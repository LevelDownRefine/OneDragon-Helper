"""缺少随包后端的冻结 Qt 包：运行提示与单脚本启动交互。"""

import os
import subprocess

from PySide6.QtCore import QObject, Signal, Slot

from src.utils import open_in_explorer


class LaunchController(QObject):
    toastRequested = Signal(str)

    def __init__(self, game_list, app_service, toast, parent=None):
        super().__init__(parent)
        self._game_list = game_list
        self._app_service = app_service
        self._toast = toast

    @Slot()
    def launchAll(self, confirm: bool = True):
        """缺少独立 CLI 时提示修复安装包。"""
        self._toast("未找到独立 CLI，请重新解压完整安装包")

    @Slot()
    def launchScript(self):
        """启动当前选中脚本（直接运行，不走链）。"""
        game = self._game_list.current_game
        if game is None:
            self._toast("尚无脚本")
            return
        target = self._app_service.resolve_launch_target(game["script_name"], "script")
        assert "kind" in target
        if target["kind"] == "unavailable":
            assert "reason" in target
            self._toast(f"{game['display_name']}：{target['reason']}")
            return
        if target["kind"] == "command":
            assert all(key in target for key in ("program", "args", "cwd", "env"))
            # service 只返回覆盖项；继承当前环境，保留 PATH 等运行依赖。
            environment = {**os.environ, **target["env"]} if target["env"] else None
            subprocess.Popen(
                [target["program"], *target["args"]],
                cwd=target["cwd"],
                env=environment,
            )
        else:
            assert target["kind"] == "association" and "path" in target
            open_in_explorer(target["path"])  # noqa: S606 启动脚本本体
        self._toast(f"已启动 {game['display_name']}")
