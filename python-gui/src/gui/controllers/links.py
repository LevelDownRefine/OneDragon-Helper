"""悬浮条控制器：主页 / B站 / GitHub / 脚本目录 / 设置 / 启动游戏。

独立 QObject，依赖 game_list（读当前游戏）。资源与启动目标解析统一委托 AppService。
"""

import os
import subprocess
import webbrowser

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from src.service.app_service import AppService
from src.utils import get_config_yml_path_under_root, open_in_explorer


class LinksController(QObject):
    toastRequested = Signal(str)

    def __init__(self, game_list, toast, app_service=None, parent=None):
        super().__init__(parent)
        self._game_list = game_list
        self._toast = toast
        self._app_service = app_service or AppService()
        self._game_launches = []
        self._game_launch_timer = QTimer(self)
        self._game_launch_timer.setInterval(250)
        self._game_launch_timer.timeout.connect(self._poll_game_launches)

    def _open_path(self, path: str, arguments: str = "") -> bool:
        """用系统默认程序打开；无关联程序等 OSError 转 toast 并返回 False。

        os.startfile 对未关联文件类型（如 .yml 无默认程序）会抛 OSError，
        从 QML 槽逃逸即崩，故统一在此收口。
        """
        try:
            if arguments:
                open_in_explorer(path, arguments)
            else:
                open_in_explorer(path)
        except OSError as e:
            self._toast(f"无法打开：{e}")
            return False
        return True

    def _open_launch_target(self, target: dict, game: bool = False) -> bool:
        """执行关联或独立命令；游戏启动 CLI 在后台运行并检查退出结果。"""
        label = "游戏" if game else "脚本"
        if target["kind"] == "association":
            arguments = target["arguments"] if "arguments" in target else ""  # noqa: SIM401
            return self._open_path(target["path"], arguments)
        if target["kind"] != "command":
            raise ValueError(f"{label}启动目标无效")
        if not all(key in target for key in ("program", "args", "cwd", "env")):
            self._toast(f"{label}启动命令无效")
            return False
        options = (
            {
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
                "creationflags": subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            }
            if game
            else {}
        )
        try:
            child = subprocess.Popen(
                [target["program"], *target["args"]],
                cwd=target["cwd"],
                env={**os.environ, **target["env"]} if target["env"] else None,
                **options,
            )
        except OSError as error:
            self._toast(f"无法启动{label}：{error}")
            return False
        if game:
            self._game_launches.append(child)
            self._game_launch_timer.start()
        return True

    def _poll_game_launches(self):
        for child in self._game_launches[:]:
            try:
                code = child.poll()
            except OSError as error:
                self._game_launches.remove(child)
                self._toast(f"无法读取游戏启动结果：{error}")
                continue
            if code is not None:
                self._game_launches.remove(child)
                if code != 0:
                    self._toast(f"游戏启动失败（退出码 {code}），详情见助手日志")
        if not self._game_launches:
            self._game_launch_timer.stop()

    def _current(self) -> dict | None:
        """当前脚本；config 删空（无脚本）时 None，调用方据此提示后返回。"""
        return self._game_list.current_game

    def _current_or_toast(self) -> dict | None:
        """取当前脚本；无脚本时 toast 提示并返回 None，调用方据此提前 return。"""
        game = self._current()
        if game is None:
            self._toast("尚无脚本")
        return game

    @Slot()
    def launchGame(self):
        """启动游戏：读取当前游戏 exe 路径并打开（未适配时提示）。"""
        game = self._current_or_toast()
        if game is None:
            return
        target = self._app_service.resolve_launch_target(game["script_name"], "game")
        assert "kind" in target
        if target["kind"] == "unavailable":
            assert "reason" in target
            self._toast(f"{game['display_name']}：{target['reason']}")
            return
        if self._open_launch_target(target, game=True):
            self._toast(f"正在启动 {game['display_name']}…")

    @Slot(result=str)
    def gameIconSource(self) -> str:
        """悬停时返回当前游戏图标源；缺路径或无图标时由 QML 提示启动游戏。

        返回 ``image://gameicon/<script_name>``：图标由 GameIconProvider 按 script_name
        解析游戏 exe 并取内嵌图标（近显示分辨率），避免 data URL 直给 256 档被 QML
        下采样混叠。
        """
        game = self._current()
        if game is None:
            return ""
        assert "script_name" in game
        icon = self._app_service.game_icon_path(game["script_name"])
        assert "path" in icon
        return f"image://gameicon/{game['script_name']}" if icon["path"] else ""

    def _open_resource(self, target_name: str, label: str):
        game = self._current_or_toast()
        if game is None:
            return
        target = self._app_service.resolve_script_target(
            game["script_name"], target_name
        )
        assert "kind" in target
        if target["kind"] == "unavailable":
            assert "reason" in target
            self._toast(f"{game['display_name']}：{target['reason']}")
            return
        assert "value" in target
        value = target["value"]
        if target["kind"] == "url":
            opened = webbrowser.open(value)
            self._toast(
                f"打开{label}：{value}" if opened else f"无法打开{label}：{value}"
            )
        else:
            assert target["kind"] == "path"
            if self._open_path(value):
                self._toast(f"已打开 {game['display_name']} {label}")

    @Slot()
    def openHome(self):
        self._open_resource("home", "主页")

    @Slot()
    def openBilibili(self):
        self._open_resource("bili", "B站")

    @Slot()
    def openGithub(self):
        self._open_resource("github", "GitHub")

    @Slot()
    def openScriptFolder(self):
        self._open_resource("folder", "脚本目录")

    @Slot()
    def openLogFolder(self):
        self._open_resource("log", "日志目录")

    @Slot()
    def openSettings(self):
        """打开总配置文件 config.yml（系统默认程序），缺失时提示。"""
        config_path = get_config_yml_path_under_root()
        if not os.path.isfile(config_path):
            self._toast("未找到 config/config.yml")
            return
        if self._open_path(config_path):
            self._toast("已打开总配置文件 config.yml")

    @Slot()
    def openScriptConfig(self):
        """打开当前脚本专属配置文件（python→源码；exe→内部 config），未适配或缺失时提示。"""
        self._open_resource("configfile", "配置文件")
