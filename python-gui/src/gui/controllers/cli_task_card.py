"""任务卡的异步协议适配；标签由 GUI 生成，业务读写只经 CLI。"""

from PySide6.QtCore import Slot

from gui.controllers.task_card import TaskCardController


class CliTaskCardController(TaskCardController):
    def __init__(self, game_list, client, toast, parent=None, client_factory=None):
        super().__init__(game_list, None, toast, parent)
        self._client = client
        self._client_factory = client_factory
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
        """刷新失败会话时新建客户端，只重新查询当前脚本。"""
        self._generation += 1
        self._view = None
        self.taskStateChanged.emit()
        script_name = self._current["script_name"]
        if script_name:
            if not self._client.usable and self._client_factory is not None:
                previous = self._client
                previous.succeeded.disconnect(self._succeeded)
                previous.failed.disconnect(self._failed)
                self._requests.clear()
                previous.close()
                self._client = self._client_factory()
                self._client.succeeded.connect(self._succeeded)
                self._client.failed.connect(self._failed)
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
            if result is not None:
                self._toast("CLI 写操作响应无效，请刷新")
                self.refresh()
                return
            # null 也是成功；确认后仅反读，不重放写入。
            self.refresh()
        elif kind == "read":
            if not valid_script_view(result, self._current["script_name"]):
                self._view = None
                self._toast("CLI 任务卡响应无效，请刷新")
                self.taskStateChanged.emit()
                return
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


def valid_options(options) -> bool:
    """校验递归菜单的容器及标签，物理值保持原 JSON 类型。"""
    if not isinstance(options, dict) or "values" not in options:
        return False
    if not isinstance(options["values"], list):
        return False
    for choice in options["values"]:
        if (
            not isinstance(choice, dict)
            or "display_name" not in choice
            or not isinstance(choice["display_name"], str)
            or "physical_name" not in choice
        ):
            return False
        if "options" in choice and choice["options"] is not None:
            if not valid_options(choice["options"]):
                return False
    return True


def valid_script_view(view, script_name) -> bool:
    """进程响应是外部输入，显式校验身份、类型和必需的可空字段。"""
    if (
        not isinstance(view, dict)
        or not {"script", "dailies", "weeklies"} <= view.keys()
    ):
        return False
    script = view["script"]
    if (
        not isinstance(script, dict)
        or "script_name" not in script
        or script["script_name"] != script_name
        or "adapted" not in script
        or type(script["adapted"]) is not bool
    ):
        return False
    if not isinstance(view["dailies"], list) or not isinstance(view["weeklies"], list):
        return False
    for row in view["dailies"]:
        if (
            not isinstance(row, dict)
            or not {"name", "options", "enabled", "task", "sequence"} <= row.keys()
            or not isinstance(row["name"], str)
            or row["task"] is not None
            and not isinstance(row["task"], str)
            or row["enabled"] is not None
            and type(row["enabled"]) is not bool
            or not valid_options(row["options"])
        ):
            return False
    for row in view["weeklies"]:
        if (
            not isinstance(row, dict)
            or not {"name", "options", "task", "start_day"} <= row.keys()
            or not isinstance(row["name"], str)
            or row["task"] is not None
            and not isinstance(row["task"], str)
            or row["options"] is not None
            and not valid_options(row["options"])
        ):
            return False
        day = row["start_day"]
        if day is not None and (type(day) is not int or not 0 <= day <= 7):
            return False
    return True
