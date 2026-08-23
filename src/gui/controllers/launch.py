"""启动 / 运行控制器：启动全部 / 启动当前脚本 / 运行前校验 / 生成并运行链。

独立 QObject，依赖 game_list / task_card / service（落盘与生成链）。
"""

import os
import subprocess
from collections.abc import Callable

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QDialog, QMessageBox

from src.config.subscript import get_script_name, resolve_script_path
from src.gui.run_confirm_dialog import RunConfirmDialog
from src.utils import open_in_explorer
from src.utils_runner import (
    apply_mute_config,
    apply_shutdown_config,
    apply_timed_run_config,
    build_script_command,
    next_target_datetime,
    parse_mute_run,
    parse_shutdown,
    parse_timed_run,
    spawn_schedule_run,
)
from src.utils_shutdown import shutdown_sys


class LaunchController(QObject):
    toastRequested = Signal(str)

    def __init__(self, game_list, task_card, service, toast, parent=None):
        super().__init__(parent)
        self._game_list = game_list
        self._task_card = task_card
        self._service = service
        self._toast = toast

    @Slot()
    def launchAll(self):
        """启动全部：先校验，再按需等待后运行。

        生成+运行+关机/静音命令构造、定时等待与到点触发统一交由 service
        （即时 ``run_chain_once`` / 定时 ``spawn_schedule_run``+``ChainService.schedule_run``）；
        本方法仅负责 UI 流程：计算启用集合、弹确认窗、解析定时配置，并把定时等待委托出去。
        """
        enabled_script_names = {
            g["script_name"]
            for g, game_enabled in zip(
                self._game_list.games, self._game_list.enabled, strict=True
            )
            if game_enabled
        }
        if not enabled_script_names:
            self._toast("没有启用的脚本")
            return
        if not self._confirm_run(enabled_script_names):
            return
        config_data = self._service.load_config()
        shutdown_delay = parse_shutdown(config_data)
        mute = parse_mute_run(config_data)
        timed_enabled, timed_target = parse_timed_run(config_data)
        if not timed_enabled:
            post_run = self._build_post_run(shutdown_delay)
            self._service.run_chain_once(
                enabled_script_names, mute=mute, post_run=post_run
            )
            self._toast(
                f"启动全部：已生成并运行链 ({len(enabled_script_names)} 个脚本)"
            )
            return
        # parse_timed_run 保证 timed_enabled=True 时 timed_target 必为合法 HH:MM。
        assert timed_target is not None, "timed_enabled=True 但 timed_target 缺失"
        # 定时运行起独立控制台进程（关闭控制台即取消，关程序不影响），
        # 真实实现见 ChainService.schedule_run（等待→生成→运行→关机）。
        spawn_schedule_run(
            enabled_script_names,
            timed_target,
            mute=mute,
            shutdown_delay=shutdown_delay,
        )
        target_dt = next_target_datetime(timed_target)
        self._toast(
            f"已设置定时运行：将于 {target_dt:%Y-%m-%d %H:%M} 重新生成脚本链并运行"
            f"（关闭控制台即取消）"
        )

    def _build_post_run(self, shutdown_delay: int | None) -> list[Callable[[], None]]:
        """构造运行后动作列表；启用关机时把关机作为最后一项追加。

        关机必须等全部运行（含重跑）结束才执行，故放在 post_run 末位，交由
        service 在链运行结束后统一触发，而非经 runner 的 --shutdown 子进程关机。

        Args:
            shutdown_delay: 关机延迟秒数；None/0 表示不关机。

        Returns:
            后置步骤列表（可能为空）。
        """
        post_run: list[Callable[[], None]] = []
        if shutdown_delay:
            post_run.append(lambda: shutdown_sys(shutdown_delay))
        return post_run

    @Slot()
    def launchScript(self):
        """启动当前选中脚本（直接运行，不走链）。"""
        game = self._game_list.current_game
        script = game["script_data"]
        if script.get("script_type") == "python":
            resolved = resolve_script_path(script["script_path"])
            if not resolved or not os.path.isfile(resolved):
                self._toast(f"找不到脚本文件：{script['script_path']}")
                return
            command, cwd, env = build_script_command(["--script", resolved])
            subprocess.Popen(command, cwd=cwd, env=env)
        else:
            exe_path = script.get("script_path", "")
            resolved = resolve_script_path(exe_path) if exe_path else None
            if not resolved or not os.path.isfile(resolved):
                self._toast(f"找不到脚本：{exe_path}")
                return
            open_in_explorer(resolved)  # noqa: S606 启动脚本本体
        self._toast(f"已启动 {game['display_name']}")

    def _confirm_run(self, enabled_keys: set) -> bool:
        """运行前校验并确认（含自动关机 / 定时计划配置）。Returns: True 继续，False 取消。"""
        config_data = self._service.load_config()
        enabled_scripts = [
            s for s in config_data["script_list"] if get_script_name(s) in enabled_keys
        ]
        invalid = self._service.collect_invalid_scripts(enabled_scripts)
        if invalid:
            details = "\n".join(f"· {name}：{msg}" for name, msg in invalid)
            reply = QMessageBox.warning(
                None,
                "脚本配置不合法",
                f"以下脚本配置不合法，运行时会被跳过：\n{details}\n\n是否仍然运行？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return False

        # 回显 config 当前自动关机 / 定时计划配置到确认弹窗。
        shutdown_cfg = config_data.get("shutdown")
        shutdown_enabled = bool(
            isinstance(shutdown_cfg, dict) and shutdown_cfg.get("after_run", False)
        )
        shutdown_delay = (
            int(shutdown_cfg.get("delay_seconds", 0))
            if isinstance(shutdown_cfg, dict)
            else 0
        )
        timed_enabled, timed_target = parse_timed_run(config_data)
        mute_enabled = parse_mute_run(config_data)

        dialog = RunConfirmDialog(
            len(enabled_keys),
            shutdown_enabled=shutdown_enabled,
            shutdown_delay=shutdown_delay,
            timed_enabled=timed_enabled,
            timed_target=timed_target or "04:10",
            mute_enabled=mute_enabled,
        )
        if dialog.exec() != QDialog.Accepted:
            return False

        # 把弹窗勾选项写回 config.yml（与现有 service 写盘路径一致）。
        res = dialog.result
        assert res is not None, "[launch] 弹窗 accept 但 result 为 None"
        apply_shutdown_config(
            config_data,
            enabled=res["shutdown_enabled"],
            delay_seconds=res["shutdown_delay"],
        )
        apply_timed_run_config(
            config_data,
            enabled=res["timed_enabled"],
            target_time=res["timed_target"],
        )
        apply_mute_config(config_data, enabled=res["mute_enabled"])
        self._service.save_config(config_data)
        return True
