"""任务卡视图：日常副本 / 周常周几的标签、选项与缓存。

独立 QObject。数据源为 CLI ``script.view``（与 Rust 前端 ``script.view``
同一聚合视图）：日常/周常行、下拉选项与周几起一次取全，控制器只做视图→UI 行的
展示衍生。当前游戏经构造注入的 game_list 引用读取；视图按脚本缓存，
``refresh()``（写操作后）与 ``build_daily_cache()``（列表重载）失效重取。
启用控制：脚本级启用靠控制模式、日常级开关靠 setDailyEnabled（仅声明了日常
开关的脚本，如异环）、周常靠周几起（均在别处实现）。
"""

from PySide6.QtCore import QObject, Signal

from src.utils.utils_weekly import DISABLED_START_DAY

# 周常「周几以后开始执行」：值 1=周一 ~ 7=周日（对齐 get_week_num 的 0=周一 偏移 +1）；
# DISABLED_START_DAY（0）= 不启用。
WEEKDAY_NAMES = {
    1: "周一",
    2: "周二",
    3: "周三",
    4: "周四",
    5: "周五",
    6: "周六",
    7: "周日",
}

# 无脚本时的哨兵当前项：config 删空后 QML 属性仍可安全求值（空标题 / 空列表，卡收缩）。
_EMPTY_GAME = {
    "display_name": "",
    "script_name": "",
    "script_data": {},
    "char": "",
    "color": "",
}

# 空视图：无脚本（哨兵）或脚本已被移除时收缩卡片（与旧直读口径一致：空列表）。
_EMPTY_VIEW = {"script": {"adapted": False}, "dailies": [], "weeklies": []}


