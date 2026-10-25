"""任务卡的异步协议适配；标签由 GUI 生成，业务读写只经 CLI。

复用 :class:`TaskCardController` 的视图→行展示逻辑（两前端同吃 ``script.view``
聚合视图），仅覆写取数方式：视图经 CLI 异步请求取得，响应校验后回填缓存。
"""

from PySide6.QtCore import Slot

from gui.controllers.task_card import TaskCardController


class CliTaskCardController(TaskCardController):
    def __init__(self, game_list, client, toast, parent=None, client_factory=None):
        super().__init__(game_list, None, toast, parent)
        self._client = client
        self._client_factory = client_factory
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

    def _fetch_view(self, script_name: str) -> dict | None:
        """异步模式：发出 script.view 请求后返回 None（空视图先缓存，防重复请求）。

        供 QML 求值触发的惰性取数：当前代已有待响应的读请求时不重复发送。
        响应在 ``_succeeded`` 校验后回填 ``_view`` 并发信号，QML 重读拿到真数据。
        """
        if any(
            kind == "read" and generation == self._generation
            for kind, _n, generation in self._requests.values()
        ):
            return None
        self._request("script.view", {"script_name": script_name}, "read")
        return None

    def refresh(self):
        """刷新失败会话时新建客户端，只重新查询当前脚本（每代恒发一次读请求）。"""
        self._generation += 1
        if not self._client.usable and self._client_factory is not None:
            previous = self._client
            previous.succeeded.disconnect(self._succeeded)
            previous.failed.disconnect(self._failed)
            self._requests.clear()
            previous.close()
            self._client = self._client_factory()
            self._client.succeeded.connect(self._succeeded)
            self._client.failed.connect(self._failed)
        self._invalidate_view()
        self.taskStateChanged.emit()
        script_name = self._current["script_name"]
        if script_name:
            self._request("script.view", {"script_name": script_name}, "read")

    @property
    def task_adapted(self) -> bool:
        """CLI 模式下适配状态来自视图（script.adapted），无本地注册表可查。"""
        if not self._view or "script" not in self._view:
            return False  # 尚未取到视图（含空视图缓存）
        return bool(self._view["script"]["adapted"])

    def _write(self, method, **params):
        script_name = self._current["script_name"]
        if script_name:
            self._request(method, {"script_name": script_name, **params}, "write")

    @Slot(str, str, "QVariant")
    def selectDaily(self, daily_name: str, task_name: str, sequence):
        if task_name:
            self._write(
                "daily.select",
                daily_name=daily_name,
                task_name=task_name,
                sequence=sequence,
            )

    @Slot(str, bool)
    def setDailyEnabled(self, daily_name: str, enabled: bool):
        self._write("daily.enable", daily_name=daily_name, enabled=enabled)

    @Slot(str, str)
    def selectWeekly(self, weekly_name: str, task_name: str):
        self._write("weekly.select", weekly_name=weekly_name, task_name=task_name)

    @Slot(str, int)
    def selectWeeklyStart(self, weekly_name: str, start_day: int):
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
            script_name = self._current["script_name"]
            if not valid_script_view(result, script_name):
                self._invalidate_view()
                self._toast("CLI 任务卡响应无效，请刷新")
                self.taskStateChanged.emit()
                return
            self._view = result
            self._view_script = script_name
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
                self._invalidate_view()
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
