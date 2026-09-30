"""任务卡的异步协议适配；标签由 GUI 生成，业务读写只经 CLI。"""

from PySide6.QtCore import Slot

from gui.controllers.task_card import TaskCardController


class CliTaskCardController(TaskCardController):
    def __init__(self, game_list, client, toast, parent=None):
        super().__init__(game_list, None, toast, parent)
        self._client = client
        self._view = None
        self._generation = 0
        self._requests = {}
        client.succeeded.connect(self._succeeded)
        client.failed.connect(self._failed)

    def _request(self, method, params, kind):
        try:
            request_id = self._client.request(method, params)
        except RuntimeError as exc:
            self._toast(str(exc))
            return
        self._requests[request_id] = (
            kind,
            self._current["script_name"],
            self._generation,
        )

    def refresh(self):
        self._generation += 1
        self._view = None
        self.taskStateChanged.emit()
        script_name = self._current["script_name"]
        if script_name:
            self._request("script.view", {"script_name": script_name}, "read")

    def build_daily_cache(self):
        self._view = None

    @property
    def task_adapted(self):
        return bool(self._view and self._view["script"]["adapted"])

    def _dailies_of(self, script_name):
        if self._view is None:
            return []
        return [
            {"display_name": row["name"], "options": row["options"]}
            for row in self._view["dailies"]
        ]

    @property
    def daily_items(self):
        if self._view is None:
            return []
        return [
            {
                "name": row["name"],
                "task_label": self._daily_label(row, row["options"]["values"]),
                "can_disable": row["enabled"] is not None,
                "disabled": row["enabled"] is False,
            }
            for row in self._view["dailies"]
        ]

    @property
    def weekly_supported(self):
        return bool(self._view and self._view["weeklies"])

    @property
    def weekly_items(self):
        if self._view is None:
            return []
        return [
            {
                "name": row["name"],
                "has_task": bool(row["options"] and row["options"]["values"]),
                "task_label": (row["task"] or "选择副本") if row["options"] else "",
                "start_set": row["start_day"] is not None,
                "start_label": self._start_day_label(row["start_day"]),
            }
            for row in self._view["weeklies"]
        ]

    def weekly_task_options(self, weekly_name):
        if self._view is not None:
            for row in self._view["weeklies"]:
                if row["name"] == weekly_name:
                    return row["options"]["values"] if row["options"] else []
        return []

    def _write(self, method, **params):
        script_name = self._current["script_name"]
        if script_name:
            self._request(method, {"script_name": script_name, **params}, "write")

    @Slot(str, str, "QVariant")
    def selectDaily(self, daily_name, task_name, sequence):
        if task_name:
            self._write(
                "daily.select",
                daily_name=daily_name,
                task_name=task_name,
                sequence=sequence,
            )

    @Slot(str, bool)
    def setDailyEnabled(self, daily_name, enabled):
        self._write("daily.enable", daily_name=daily_name, enabled=enabled)

    @Slot(str, str)
    def selectWeekly(self, weekly_name, task_name):
        self._write("weekly.select", weekly_name=weekly_name, task_name=task_name)

    @Slot(str, int)
    def selectWeeklyStart(self, weekly_name, start_day):
        self._write("weekly.start", weekly_name=weekly_name, start_day=start_day)

    def _take(self, request_id):
        if request_id not in self._requests:
            return None
        kind, script_name, generation = self._requests.pop(request_id)
        if (
            script_name != self._current["script_name"]
            or generation != self._generation
        ):
            return None
        return kind

    def _succeeded(self, request_id, result):
        kind = self._take(request_id)
        if kind == "write":
            # null 也是成功；确认后仅反读，不重放写入。
            self.refresh()
        elif kind == "read":
            assert all(key in result for key in ("script", "dailies", "weeklies"))
            assert "adapted" in result["script"]
            for row in result["dailies"]:
                assert all(
                    key in row
                    for key in ("name", "options", "enabled", "task", "sequence")
                )
                assert "values" in row["options"]
            for row in result["weeklies"]:
                assert all(
                    key in row for key in ("name", "options", "task", "start_day")
                )
                assert row["options"] is None or "values" in row["options"]
            self._view = result
            self.taskStateChanged.emit()

    def _failed(self, request_id, failure):
        kind = self._take(request_id)
        if kind is None:
            return
        self._toast(failure.message)
        if kind == "write" and failure.refresh_required:
            if failure.code != "transport_failed":
                self.refresh()
            else:
                self._view = None
                self.taskStateChanged.emit()
