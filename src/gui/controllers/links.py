"""悬浮条控制器：主页 / B站 / GitHub / 脚本目录 / 设置 / 启动游戏。

脚本路径解析（resolve_script_path）与链接回退地址（_URL_HOME / _URL_BILIBILI）
由 theme / subscript 提供；当前游戏经 _current_game（GameListController 提供，
经门面 QmlBridge 的 MRO 在运行时解析）。
"""

import os
import webbrowser

from PySide6.QtCore import Slot

from src.config.set_config import (
    get_game_bilibili as _get_game_bilibili,
)
from src.config.set_config import (
    get_game_exe_path as _get_game_exe_path,
)
from src.config.set_config import (
    get_game_github as _get_game_github,
)
from src.config.set_config import (
    get_game_homepage as _get_game_homepage,
)
from src.config.subscript import resolve_script_path
from src.gui.controllers.launch import LaunchController
from src.gui.theme import _URL_BILIBILI, _URL_HOME
from src.utils import get_config_yml_path_under_root


class LinkController(LaunchController):
    @Slot()
    def launchGame(self):
        """启动游戏：读取当前游戏 exe 路径并打开（未适配时提示）。"""
        game = self._current_game()
        exe_path = _get_game_exe_path(game["script_name"])
        if not exe_path:
            self.toastRequested.emit(f"{game['display_name']}：未找到游戏路径")
            return
        os.startfile(exe_path)  # noqa: S606 启动游戏
        self.toastRequested.emit(f"正在启动 {game['display_name']}…")

    def _open_url(self, url: str, fallback: str, label: str):
        target = url or fallback
        webbrowser.open(target)
        self.toastRequested.emit(f"打开{label}：{target}")

    @Slot()
    def openHome(self):
        """打开当前游戏官方主页（set_config 声明，空则通用占位）。"""
        self._open_url(
            _get_game_homepage(self._current_game()["script_name"]),
            _URL_HOME,
            "主页",
        )

    @Slot()
    def openBilibili(self):
        """打开当前游戏官方 B 站（set_config 声明，空则通用占位）。"""
        self._open_url(
            _get_game_bilibili(self._current_game()["script_name"]),
            _URL_BILIBILI,
            "B站",
        )

    @Slot()
    def openGithub(self):
        """打开当前脚本项目 GitHub 主页（set_config 声明，空则通用占位）。"""
        self._open_url(
            _get_game_github(self._current_game()["script_name"]),
            _URL_HOME,
            "GitHub",
        )

    @Slot()
    def openScriptFolder(self):
        """打开当前脚本所在目录（script_path 父目录，资源管理器）。"""
        game = self._current_game()
        script_path = game["script_data"].get("script_path", "")
        resolved = resolve_script_path(script_path) if script_path else None
        if not resolved:
            self.toastRequested.emit(f"{game['display_name']}：未找到脚本路径")
            return
        folder = os.path.dirname(resolved)
        if not os.path.isdir(folder):
            self.toastRequested.emit(f"{game['display_name']}：脚本目录不存在")
            return
        os.startfile(folder)  # noqa: S606 打开脚本所在目录
        self.toastRequested.emit(f"已打开 {game['display_name']} 脚本目录")

    @Slot()
    def openSettings(self):
        """打开总配置文件 config.yml（系统默认程序）；缺失时 toast 提示（对齐旧 GUI）。"""
        config_path = get_config_yml_path_under_root()
        if not os.path.isfile(config_path):
            self.toastRequested.emit("未找到 config/config.yml")
            return
        os.startfile(config_path)  # noqa: S606 打开总配置文件
        self.toastRequested.emit("已打开总配置文件 config.yml")