class TaskCardController(QObject):
    taskStateChanged = Signal()
    toastRequested = Signal(str)

    def __init__(self, game_list, toast, parent=None):
        super().__init__(parent)
        self._game_list = game_list
        self._toast = toast
        # 聚合视图缓存：QML 的行属性与下拉共用一份；refresh / build_daily_cache 失效。
        self._view: dict | None = None
        self._view_script = ""

    # ── 视图 ─────────────────────────────────────────────────────────
    def _fetch_view(self, script_name: str) -> dict | None:
        """视图尚未到达时返回空；CLI 子类负责异步请求。"""
        return None

    def _card_view(self) -> dict:
        """当前脚本的任务卡视图；同一脚本在两次失效之间只取一次。

        取数经 ``_fetch_view``（同步返回视图）；异步模式取数为 None 时缓存空
        视图（响应到达后由子类直接回填 ``_view`` 并发信号）。脚本为空
        （config 删空哨兵）或已被移除（列表重载随后跟上）时同样收缩为空视图。

        Returns:
            ``script_view`` 的聚合结果（dailies / weeklies）。
        """
        script_name = self._current["script_name"]
        if self._view is not None and self._view_script == script_name:
            return self._view
        view = self._fetch_view(script_name) if script_name else None
        if view is None:
            view = _EMPTY_VIEW
        assert all(key in view for key in ("script", "dailies", "weeklies"))
        assert "adapted" in view["script"]
        self._view = view
        self._view_script = script_name
        return view

    def _invalidate_view(self) -> None:
        self._view = None
        self._view_script = ""

    # ── 读接口（供 QmlBridge 委托）────────────────────────────────────
    @property
    def _current(self) -> dict:
        """当前脚本（config 删空时回退哨兵空项，QML 属性安全求值）。"""
        game = self._game_list.current_game
        return game if game is not None else _EMPTY_GAME

    @property
    def task_title(self) -> str:
        """当前游戏显示名（任务卡标题）。"""
        return self._current["display_name"]

    @property
    def task_adapted(self) -> bool:
        """当前游戏是否已注册副本适配（视图 script.adapted，决定行显隐）。"""
        return bool(self._card_view()["script"]["adapted"])

    @property
    def daily_items(self) -> list[dict]:
        """当前脚本的日常列表（供 QML 多日常布局）。

        视图行已并入反读真相（task/sequence/enabled）与声明菜单（options），
        此处逐行生成 {name, task_label, can_disable, disabled}：task_label 为 chip
        文字，优先用反读到的副本（+二级选项），无真相回退该日常声明的首个选项
        （绝区零/崩铁的 set_daily_task 为 no-op，反读恒无真相，故回退声明项——
        即 UI 上直接呈现为已选状态）；该日常被停用时显示「不启用」。
        can_disable 由脚本是否声明日常开关（enabled 非 None）推导，
        disabled 为当前是否已停用。
        """
        items = []
        for daily in self._card_view()["dailies"]:
            assert all(key in daily for key in ("name", "task", "sequence", "enabled"))
            assert "options" in daily and "values" in daily["options"]
            items.append(
                {
                    "name": daily["name"],
                    "task_label": self._daily_label(daily, daily["options"]["values"]),
                    "can_disable": daily["enabled"] is not None,
                    "disabled": daily["enabled"] is False,
                }
            )
        return items

    def daily_options(self, daily_name: str) -> list:
        """某日常的副本下拉数据（QML 按行调用）。

        Args:
            daily_name: 日常展示名。

        Returns:
            该日常一级选项的物化声明列表（display_name/physical_name/子选项组）；
            未知日常返回空列表。
        """
        for daily in self._card_view()["dailies"]:
            if daily["name"] != daily_name:
                continue
            assert "options" in daily and "values" in daily["options"]
            return daily["options"]["values"]
        return []

    @property
    def weekly_supported(self) -> bool:
        """当前游戏是否支持周常（决定周常行显隐）。

        唯一真相源为 weekly_task_list.yml：声明了该脚本周常即支持。
        """
        return bool(self._card_view()["weeklies"])

    @staticmethod
    def _start_day_label(start_day: int | None) -> str:
        """「周几起」chip 文字；未设置 →「选择周几」，不启用 →「不启用」。

        Args:
            start_day: 周几起（1~7）；``DISABLED_START_DAY`` 表示不启用；None 表示未设置。

        Returns:
            chip / 标签文字。

        Raises:
            AssertionError: start_day 既非不启用也不在 1~7（weekly.yml 被手工改坏）。
        """
        if start_day is None:
            return "选择周几"
        if start_day == DISABLED_START_DAY:
            return "不启用"
        assert start_day in WEEKDAY_NAMES, (
            f"[task_card] 非法周几起: {start_day!r}（weekly.yml 应为 0（不启用）或 1~7）"
        )
        return f"{WEEKDAY_NAMES[start_day]}起"

    @property
    def weekly_start_options(self) -> list[dict]:
        """「周几起」下拉的候选（不启用 + 周一~周日），供 QML 逐项渲染。

        Returns:
            [{label, value}]，value 即写进 weekly.yml 的起始日。
        """
        return [{"label": "不启用", "value": DISABLED_START_DAY}] + [
            {"label": f"{name}起", "value": day} for day, name in WEEKDAY_NAMES.items()
        ]

    @property
    def weekly_items(self) -> list[dict]:
        """当前脚本支持的周常列表（供 QML 多周常布局）。

        每条周常：{name, has_task, task_label, start_set, start_label}。has_task 由
        声明是否含选项（且有内容）推导；task_label 为已选副本名，需选而未选时返回
        「选择副本」、无需选返回空。start_label 为该条周常的「周几起」文字（未设 →
        「选择周几」），start_set 供 QML 区分未设置时的文字配色。声明与已选副本、
        周几起均来自聚合视图——周常侧无 no-op 脚本，故不设回退。
        """
        items = []
        for weekly in self._card_view()["weeklies"]:
            assert all(
                key in weekly for key in ("name", "options", "task", "start_day")
            )
            has_task = weekly["options"] is not None and bool(
                weekly["options"]["values"]
            )
            label = ""
            if has_task:
                # 已选副本反读自子脚本 config（真相源，如 M7A instance_names）
                label = weekly["task"] or "选择副本"
            start_day = weekly["start_day"]
            items.append(
                {
                    "name": weekly["name"],
                    "has_task": has_task,
                    "task_label": label,
                    "start_set": start_day is not None,
                    "start_label": self._start_day_label(start_day),
                }
            )
        return items

    def weekly_task_options(self, weekly_name: str) -> list:
        """某周常的可选副本清单（物化声明：display_name/physical_name）。

        来自 weekly_task_list.yml 声明的物化结果；未声明或无需副本返回空列表。

        Args:
            weekly_name: 周常名（如「历战余响」）。

        Returns:
            一级选项的物化声明列表（含「无」）；该周常未声明副本清单时返回空列表。
        """
        for weekly in self._card_view()["weeklies"]:
            if weekly["name"] != weekly_name:
                continue
            return weekly["options"]["values"] if weekly["options"] else []
        return []

    # ── 视图缓存失效──────────────────────────────────────────────────
    def build_daily_cache(self):
        """列表重载后失效视图缓存（菜单词汇与本地资源按新列表重取）。"""
        self._invalidate_view()

    def refresh(self):
        """写操作后失效缓存并发信号，触发 QML 以新视图重读任务卡。"""
        self._invalidate_view()
        self.taskStateChanged.emit()

    def _daily_label(self, record: dict, values: list) -> str:
        """某日常的 chip 文字：停用 →「不启用」，否则反读副本（+二级选项）。

        反读无真相（如绝区零/崩铁的 no-op 日常）时回退声明的首个选项，
        即 UI 上呈现为已选状态（不再持久化）。

        Args:
            record: 该日常的反读记录（{name, task, sequence, enabled}）。
            values: 该日常一级选项的物化声明（用于二级物理值翻展示名）。

        Returns:
            chip 文字。
        """
        if record["enabled"] is False:
            return "不启用"
        task = record["task"]
        if task is None and values:
            task = values[0]["display_name"]
        if not task:
            return "选择副本"
        return self._daily_chip_text(values, task, record["sequence"])

    def _daily_chip_text(self, values: list, task_name: str, sequence) -> str:
        """副本 chip 文字：副本名 + 已选二级选项（如「空幕 · 轨道之夜」）。

        异环等游戏的二级选项（如轨道之夜）不自包含副本名，必须连同副本名一起
        展示，否则会误把选项当成副本本身。无二级选项时仅显示副本名。
        """
        if task_name is None:
            return "选择副本"
        if sequence is not None:
            for option in values:
                if option["display_name"] != task_name or "options" not in option:
                    continue
                for child in option["options"]["values"]:
                    if child["physical_name"] == sequence:
                        return f"{task_name} · {child['display_name']}"
        return task_name
