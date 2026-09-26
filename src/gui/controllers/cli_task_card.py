"""CLI 任务卡：属性仅读内存，异步响应按当前选择的代次应用。"""

from PySide6.QtCore import Slot

from src.gui.controllers.task_card import TaskCardController


class CliTaskCardController(TaskCardController):
    def __init__(self, game_list, app_service, toast, client, parent=None):
        super().__init__(game_list, app_service, toast, parent)
        self._client = client
        self._view = {"dailies": [], "weeklies": []}
        self._generation = 0
        self.busy = False
        self.status = "连接中"
        client.failed.connect(self._disconnected)

    @property
    def task_adapted(self):
        return bool(self._view["dailies"] or self._view["weeklies"])

    @property
    def daily_items(self):
        return [
            {
                "name": daily["daily_name"],
                "task_label": self._daily_label(
                    {
                        "enabled": daily["enabled"],
                        "task": daily["selected"]["task_name"],
                        "sequence": daily["selected"]["sequence"],
                    },
                    daily["options"]["values"],
                ),
                "can_disable": daily["enabled"] is not None,
                "disabled": daily["enabled"] is False,
            }
            for daily in self._view["dailies"]
        ]

    def daily_options(self, daily_name):
        for daily in self._view["dailies"]:
            if daily["daily_name"] == daily_name:
                return daily["options"]["values"]
        return []

    @property
    def weekly_supported(self):
        return bool(self._view["weeklies"])

    @property
    def weekly_items(self):
        return [
            {
                "name": weekly["weekly_name"],
                "has_task": bool(weekly["options"] and weekly["options"]["values"]),
                "task_label": weekly["selected"]
                or ("选择副本" if weekly["options"] else ""),
                "start_set": weekly["start_day"] is not None,
                "start_label": self._start_day_label(weekly["start_day"]),
            }
            for weekly in self._view["weeklies"]
        ]

    def weekly_task_options(self, weekly_name):
        for weekly in self._view["weeklies"]:
            if weekly["weekly_name"] == weekly_name:
                return weekly["options"]["values"] if weekly["options"] else []
        return []

    def build_daily_cache(self):
        self._generation += 1
        self._view = {"dailies": [], "weeklies": []}

    def refresh(self):
        self.build_daily_cache()
        script_name = self._current["script_name"]
        if not script_name:
            self.busy = False
            self.status = "无脚本"
            self.taskStateChanged.emit()
            return
        self._request("script.view", {"script_name": script_name})

    def _request(self, method, params):
        generation = self._generation
        self.busy = True
        self.status = "读取中" if method == "script.view" else "保存中"
        self.taskStateChanged.emit()

        def completed(result, error):
            if generation != self._generation:
                if error is not None and method != "script.view":
                    assert "message" in error
                    self._toast(f"{params['script_name']}：{error['message']}")
                return
            self.busy = False
            if error is not None:
                assert "message" in error and "code" in error
                self.status = "失败 · 请刷新"
                self._toast(error["message"])
                self._view = {"dailies": [], "weeklies": []}
                self.taskStateChanged.emit()
                # 明确的业务失败可反读部分落盘状态；断连不自动重连或重放写操作。
                if method != "script.view" and error["code"] != "transport_failed":
                    self.refresh()
                return
            assert "script" in result and "script_name" in result["script"]
            assert result["script"]["script_name"] == params["script_name"]
            assert "dailies" in result and "weeklies" in result
            for daily in result["dailies"]:
                assert {"daily_name", "options", "selected", "enabled"} <= daily.keys()
                assert "values" in daily["options"]
                assert {"task_name", "sequence"} <= daily["selected"].keys()
            for weekly in result["weeklies"]:
                assert {
                    "weekly_name",
                    "options",
                    "selected",
                    "start_day",
                } <= weekly.keys()
            self._view = result
            self.status = "已同步"
            self.taskStateChanged.emit()

        self._client.request(method, params, completed)

    def _disconnected(self, _message):
        self.build_daily_cache()
        self.busy = False
        self.status = "连接断开 · 请刷新"
        self.taskStateChanged.emit()

    def _edit(self, method, params):
        if self.busy or not self.task_adapted:
            return
        self._generation += 1
        self._request(method, {"script_name": self._current["script_name"], **params})

    @Slot(str, str, "QVariant")
    def selectDaily(self, daily_name, task_name, sequence):
        self._edit(
            "daily.select",
            {"daily_name": daily_name, "task_name": task_name, "sequence": sequence},
        )

    @Slot(str, bool)
    def setDailyEnabled(self, daily_name, enabled):
        self._edit("daily.enable", {"daily_name": daily_name, "enabled": enabled})

    @Slot(str, str)
    def selectWeekly(self, weekly_name, task_name):
        self._edit(
            "weekly.select", {"weekly_name": weekly_name, "task_name": task_name}
        )

    @Slot(str, int)
    def selectWeeklyStart(self, weekly_name, start_day):
        self._edit("weekly.start", {"weekly_name": weekly_name, "start_day": start_day})
