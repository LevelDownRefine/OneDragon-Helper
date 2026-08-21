"""启动 / 运行控制器：启动全部 / 启动当前脚本 / 运行前校验 / 生成并运行链。

独立 QObject，依赖 game_list / task_card / service（落盘与生成链）。
"""

import os
import subprocess
import sys

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QMessageBox

from src.config.subscript import get_script_name, resolve_script_path
from src.utils_runner import build_script_command, build_shutdown_extra_args


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
        """启动全部：生成仅含启用脚本的链并运行。"""
        keys = {
            g["script_name"]
            for g, on in zip(
                self._game_list.games, self._game_list.enabled, strict=True
            )
            if on
        }
        if not keys:
            self._toast("没有启用的脚本")
            return
        if not self._confirm_run(keys):
            return
        config_data = self._service.load_config()
        self._run_chain(config_data, keys, "启动全部")

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
            os.startfile(resolved)  # noqa: S606 启动脚本本体
        self._toast(f"已启动 {game['display_name']}")

    def _confirm_run(self, enabled_keys: set) -> bool:
        """运行前校验并确认。Returns: True 继续，False 取消。"""
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
        reply = QMessageBox.question(
            None,
            "确认运行",
            f"即将运行 {len(enabled_keys)} 个脚本，是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return reply == QMessageBox.Yes

    def _run_chain(self, config_data: dict, enabled_keys: set, label: str) -> None:
        """生成并运行脚本链（真实 ChainService）。"""
        ui_state = {
            name: dict(entry) for name, entry in self._task_card.ui_state.items()
        }
        chain_path = self._service.generate_chain(
            config_data, enabled_keys, chain_name="today", ui_state=ui_state
        )
        command, cwd, env = build_script_command(["--chain", chain_path])
        command[0] = command[0].replace("pythonw.exe", "python.exe")
        command += build_shutdown_extra_args(config_data)
        creationflags = subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
        subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            creationflags=creationflags,
        )
        self._toast(f"{label}：已生成并运行链 ({len(enabled_keys)} 个脚本)")
