"""悬浮条控制器：主页 / B站 / GitHub / 脚本目录 / 设置 / 启动游戏。

独立 QObject，依赖 game_list（读当前游戏）。脚本路径解析由 subscript 提供。
"""

import os
import webbrowser

from PySide6.QtCore import QObject, Signal, Slot

from src.config.set_config import get_game_exe_path as _get_game_exe_path
from src.link import get_game_link as _get_game_link
from src.log import get_log_dir
from src.service.app_service import AppService
from src.utils import get_config_yml_path_under_root, open_in_explorer
from src.utils_sub_config import resolve_script_path

# 通用占位链接（对应内容未配置时使用）
_URL_HOME = "https://github.com/LevelDownRefine/OneDragon-Helper"
_URL_BILIBILI = "https://www.bilibili.com/"


class LinksController(QObject):
    toastRequested = Signal(str)

    def __init__(self, game_list, toast, app_service=None, parent=None):
        super().__init__(parent)
        self._game_list = game_list
        self._toast = toast
        self._app_service = app_service or AppService()

    @Slot()
    def launchGame(self):
        """启动游戏：读取当前游戏 exe 路径并打开（未适配时提示）。"""
        game = self._game_list.current_game
        exe_path = _get_game_exe_path(game["script_name"])
        if not exe_path:
            self._toast(f"{game['display_name']}：未找到游戏路径")
            return
        open_in_explorer(exe_path)
        self._toast(f"正在启动 {game['display_name']}…")

    def _open_url(self, url: str, fallback: str, label: str):
        target = url or fallback
        webbrowser.open(target)
        self._toast(f"打开{label}：{target}")

    @Slot()
    def openHome(self):
        """打开当前游戏官方主页（link 声明，空则通用占位）。"""
        self._open_url(
            _get_game_link(self._game_list.current_game["script_name"], "homepage"),
            _URL_HOME,
            "主页",
        )

    @Slot()
    def openBilibili(self):
        """打开当前游戏官方 B 站（link 声明，空则通用占位）。"""
        self._open_url(
            _get_game_link(self._game_list.current_game["script_name"], "bilibili"),
            _URL_BILIBILI,
            "B站",
        )

    @Slot()
    def openGithub(self):
        """打开当前脚本项目 GitHub 主页（link 声明，空则通用占位）。"""
        self._open_url(
            _get_game_link(self._game_list.current_game["script_name"], "github"),
            _URL_HOME,
            "GitHub",
        )

    @Slot()
    def openScriptFolder(self):
        """打开当前脚本所在目录（script_path 父目录，资源管理器）。"""
        game = self._game_list.current_game
        script_path = game["script_data"].get("script_path", "")
        resolved = resolve_script_path(script_path) if script_path else None
        if not resolved:
            self._toast(f"{game['display_name']}：未找到脚本路径")
            return
        folder = os.path.dirname(resolved)
        if not os.path.isdir(folder):
            self._toast(f"{game['display_name']}：脚本目录不存在")
            return
        open_in_explorer(folder)
        self._toast(f"已打开 {game['display_name']} 脚本目录")

    @Slot()
    def openLogFolder(self):
        """打开当前脚本运行日志目录（资源管理器）；无匹配解析器或目录缺失时提示。"""
        game = self._game_list.current_game
        script_path = game["script_data"].get("script_path", "")
        resolved = resolve_script_path(script_path) if script_path else None
        if not resolved:
            self._toast(f"{game['display_name']}：未找到脚本路径")
            return
        log_dir = get_log_dir(game["script_name"], resolved)
        if log_dir is None:
            self._toast(f"{game['display_name']}：暂不支持日志跳转")
            return
        if not os.path.isdir(log_dir):
            self._toast(f"{game['display_name']}：日志目录不存在")
            return
        open_in_explorer(log_dir)
        self._toast(f"已打开 {game['display_name']} 日志目录")

    @Slot()
    def openSettings(self):
        """打开总配置文件 config.yml（系统默认程序），缺失时提示。"""
        config_path = get_config_yml_path_under_root()
        if not os.path.isfile(config_path):
            self._toast("未找到 config/config.yml")
            return
        open_in_explorer(config_path)
        self._toast("已打开总配置文件 config.yml")

    @Slot()
    def openScriptConfig(self):
        """打开当前脚本专属配置文件（python→源码；exe→内部 config），未适配或缺失时提示。"""
        game = self._game_list.current_game
        path, error = self._app_service.config_file_path(game["script_name"])
        if error is not None:
            self._toast(f"{game['display_name']}：{error}")
            return
        open_in_explorer(path)
        self._toast(f"已打开 {game['display_name']} 配置文件")
