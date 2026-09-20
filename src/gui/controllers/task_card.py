"""任务卡控制器：日常副本 / 周常周几（数据 + 选择持久化）。

独立 QObject，自管状态（_daily_map_cache）。当前游戏经构造注入的
game_list 引用读取。日常菜单的选项从缓存读取（build_daily_cache 时构建）；日常行的 chip 文案
每次求值时经 get_daily_readback 反读一次（一次覆盖该脚本全部日常）。
启用控制：脚本级启用靠控制模式、日常级开关靠 setDailyEnabled（仅声明了日常开关的脚本，如异环）、
周常靠周几起（均在别处实现）。
"""

import logging

from PySide6.QtCore import QObject, Signal, Slot
from ruamel.yaml.error import YAMLError

from src.config.set_config import (
    get_daily_readback,
    is_adapted,
)
from src.config.weekly import get_weekly_task
from src.utils.utils_weekly import DISABLED_START_DAY

logger = logging.getLogger(__name__)

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


class TaskCardController(QObject):
    taskStateChanged = Signal()
    toastRequested = Signal(str)

    def __init__(self, game_list, app_service, toast, parent=None):
        super().__init__(parent)
        self._game_list = game_list
        self._app_service = app_service
        self._toast = toast
        # 副本下拉数据缓存：daily_task_list.yml 解析较贵且运行期不变，
        # build_daily_cache 时一次性构建。
        self._daily_map_cache: dict = {}

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
        """当前游戏是否已注册副本适配（决定日常/周常行显隐）。"""
        return is_adapted(self._current["script_name"])

    @property
    def daily_items(self) -> list[dict]:
        """当前脚本的日常列表（供 QML 多日常布局）。

        一次反读拿到该脚本全部日常的已选项与开关（get_daily_readback），逐行生成
        {name, task_label, can_disable, disabled}：task_label 为 chip 文字，优先用反读到的
        副本（+二级选项），无真相回退该日常声明的首个选项（绝区零/崩铁的 set_daily_task
        为 no-op，反读恒无真相，故回退声明项——即 UI 上直接呈现为已选状态）；该日常被停用时
        显示「不启用」。can_disable 由脚本是否声明日常开关（enabled 非 None）推导，
        disabled 为当前是否已停用。
        """
        script_name = self._current["script_name"]
        options_by_daily = {
            daily["display_name"]: daily["options"]["values"]
            for daily in self._dailies_of(script_name)
        }
        items = []
        for record in get_daily_readback(script_name):
            name = record["name"]
            options = options_by_daily.get(name, [])
            items.append(
                {
                    "name": name,
                    "task_label": self._daily_label(record, options),
                    "can_disable": record["enabled"] is not None,
                    "disabled": record["enabled"] is False,
                }
            )
        return items

    def _dailies_of(self, script_name: str) -> list:
        """某脚本各日常的物化声明（词汇与声明一致）；无数据返回空列表。"""
        return self._daily_map_cache.get(script_name, {}).get("dailies", [])

    def daily_options(self, daily_name: str) -> list:
        """某日常的副本下拉数据（QML 按行调用）。

        Args:
            daily_name: 日常展示名。

        Returns:
            该日常一级选项的物化声明列表（display_name/physical_name/子选项组）；
            未知日常返回空列表。
        """
        script_name = self._current["script_name"]
        for daily in self._dailies_of(script_name):
            if daily["display_name"] == daily_name:
                return daily["options"]["values"]
        return []

    @property
    def weekly_supported(self) -> bool:
        """当前游戏是否支持周常（决定周常行显隐）。

        唯一真相源为 weekly_task_list.yml：声明了该脚本周常即支持。
        """
        return bool(self._app_service.get_weekly_map(self._current["script_name"]))

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

        每条周常：{name, has_task, task_label, start_set, start_label}。has_task 由物化声明
        是否含 options（且有内容）推导；task_label 为已选副本名，需选而未选时返回
        「选择副本」、无需选返回空。start_label 为该条周常的「周几起」文字（未设 →
        「选择周几」），start_set 供 QML 区分未设置时的文字配色。
        声明（支持哪些周常/可选副本）来自 weekly_task_list.yml；已选副本反读子脚本
        config（如 M7A instance_names）、周几起反读 ``weekly.yml``——周常侧无 no-op
        脚本，故不设回退。
        """
        script_name = self._current["script_name"]
        defs = self._app_service.get_weekly_map(script_name)
        if not defs:
            return []
        items = []
        for d in defs:
            name = d["display_name"]
            has_task = "options" in d and bool(d["options"]["values"])
            label = ""
            if has_task:
                # 反读子脚本 config（真相源，如 M7A instance_names）
                label = "选择副本"
                cfg_task = get_weekly_task(script_name, name)
                if cfg_task:
                    label = cfg_task
            start_day = self._app_service.get_weekly_start_for(script_name, name)
            items.append(
                {
                    "name": name,
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
        script_name = self._current["script_name"]
        for d in self._app_service.get_weekly_map(script_name):
            if d["display_name"] != weekly_name:
                continue
            return d["options"]["values"] if "options" in d else []
        return []

    # ── 缓存构建（运行期不变）──────────────────────────────────────────
    def build_daily_cache(self, games: list):
        """一次性解析 daily_task_list.yml 并构建各脚本的日常菜单（运行期不变）。"""
        self._daily_map_cache = self._app_service.get_daily_map()

    def refresh(self):
        """切换游戏后发信号触发 QML 重读任务卡。"""
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

    # ── 交互 ───────────────────────────────────────────────────────────
    @Slot(str, str, "QVariant")
    def selectDaily(self, daily_name: str, task_name: str, sequence):
        """选择某日常的副本（实时落盘子脚本 config，并启用该日常）。

        绝区零/崩铁的 set_daily_task 为 no-op（上游已支持到无需本工具配置），
        其日常副本直接取 daily_task_list.yml 声明选项，不经本方法持久化。

        Args:
            daily_name: 日常展示名（该行所属日常）。
            task_name: 选中的副本名（来自 daily_options）。
            sequence: 选中的二级选项值；该副本无二级选项时为 None。
        """
        script_name = self._current["script_name"]
        # 实时落盘子脚本 config（与周常副本 selectWeekly 一致，经 service）；
        # 未选择选项已移除，下拉只含真实副本，此处不再区分清空调度。
        if task_name:
            self._app_service.set_script_daily_task(
                script_name,
                task_name=task_name,
                sequence=sequence,
                daily_display_name=daily_name,
            )
        self.refresh()

    @Slot(str, bool)
    def setDailyEnabled(self, daily_name: str, enabled: bool):
        """启用/停用某日常（写子脚本 config 的日常开关，不动副本选择）。

        Args:
            daily_name: 日常展示名。
            enabled: 目标启用状态。
        """
        script_name = self._current["script_name"]
        self._app_service.set_script_daily_enabled(script_name, daily_name, enabled)
        self.refresh()

    @Slot(str, str)
    def selectWeekly(self, weekly_name: str, task_name: str):
        """选择某周常的副本（写回脚本自身 config）。

        Args:
            weekly_name: 周常名（如「历战余响」）。
            task_name: 选中的副本名（来自 weekly_task_options）。
        """
        script_name = self._current["script_name"]
        # 写回脚本自身 config（如 M7A config.yaml 的 instance_names[weekly_name]），经 service
        self._app_service.set_script_weekly_task(script_name, weekly_name, task_name)
        self.refresh()

    @Slot(str, int)
    def selectWeeklyStart(self, weekly_name: str, start_day: int):
        """选择某条周常的起始日（周几起）。

        意图写 weekly.yml（先），再同步该条的游戏侧字段（后）。后者要求游戏原生
        config 可用，其缺失/损坏/不可写属可预期状态：意图已落盘，界面下次刷新即按
        新值显示。故此处不让异常抛回 QML——抛回会跳过 onClicked 里后续的关下拉，
        且界面静默（错误只进日志）。

        Args:
            weekly_name: 周常名（如「历战余响」）。
            start_day: 周几起（0=不启用，1=周一 ~ 7=周日）。
        """
        script_name = self._current["script_name"]
        try:
            self._app_service.set_weekly_start_for(script_name, weekly_name, start_day)
        except (AssertionError, OSError, ValueError, YAMLError) as exc:
            logger.warning("周几起未同步到游戏配置：%s: %s", type(exc).__name__, exc)
            self._toast(f"{weekly_name} 已记录，但未能写入游戏配置：{exc}")
        finally:
            self.refresh()
