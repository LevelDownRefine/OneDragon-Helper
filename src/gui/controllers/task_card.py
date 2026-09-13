"""任务卡控制器：日常副本 / 周常周几（数据 + 选择持久化）。

独立 QObject，自管状态（_daily_task_map_cache / _daily_task_options_cache）。当前游戏经构造注入的
game_list 引用读取。日常菜单的选项从缓存读取（build_daily_task_cache 时构建）；日常行的 chip 文案
每次求值时经 get_daily_readback 反读一次（一次覆盖该脚本全部日常）。
启用控制：脚本级启用靠控制模式、日常级开关靠 setDailyEnabled（仅声明了日常开关的脚本，如异环）、
周常靠周几起（均在别处实现）。
"""

from PySide6.QtCore import QObject, Signal, Slot

from src.config.daily_task_config import parse_daily_task_config
from src.config.set_config import (
    get_daily_readback,
    get_weekly_task,
    is_adapted,
)

# 周常「周几以后开始执行」：值 1=周一 ~ 7=周日（对齐 get_week_num 的 0=周一 偏移 +1）
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
        # build_daily_task_cache 时一次性构建。
        self._daily_task_map_cache: dict = {}
        self._daily_task_options_cache: dict[str, list] = {}

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
    def daily_supported(self) -> bool:
        """当前游戏是否有可配置日常副本（daily_task_map 有配置才显示日常行）。"""
        return bool(self._daily_task_map_cache.get(self._current["script_name"]))

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
            daily["name"]: daily["options"]
            for daily in self._daily_task_options_cache.get(script_name, [])
        }
        items = []
        for record in get_daily_readback(script_name):
            name = record["name"]
            options = options_by_daily.get(name, [])
            items.append(
                {
                    "name": name,
                    "task_label": self._daily_task_label(record, options),
                    "can_disable": record["enabled"] is not None,
                    "disabled": record["enabled"] is False,
                }
            )
        return items

    def daily_task_options(self, daily_name: str) -> list:
        """某日常的副本下拉数据（QML 按行调用）。

        Args:
            daily_name: 日常展示名。

        Returns:
            该日常的 [{name, sequences:[{label,value}]}, ...]；未知日常返回空列表。
        """
        script_name = self._current["script_name"]
        for daily in self._daily_task_options_cache.get(script_name, []):
            if daily["name"] == daily_name:
                return daily["options"]
        return []

    @property
    def weekly_supported(self) -> bool:
        """当前游戏是否支持周常（决定周常行显隐）。

        唯一真相源为 weekly_task_list.yml：声明了该脚本周常即支持。
        """
        return bool(self._app_service.get_weekly_map(self._current["script_name"]))

    @property
    def weekly_start_label(self) -> str:
        """周常起始日文字（周几起），供单脚本配置弹窗显示当前选择。"""
        game = self._current
        start_day = self._app_service.get_weekly_start(game["script_name"])
        return "选择周几" if start_day is None else f"{WEEKDAY_NAMES[start_day]}起"

    @property
    def weekly_items(self) -> list[dict]:
        """当前脚本支持的周常列表（供 QML 多周常布局）。

        每种周常：{name, has_task, task_label}。has_task 由声明是否含
        tasks 字段（且有内容）推导，不再用 needs_instance 布尔字段；
        task_label 为已选副本名，需选而未选时返回「选择副本」、无需选返回空。
        声明（支持哪些周常/可选副本）来自 weekly_task_list.yml；已选副本反读子脚本
        config（如 M7A instance_names）——周常侧无 no-op 脚本，故不设回退。
        """
        script_name = self._current["script_name"]
        defs = self._app_service.get_weekly_map(script_name)
        if not defs:
            return []
        items = []
        for d in defs:
            name = d["name"]
            has_task = "tasks" in d and bool(d["tasks"])
            label = ""
            if has_task:
                # 反读子脚本 config（真相源，如 M7A instance_names）
                label = "选择副本"
                cfg_task = get_weekly_task(script_name, name)
                if cfg_task:
                    label = cfg_task
            items.append({"name": name, "has_task": has_task, "task_label": label})
        return items

    def weekly_task_options(self, weekly_name: str) -> list[str]:
        """某周常的可选副本名列表（如历战余响的全体副本）。

        来自 weekly_task_list.yml 声明（该周常的 tasks 字段）；不再依赖游戏脚本
        私有配置。未声明或无需副本返回空列表。

        Args:
            weekly_name: 周常名（如「历战余响」）。

        Returns:
            副本名列表（含「无」）；该周常未声明副本清单时返回空列表。
        """
        script_name = self._current["script_name"]
        for d in self._app_service.get_weekly_map(script_name):
            if d["name"] != weekly_name:
                continue
            return list(d["tasks"]) if "tasks" in d else []
        return []

    # ── 缓存构建（运行期不变）──────────────────────────────────────────
    def build_daily_task_cache(self, games: list):
        """一次性解析 daily_task_list.yml 并构建各脚本的日常菜单（运行期不变）。"""
        self._daily_task_map_cache = self._app_service.get_daily_task_map()
        self._daily_task_options_cache = {
            g["script_name"]: self._build_daily_options(g["script_name"]) for g in games
        }

    def refresh(self):
        """切换游戏后发信号触发 QML 重读任务卡。"""
        self.taskStateChanged.emit()

    def _daily_task_label(self, record: dict, options: list) -> str:
        """某日常的 chip 文字：停用 →「不启用」，否则反读副本（+二级选项）。

        反读无真相（如绝区零/崩铁的 no-op 日常）时回退该日常声明的首个选项，
        即 UI 上呈现为已选状态（不再持久化）。

        Args:
            record: 该日常的反读记录（{name, task, sequence, enabled}）。
            options: 该日常的下拉数据（用于把二级值翻成展示名）。

        Returns:
            chip 文字。
        """
        if record["enabled"] is False:
            return "不启用"
        task = record["task"]
        if task is None and options:
            task = options[0]["name"]
        if not task:
            return "选择副本"
        return self._daily_task_chip_text(options, task, record["sequence"])

    def _daily_task_chip_text(self, options: list, task_name: str, sequence) -> str:
        """副本 chip 文字：副本名 + 已选二级选项（如「空幕 · 轨道之夜」）。

        异环等游戏的二级选项（如轨道之夜）不自包含副本名，必须连同副本名一起
        展示，否则会误把选项当成副本本身。无二级选项时仅显示副本名。
        """
        if task_name is None:
            return "选择副本"
        if sequence is not None:
            for option in options:
                if option["name"] != task_name:
                    continue
                for seq in option["sequences"]:
                    if seq["value"] == sequence:
                        return f"{task_name} · {seq['label']}"
        return task_name

    def _build_daily_options(self, script_name: str) -> list:
        """构建某脚本各日常的下拉数据：[{name, options:[{name, sequences}]}, ...]。"""
        if script_name not in self._daily_task_map_cache:
            return []
        return [
            {"name": daily["name"], "options": self._build_daily_task_options(daily)}
            for daily in self._daily_task_map_cache[script_name]["dailies"]
        ]

    def _build_daily_task_options(self, daily: dict) -> list:
        """构建单个日常的副本下拉数据（一级副本 → 二级选项）。"""
        options, seq_map, _ = parse_daily_task_config(daily)
        return [
            {
                "name": name,
                "sequences": [
                    {"label": lbl, "value": val} for lbl, val in seq_map.get(name, [])
                ],
            }
            for name in options
        ]

    # ── 交互 ───────────────────────────────────────────────────────────
    @Slot(str, str, "QVariant")
    def selectDailyTask(self, daily_name: str, task_name: str, sequence):
        """选择某日常的副本（实时落盘子脚本 config，并启用该日常）。

        绝区零/崩铁的 set_daily_task 为 no-op（上游已支持到无需本工具配置），
        其日常副本直接取 daily_task_list.yml 声明选项，不经本方法持久化。

        Args:
            daily_name: 日常展示名（该行所属日常）。
            task_name: 选中的副本名（来自 daily_task_options）。
            sequence: 选中的二级选项值；该副本无二级选项时为 None。
        """
        script_name = self._current["script_name"]
        # 实时落盘子脚本 config（与周常副本 selectWeeklyTask 一致，经 service）；
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
    def selectWeeklyTask(self, weekly_name: str, task_name: str):
        """选择某周常的副本（写回脚本自身 config）。

        Args:
            weekly_name: 周常名（如「历战余响」）。
            task_name: 选中的副本名（来自 weekly_task_options）。
        """
        script_name = self._current["script_name"]
        # 写回脚本自身 config（如 M7A config.yaml 的 instance_names[weekly_name]），经 service
        self._app_service.set_script_weekly_task(script_name, weekly_name, task_name)
        self.refresh()
