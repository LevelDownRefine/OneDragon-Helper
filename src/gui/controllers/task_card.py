"""任务卡控制器：日常副本 / 周常周几（数据 + 选择持久化）。

独立 QObject，自管状态（_daily_task_map_cache / _daily_task_options_cache）。当前游戏经构造注入的
game_list 引用读取。dailyTaskOptions 从缓存读取（build_daily_task_cache 时构建）。
启用控制不在此处：日常靠控制模式、周常靠周几起（均在别处实现）。
"""

from PySide6.QtCore import QObject, Signal, Slot

from src.config.daily_task_config import get_display_name, parse_daily_task_config
from src.config.set_config import (
    get_daily_task,
    get_sequence,
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
    def daily_task_text(self) -> str:
        """日常副本 chip 文字（优先反读子脚本 config，无真相回退声明的唯一选项）。

        子脚本 config 是日常副本的真相源（selectDailyTask 已实时落盘）；绝区零/崩铁
        的 set_daily_task 为 no-op（上游自身已支持到无需本工具配置），反读恒无真相，
        故回退 daily_task_list.yml 声明的首个选项——即 UI 上直接呈现为已选状态。
        """
        game = self._current
        script_name = game["script_name"]
        # 1) 优先反读子脚本 config（真相源）
        task = get_daily_task(script_name)
        sequence = get_sequence(script_name)
        # 2) 无真相：回退声明的首个选项（no-op 脚本的已选态，不再持久化）
        if task is None:
            options = self.daily_task_options
            if options:
                task = options[0]["name"]
        if not task:
            return "选择副本"
        task_cfg = self._daily_task_map_cache.get(script_name)
        return self._daily_task_chip_text(task_cfg, task, sequence)

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

    @property
    def daily_task_options(self) -> list:
        """日常副本下拉数据：[{name, clear, sequences:[{label,value}]}, ...]，从缓存读取。"""
        return self._daily_task_options_cache.get(self._current["script_name"], [])

    # ── 缓存构建（运行期不变）──────────────────────────────────────────
    def build_daily_task_cache(self, games: list):
        """一次性解析 daily_task_list.yml 并构建所有脚本的副本下拉数据（运行期不变）。"""
        self._daily_task_map_cache = self._app_service.get_daily_task_map()
        self._daily_task_options_cache = {
            g["script_name"]: self._build_daily_task_options(g["script_name"])
            for g in games
        }

    def refresh(self):
        """切换游戏后发信号触发 QML 重读任务卡。"""
        self.taskStateChanged.emit()

    def _daily_task_chip_text(self, task_cfg, task_name: str, sequence) -> str:
        """副本 chip 文字：副本名 + 已选二级序号（如「空幕 · 轨道之夜」）。

        异环等游戏的二级序号（如轨道之夜）不自包含副本名，必须连同副本名一起
        展示，否则会误把序号当成副本本身。无二级序号时仅显示副本名。
        """
        if task_name is None:
            return "选择副本"
        if task_cfg and sequence is not None:
            _, seq_map, _ = parse_daily_task_config(task_cfg)
            if task_name in seq_map:
                return f"{task_name} · {get_display_name(seq_map, task_name, sequence)}"
        return task_name

    def _build_daily_task_options(self, script_name: str) -> list:
        """构建日常副本下拉数据（一级副本 → 二级序列）。"""
        task_cfg = self._daily_task_map_cache.get(script_name)
        if not task_cfg:
            return []
        options, seq_map, _ = parse_daily_task_config(task_cfg)
        result = []
        for name in options:
            seqs = seq_map.get(name, [])
            result.append(
                {
                    "name": name,
                    "sequences": [{"label": lbl, "value": val} for lbl, val in seqs],
                }
            )
        return result

    # ── 交互 ───────────────────────────────────────────────────────────
    @Slot(str, "QVariant")
    def selectDailyTask(self, task_name: str, sequence):
        """选择日常副本（实时落盘子脚本 config）。

        绝区零/崩铁的 set_daily_task 为 no-op（上游已支持到无需本工具配置），
        其日常副本直接取 daily_task_list.yml 声明选项，不经本方法持久化。
        """
        script_name = self._current["script_name"]
        # 实时落盘子脚本 config（与周常副本 selectWeeklyTask 一致，经 service）；
        # 未选择选项已移除，下拉只含真实副本，此处不再区分清空调度。
        if task_name:
            self._app_service.set_script_daily_task(
                script_name, task_name=task_name, sequence=sequence
            )
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
