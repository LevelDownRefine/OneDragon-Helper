"""脚本列表的协议适配；模型和文件选择交互复用原控制器。"""

import os
from dataclasses import asdict

from PySide6.QtCore import Signal, Slot

from gui.controllers.game_list import C_GAME_DIM, GameListController


class CliGameListController(GameListController):
    loaded = Signal()
    loadFailed = Signal()

    def __init__(self, session, toast, on_reload, parent=None):
        super().__init__(None, toast, on_reload, parent)
        self._session = session
        self._enabled = []
        self._generation = 0
        self._editing = False
        self._mutating = False
        self._selection_generation = 0
        self.currentIndexChanged.connect(self._selection_changed)
        self.game_icon_provider.paths = {}

    def _selection_changed(self):
        self._selection_generation += 1

    def reload_games(self):
        self._generation += 1
        generation = self._generation

        def loaded(snapshot):
            if generation != self._generation:
                return
            if not valid_snapshot(snapshot):
                raise ValueError("脚本列表无效")
            games = [
                {
                    "display_name": row["display_name"],
                    "script_name": row["script_name"],
                    "script_data": row["script_data"],
                    "icon_path": row["icon_path"] or snapshot["default_icon_path"],
                    "char": row["display_name"][0],
                    "color": C_GAME_DIM,
                }
                for row in snapshot["scripts"]
            ]
            current = self.current_game
            name = current["script_name"] if current is not None else None
            self._set_games(games)
            if name is not None:
                for index, game in enumerate(games):
                    if game["script_name"] == name and index != self.current_index:
                        self.current_index = index
                        self.currentIndexChanged.emit()
                        break
            self.loaded.emit()

        def failed(failure):
            if generation == self._generation:
                self._toast(failure.message)
                self.loadFailed.emit()

        self._session.call("app.snapshot", {}, loaded, failed)

    def _write(self, method, params, message, success=None):
        if self._mutating:
            self._toast("正在保存脚本列表，请稍候")
            return
        self._mutating = True

        def saved(result):
            self._mutating = False
            if method == "script.add":
                if not isinstance(result, dict) or not all(
                    key in result and isinstance(result[key], str)
                    for key in ("script_name", "display_name")
                ):
                    raise ValueError("添加响应无效")
            elif result is not None:
                raise ValueError("写操作应返回 null")
            self._on_reload()
            self._toast(message)
            if success is not None:
                success()

        def failed(failure):
            self._mutating = False
            self._toast(failure.message)
            # 传输断开时由用户刷新重连；可能已写盘的业务错误仅反读。
            if failure.refresh_required and failure.code != "transport_failed":
                self._on_reload()

        self._session.call(method, params, saved, failed)

    @Slot(int, int)
    def reorderGames(self, src_index, dst_index):
        assert 0 <= src_index < len(self._games)
        assert 0 <= dst_index < len(self._games)
        if src_index != dst_index:
            names = [game["script_name"] for game in self._games]
            names.insert(dst_index, names.pop(src_index))
            self._write("script.reorder", {"script_names": names}, "已调整脚本顺序")

    @Slot()
    def addScript(self):
        from gui.dialogs import SCRIPT_FILE_FILTER, pick_file

        path = pick_file(None, "选择脚本文件", SCRIPT_FILE_FILTER)
        if path:
            self._write(
                "script.add", {"file_path": path}, "已添加脚本", self.gameAdded.emit
            )

    @Slot("QVariantList", result=bool)
    def dropScripts(self, urls):
        paths = self._script_drop_paths(urls)
        if not paths or self._mutating:
            self._toast("请拖入有效脚本文件，或等待当前保存完成")
            return False
        # 返回表示已接受拖入；结果由异步回调通知，不能冒充保存成功。
        self._mutating = True
        results = []
        added = 0

        def next_path():
            if len(results) == len(paths):
                self._mutating = False
                self._on_reload()
                self._toast("\n".join(results))
                if added:
                    self.gameAdded.emit()
                return
            path = paths[len(results)]

            def saved(result):
                nonlocal added
                if (
                    not isinstance(result, dict)
                    or "display_name" not in result
                    or not isinstance(result["display_name"], str)
                ):
                    raise ValueError("添加响应无效")
                results.append(f"已添加 {result['display_name']}")
                added += 1
                next_path()

            def failed(failure):
                results.append(f"{os.path.basename(path)}：{failure.message}")
                if failure.code == "transport_failed":
                    self._mutating = False
                    self._toast("\n".join(results))
                    if added:
                        self._on_reload()
                        self.gameAdded.emit()
                    return
                next_path()

            self._session.call("script.add", {"file_path": path}, saved, failed)

        next_path()
        return True

    def _on_delete_script(self, script_name):
        self._write("script.remove", {"script_name": script_name}, "已删除脚本")

    @Slot()
    def configCurrent(self):
        game = self.current_game
        if game is None or self._editing:
            return
        self._editing = True
        name = game["script_name"]
        generation = (self._selection_generation, self._generation)

        def failed(failure):
            self._editing = False
            self._toast(failure.message)

        def loaded(view):
            self._editing = False
            current = self.current_game
            if (
                current is None
                or current["script_name"] != name
                or generation != (self._selection_generation, self._generation)
            ):
                return
            if not valid_edit_view(view, name):
                raise ValueError("脚本编辑数据无效")
            from gui.dialogs import SingleScriptConfigDialog, show_warning

            dialog = SingleScriptConfigDialog(
                name,
                view["script"]["display_name"],
                view["script"]["script_path"],
                edit_view=view,
            )
            saving = False

            def save(edit):
                nonlocal saving
                if saving:
                    return
                saving = True

                def rejected(failure):
                    nonlocal saving
                    saving = False
                    if dialog.isVisible():
                        show_warning(dialog, failure.message)
                    else:
                        self._toast(failure.message)

                def saved(result):
                    nonlocal saving
                    saving = False
                    if (
                        not isinstance(result, dict)
                        or "script_name" not in result
                        or not isinstance(result["script_name"], str)
                    ):
                        raise ValueError("保存响应无效")
                    dialog.accept()
                    self._on_reload()
                    self._toast(f"已保存 {edit.display_name} 配置")

                self._session.call("script.edit_save", asdict(edit), saved, rejected)

            dialog.saveRequested.connect(save)
            dialog.exec()

        self._session.call("script.edit_view", {"script_name": name}, loaded, failed)


