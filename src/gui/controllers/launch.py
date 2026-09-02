"""启动 / 运行控制器：启动全部 / 启动当前脚本 / 运行前校验 / 生成并运行链。

独立 QObject，依赖 game_list / task_card / service（落盘与生成链）。
"""

import os
import subprocess

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QDialog, QMessageBox

from src.gui.run_confirm_dialog import RunConfirmDialog
from src.utils import open_in_explorer
from src.utils_runner import (
    apply_close_running_config,
    apply_mute_config,
    apply_notify_config,
    apply_rerun_config,
    apply_shutdown_config,
    apply_timed_run_config,
    build_script_command,
    parse_close_running,
    parse_mute_run,
    parse_notify_enabled,
    parse_rerun_config,
    parse_shutdown,
    parse_timed_run,
    spawn_schedule_run,
)
from src.utils_sub_config import get_script_name, resolve_script_path
from src.utils_weekly import next_target_datetime


class LaunchController(QObject):
    toastRequested = Signal(str)

    def __init__(self, game_list, task_card, app_service, toast, parent=None):
        super().__init__(parent)
        self._game_list = game_list
        self._task_card = task_card
        self._app_service = app_service
        self._toast = toast

    @Slot()
    def launchAll(self):
        """启动全部：先校验，再经 spawn_schedule_run 运行。

        即时与定时两条路径统一经 ``spawn_schedule_run`` 起独立控制台进程，由
        ``chain_service.schedule_run`` 处理逻辑（生成→运行→重跑→邮件/关机）；二者差异
        仅在于是否等待：定时等待到目标时刻，即时（target=now）不等待。关闭控制台即取消、
        GUI 退出不影响（进程独立存活）。
        本方法仅负责 UI 流程：计算启用集合、弹确认窗、解析定时/关机/静音配置。
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
        schedule_data = self._app_service.load_schedule()
        shutdown_delay = parse_shutdown(schedule_data)
        mute = parse_mute_run(schedule_data)
        close_running = parse_close_running(schedule_data)
        timed_enabled, timed_target = parse_timed_run(schedule_data)
        run_target = timed_target if timed_enabled else "now"
        if timed_enabled:
            target_dt = next_target_datetime(run_target)
            msg = f"定时运行：将于 {target_dt:%Y-%m-%d %H:%M} 重新生成脚本链并运行"
        else:
            msg = f"启动全部：已在新控制台窗口生成并运行链 ({len(enabled_script_names)} 个脚本)"
        self._toast(f"{msg}（关闭控制台即取消）")
        spawn_schedule_run(
            enabled_script_names,
            run_target,
            mute=mute,
            shutdown_delay=shutdown_delay,
            close_running=close_running,
        )

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
        config_data = self._app_service.load_config()
        enabled_scripts = [
            s for s in config_data["script_list"] if get_script_name(s) in enabled_keys
        ]
        invalid = self._app_service.collect_invalid_scripts(enabled_scripts)
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

        # 回显 schedule 当前自动关机 / 定时计划配置到确认弹窗。
        schedule_data = self._app_service.load_schedule()
        shutdown_cfg = schedule_data.get("shutdown")
        shutdown_enabled = bool(
            isinstance(shutdown_cfg, dict) and shutdown_cfg.get("after_run", False)
        )
        shutdown_delay = (
            int(shutdown_cfg.get("delay_seconds", 0))
            if isinstance(shutdown_cfg, dict)
            else 0
        )
        timed_enabled, timed_target = parse_timed_run(schedule_data)
        mute_enabled = parse_mute_run(schedule_data)
        close_running_enabled = parse_close_running(schedule_data)
        rerun_enabled = parse_rerun_config(schedule_data)
        notify_enabled = parse_notify_enabled(schedule_data)

        dialog = RunConfirmDialog(
            len(enabled_keys),
            shutdown_enabled=shutdown_enabled,
            shutdown_delay=shutdown_delay,
            timed_enabled=timed_enabled,
            timed_target=timed_target,
            mute_enabled=mute_enabled,
            close_running_enabled=close_running_enabled,
            rerun_enabled=rerun_enabled,
            notify_enabled=notify_enabled,
        )
        if dialog.exec() != QDialog.Accepted:
            return False

        # 把弹窗勾选项写回 schedule.yml（调度参数独立存放）。
        res = dialog.result
        assert res is not None, "[launch] 弹窗 accept 但 result 为 None"
        # 关机：启用/关闭都直接落盘（含延迟数值），行为单一稳定。
        apply_shutdown_config(
            schedule_data,
            enabled=res["shutdown_enabled"],
            delay_seconds=res["shutdown_delay"],
        )
        apply_timed_run_config(
            schedule_data,
            enabled=res["timed_enabled"],
            target_time=res["timed_target"],
        )
        apply_mute_config(schedule_data, enabled=res["mute_enabled"])
        apply_close_running_config(schedule_data, enabled=res["close_running_enabled"])
        apply_rerun_config(schedule_data, enabled=res["rerun_enabled"])
        apply_notify_config(schedule_data, enabled=res["notify_enabled"])
        self._app_service.save_schedule(schedule_data)
        return True
