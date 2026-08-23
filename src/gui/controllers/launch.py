"""启动 / 运行控制器：启动全部 / 启动当前脚本 / 运行前校验 / 生成并运行链。

独立 QObject，依赖 game_list / task_card / service（落盘与生成链）。
"""

import os
import subprocess
import sys
from datetime import datetime

from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtWidgets import QMessageBox

from src.config.subscript import get_script_name, resolve_script_path
from src.utils_runner import (
    build_script_command,
    build_shutdown_extra_args,
    next_target_datetime,
    parse_timed_run,
)

# 定时运行的轮询间隔：兼容系统休眠/唤醒，唤醒后立即判断是否已到点。
_TIMED_POLL_SECONDS = 30


class LaunchController(QObject):
    toastRequested = Signal(str)

    def __init__(self, game_list, task_card, service, toast, parent=None):
        super().__init__(parent)
        self._game_list = game_list
        self._task_card = task_card
        self._service = service
        self._toast = toast
        self._timed_timer = QTimer(self)
        self._timed_timer.setInterval(_TIMED_POLL_SECONDS * 1000)
        self._timed_timer.timeout.connect(self._on_timed_tick)

    @Slot()
    def launchAll(self):
        """启动全部：先生成脚本链（确保能生成），再按需等待后运行。

        若 config 的 timed_run 启用，则进入等待，到 target_time 那一刻重新生成脚本链
        （按当时星期挑选脚本，周常/周几起逐日生效）并运行；否则立即运行。

        启用脚本集合为点击「启动全部」那一刻的快照（self._game_list.enabled），
        等待期改 config.yml 不生效——定时到点按当时星期重新生成 today.yml。
        """
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
        # 先生成一次，确保链能生成（避免在漫长等待后才失败）。
        try:
            chain_path = self._generate_chain(config_data, keys)
        except Exception as e:  # 生成失败：立即反馈，不进入等待
            self._toast(f"生成脚本链失败：{e}")
            return
        enabled, target_time = parse_timed_run(config_data)
        if not enabled:
            self._run_chain(chain_path, keys, "启动全部")
            return
        # parse_timed_run 保证 enabled=True 时 target_time 必为合法 HH:MM。
        assert target_time is not None, "enabled=True 但 target_time 缺失"
        try:
            self._schedule_timed_run(keys, target_time)
        except Exception as e:  # 调度失败（如时刻解析异常）：反馈且不残留定时器
            self._toast(f"设置定时运行失败：{e}")
            if self._timed_timer.isActive():
                self._timed_timer.stop()

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

    def _generate_chain(self, enabled_keys: set) -> str:
        """生成仅含启用脚本的 today.yml（按当前星期挑选），返回链文件路径。

        启用集合取自启动时刻 snapshot（self._game_list），等待期改 config.yml 不生效。
        """
        ui_state = {
            name: dict(entry) for name, entry in self._task_card.ui_state.items()
        }
        config_data = self._service.load_config()
        return self._service.generate_chain(
            config_data, enabled_keys, chain_name="today", ui_state=ui_state
        )

    def _run_chain(self, chain_path: str, enabled_keys: set, label: str) -> None:
        """运行已生成的脚本链（真实 ChainService）。"""
        command, cwd, env = build_script_command(["--chain", chain_path])
        command[0] = command[0].replace("pythonw.exe", "python.exe")
        config_data = self._service.load_config()
        command += build_shutdown_extra_args(config_data)
        creationflags = subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
        subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            creationflags=creationflags,
        )
        self._toast(f"{label}：已生成并运行链 ({len(enabled_keys)} 个脚本)")

    def _schedule_timed_run(self, enabled_keys: set, target_time: str) -> None:
        """进入等待：到 target_time 重新生成脚本链并运行。关闭程序会取消等待。

        关闭程序即取消等待（QTimer 随进程退出）；等待期改 config.yml 不生效——
        启动一刻的 snapshot 已冻结，到点按当时星期重新生成 today.yml。
        """
        assert target_time is not None, "target_time 为 None 时不应进入定时"
        self._timed_keys = enabled_keys
        self._timed_target = next_target_datetime(target_time)
        target_str = self._timed_target.strftime("%Y-%m-%d %H:%M")
        self._toast(
            f"已设置定时运行：将于 {target_str} 重新生成脚本链并运行（关闭程序将取消）"
        )
        self._timed_timer.start()

    def _on_timed_tick(self) -> None:
        """定时轮询：到点则停止轮询、重新生成链（按当时星期）并运行。"""
        if datetime.now() < self._timed_target:
            return
        self._timed_timer.stop()
        keys = self._timed_keys
        # 重新生成 today.yml：weekly_timeouts / weekly_start 随当天星期变动，
        # 不依赖等待期改过的 config.yml（按启动快照的 keys 重新挑选）。
        try:
            chain_path = self._generate_chain(keys)
        except Exception as e:
            self._toast(f"定时运行：重新生成脚本链失败：{e}")
            return
        self._run_chain(chain_path, keys, "定时运行")