def valid_snapshot(value):
    if (
        not isinstance(value, dict)
        or "scripts" not in value
        or not isinstance(value["scripts"], list)
        or "default_icon_path" not in value
        or not isinstance(value["default_icon_path"], str)
    ):
        return False
    names = set()
    for row in value["scripts"]:
        if (
            not isinstance(row, dict)
            or not all(
                key in row and isinstance(row[key], str) and row[key]
                for key in ("script_name", "display_name")
            )
            or "script_path" not in row
            or not isinstance(row["script_path"], str)
            or "script_data" not in row
            or not isinstance(row["script_data"], dict)
            or "icon_path" not in row
            or (row["icon_path"] is not None and not isinstance(row["icon_path"], str))
            or "adapted" not in row
            or type(row["adapted"]) is not bool
        ):
            return False
        if row["script_name"] in names:
            return False
        names.add(row["script_name"])
    return True


def valid_edit_view(value, name):
    if (
        not isinstance(value, dict)
        or not all(
            key in value
            for key in ("script_name", "script", "weekly_timeouts", "switches")
        )
        or value["script_name"] != name
        or not isinstance(value["script"], dict)
    ):
        return False
    timeouts = value["weekly_timeouts"]
    switches = value["switches"]
    script = value["script"]
    if (
        not all(
            key in script and isinstance(script[key], str)
            for key in ("display_name", "script_path")
        )
        or not script["display_name"]
    ):
        return False
    for key in (
        "display_name",
        "script_path",
        "script_type",
        "script_arguments",
        "check_done",
        "game_process_name",
        "game_path",
        "game_arguments",
    ):
        if key in script and not isinstance(script[key], str):
            return False
    for key in ("kill_script_after_done", "kill_game_after_done", "block"):
        if key in script and type(script[key]) is not bool:
            return False
    return (
        isinstance(timeouts, list)
        and len(timeouts) == 7
        and all(
            item is None or type(item) is int and 0 <= item <= 86400
            for item in timeouts
        )
        and isinstance(switches, list)
        and all(
            isinstance(row, dict)
            and "name" in row
            and isinstance(row["name"], str)
            and "enabled" in row
            and type(row["enabled"]) is bool
            for row in switches
        )
    )
