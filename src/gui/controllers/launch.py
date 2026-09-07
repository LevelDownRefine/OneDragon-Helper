"""启动 / 运行控制器：启动全部 / 启动当前脚本 / 运行前校验 / 生成并运行链。

独立 QObject，依赖 game_list / task_card / service（落盘与生成链）。
"""

import os
import subprocess

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QDialog, QMessageBox

from src.gui.run_confirm_dialog import RunConfirmDialog
from src.utils import open_in_explorer
from src.utils.utils_runner import build_script_command, spawn_schedule_run
from src.utils.utils_sub_config import get_script_name, resolve_script_path
from src.utils.utils_weekly import next_target_datetime


class LaunchController(QObject):
    toastRequested = Signal(str)

    def __init__(self, game_list, task_card, app_service, toast, parent=None):
        super().__init__(parent)
        self._game_list = game_list
        self._task_card = task_card
        self._app_service = app_service
        self._toast = toast

    @Slot()
    def launchAll(self, confirm: bool = True):
        """启动全部：先校验，再经 spawn_schedule_run 运行。

        即时与定时两条路径统一经 ``spawn_schedule_run`` 起独立控制台进程，由
        ``chain_service.schedule_run`` 处理逻辑（生成→运行→重跑→邮件/关机）；二者差异
        仅在于是否等待：定时等待到目标时刻，即时（target=now）不等待。关闭控制台即取消、
        GUI 退出不影响（进程独立存活）。
        本方法仅负责 UI 流程：计算启用集合、弹确认窗、解析定时/关机/静音配置。

        Args:
            confirm: 是否弹运行前确认窗（含不合法告警与调度配置回显）。GUI 打开后的
                无人值守启动传 ``False``，直接按上次落盘的 schedule/config 启动全部。
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
        if confirm and not self._confirm_run(enabled_script_names):
            return
        options = self._app_service.load_run_options()
        run_target = options.timed_target if options.timed_enabled else "now"
        if options.timed_enabled:
            target_dt = next_target_datetime(run_target)
            msg = f"定时运行：将于 {target_dt:%Y-%m-%d %H:%M} 重新生成脚本链并运行"
        else:
            msg = f"启动全部：已在新控制台窗口生成并运行链 ({len(enabled_script_names)} 个脚本)"
        proc = spawn_schedule_run(
            enabled_script_names,
            run_target,
            mute=options.mute_enabled,
            shutdown_delay=(
                options.shutdown_delay
                if options.shutdown_enabled and options.shutdown_delay > 0
                else None
            ),
            close_running=options.close_running_enabled,
        )
        if proc is None:
            # 起进程失败（Popen 异常已被 spawn 记日志）：不报成功，引导看日志。
            self._toast("启动失败，详见 logs/onedragon_helper.log")
            return
        self._toast(f"{msg}（关闭控制台即取消）")

    @Slot()
    def launchScript(self):
        """启动当前选中脚本（直接运行，不走链）。"""
        game = self._game_list.current_game
        script = game["script_data"]
        # script_type 可缺省（load_config 仅断言 display_name/script_path），缺省按 external
        if script.get("script_type", "external") == "python":
            resolved = resolve_script_path(script["script_path"])
            if not resolved or not os.path.isfile(resolved):
                self._toast(f"找不到脚本文件：{script['script_path']}")
                return
            command, cwd, env = build_script_command(["--script", resolved])
            subprocess.Popen(command, cwd=cwd, env=env)
        else:
            exe_path = script["script_path"]
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

        # 回显 schedule 当前运行选项到确认弹窗（RunOptions 为单一 schema）。
        options = self._app_service.load_run_options()
        dialog = RunConfirmDialog(len(enabled_keys), options)
        if dialog.exec() != QDialog.Accepted:
            return False

        # 弹窗勾选项的落盘（schedule.yml + 授权码凭据）整体经 service。
        res = dialog.result
        assert res is not None, "[launch] 弹窗 accept 但 result 为 None"
        self._app_service.apply_run_options(res)
        return True
