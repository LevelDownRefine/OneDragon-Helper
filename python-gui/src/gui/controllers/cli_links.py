"""资源目标由 CLI 查询，打开文件和浏览器仍使用本机 GUI。"""

import os
import subprocess
import webbrowser

from PySide6.QtCore import Signal, Slot

from gui.controllers.links import LinksController


class CliLinksController(LinksController):
    iconChanged = Signal()

    def __init__(self, game_list, session, toast, parent=None):
        super().__init__(game_list, toast, parent=parent)
        self._session = session
        self._generation = 0
        self._icon_source = ""

    def refresh(self):
        self._generation += 1
        generation = self._generation
        self._icon_source = ""
        self.iconChanged.emit()
        game = self._current()
        if game is None:
            return
        name = game["script_name"]

        def loaded(icon):
            if generation != self._generation:
                return
            if (
                not isinstance(icon, dict)
                or "script_name" not in icon
                or icon["script_name"] != name
                or "path" not in icon
                or (icon["path"] is not None and not isinstance(icon["path"], str))
            ):
                raise ValueError("游戏图标数据无效")
            self._game_list.game_icon_provider.paths[name] = icon["path"]
            self._icon_source = (
                f"image://gameicon/{name}?v={generation}" if icon["path"] else ""
            )
            self.iconChanged.emit()

        def failed(failure):
            if generation == self._generation:
                self._toast(failure.message)

        self._session.call("script.icon_path", {"script_name": name}, loaded, failed)

    @Slot(result=str)
    def gameIconSource(self):
        return self._icon_source

    def _query(self, method, params, show):
        game = self._current_or_toast()
        if game is None:
            return
        generation = self._generation

        def loaded(target):
            if generation != self._generation:
                return
            if not isinstance(target, dict) or "kind" not in target:
                raise ValueError("资源目标无效")
            kind = target["kind"]
            if not isinstance(kind, str):
                raise ValueError("资源目标类型无效")
            if kind == "command":
                show(game, target)
                return
            key = (
                "reason"
                if kind == "unavailable"
                else "path"
                if kind == "association"
                else "value"
            )
            if (
                kind not in {"unavailable", "association", "path", "url"}
                or key not in target
                or not isinstance(target[key], str)
            ):
                raise ValueError("资源目标字段无效")
            if kind == "unavailable":
                self._toast(f"{game['display_name']}：{target['reason']}")
            else:
                show(game, target)

        def failed(failure):
            if generation == self._generation:
                self._toast(failure.message)

        self._session.call(
            method, {"script_name": game["script_name"], **params}, loaded, failed
        )

    @Slot()
    def launchGame(self):
        def show(game, target):
            if target["kind"] != "association" or (
                "arguments" in target and not isinstance(target["arguments"], str)
            ):
                raise ValueError("游戏启动目标无效")
            arguments = target["arguments"] if "arguments" in target else ""  # noqa: SIM401
            if self._open_path(target["path"], arguments):
                self._toast(f"正在启动 {game['display_name']}…")

        self._query("script.launch_target", {"target": "game"}, show)

    def launchScript(self):
        def show(game, target):
            try:
                if target["kind"] == "association":
                    if not self._open_path(target["path"]):
                        return
                elif target["kind"] == "command":
                    if not valid_command(target):
                        raise ValueError("脚本启动命令无效")
                    subprocess.Popen(
                        [target["program"], *target["args"]],
                        cwd=target["cwd"],
                        env={**os.environ, **target["env"]} if target["env"] else None,
                    )
                else:
                    raise ValueError("脚本启动目标无效")
            except OSError as exc:
                self._toast(f"无法启动 {game['display_name']}：{exc}")
                return
            self._toast(f"已启动 {game['display_name']}")

        self._query("script.launch_target", {"target": "script"}, show)

    def _open_resource(self, target_name, label):
        def show(game, target):
            if target["kind"] == "url":
                opened = webbrowser.open(target["value"])
                self._toast(
                    f"{'打开' if opened else '无法打开'}{label}：{target['value']}"
                )
            elif target["kind"] == "path":
                if self._open_path(target["value"]):
                    self._toast(f"已打开 {game['display_name']} {label}")
            else:
                raise ValueError("资源目标类型无效")

        self._query("script.target", {"target": target_name}, show)


def valid_command(target):
    return (
        all(key in target for key in ("program", "args", "cwd", "env"))
        and isinstance(target["program"], str)
        and bool(target["program"])
        and isinstance(target["args"], list)
        and all(isinstance(arg, str) for arg in target["args"])
        and (target["cwd"] is None or isinstance(target["cwd"], str))
        and isinstance(target["env"], dict)
        and all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in target["env"].items()
        )
    )
