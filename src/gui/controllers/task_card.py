"""任务卡控制器：日常副本 / 周常周几（数据 + 选择持久化）。

独立 QObject，自管状态（_ui_state / _dungeon_*_cache）。当前游戏经构造注入的
game_list 引用读取。dungeonOptions 从缓存读取（build_dungeon_cache 时构建）。
启用控制不在此处：日常靠控制模式、周常靠周几起（均在别处实现）。
"""

from PySide6.QtCore import QObject, Signal, Slot

from src.config.dungeon_config import get_display_name, parse_dungeon_config
from src.config.set_config import (
    get_dungeon,
    get_sequence,
    get_weekly_dungeon,
    is_adapted,
    set_config,
    set_weekly_dungeon,
)
from src.service.dungeon_service import DungeonService
from src.service.weekly_service import WeeklyService

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


class TaskCardController(QObject):
    taskStateChanged = Signal()
    toastRequested = Signal(str)

    def __init__(self, game_list, service, toast, parent=None):
        super().__init__(parent)
        self._game_list = game_list
        self._service = service
        self._toast = toast
        # 周常声明只读服务：weekly_list.yml（支持哪些周常 / 是否需选副本 / 副本清单）
        self._dungeon_service = DungeonService()
        self._weekly_service = WeeklyService()
        # 任务卡状态：gui_state.json 的副本/序列/周常（按 script_name 索引）
        self._ui_state = self._service.load_ui_state()
        # 副本下拉数据缓存：dungeon_list.yml 解析较贵且运行期不变，
        # build_dungeon_cache 时一次性构建。
        self._dungeon_map_cache: dict = {}
        self._dungeon_options_cache: dict[str, list] = {}

    # ── 读接口（供 QmlBridge 委托）────────────────────────────────────
    @property
    def _current(self) -> dict:
        return self._game_list.current_game

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
        """当前游戏是否有可配置日常副本（dungeon_map 有配置才显示日常行）。"""
        return bool(self._dungeon_map_cache.get(self._current["script_name"]))

    @property
    def daily_dungeon_text(self) -> str:
        """日常副本 chip 文字（优先反读子脚本 config，无真相回退 gui_state.json）。

        子脚本 config 是日常副本的真相源（selectDungeon 已实时落盘）；
        绝区零/崩铁日常无副本适配（set_dungeon 为 no-op），只能回退 gui_state.json。
        """
        game = self._current
        script_name = game["script_name"]
        # 1) 优先反读子脚本 config（真相源）
        dungeon = get_dungeon(script_name)
        sequence = get_sequence(script_name)
        # 2) 无真相/未设置：回退 gui_state.json（覆盖 no-op 脚本）
        saved = self._ui_state.get(script_name, {})
        if dungeon is None:
            dungeon = saved.get("dungeon")
        if sequence is None:
            sequence = saved.get("sequence")
        if not dungeon:
            return "选择副本"
        dungeon_cfg = self._dungeon_map_cache.get(script_name)
        return self._dungeon_chip_text(dungeon_cfg, dungeon, sequence)

    @property
    def weekly_supported(self) -> bool:
        """当前游戏是否支持周常（决定周常行显隐）。

        唯一真相源为 weekly_list.yml：声明了该脚本周常即支持。
        """
        return bool(self._dungeon_service.get_weekly_map(self._current["script_name"]))

    @property
    def weekly_start_label(self) -> str:
        """周常起始日文字（周几起），供单脚本配置弹窗显示当前选择。"""
        game = self._current
        start_day = self._weekly_service.get_weekly_start(game["script_name"])
        return "选择周几" if start_day is None else f"{WEEKDAY_NAMES[start_day]}起"

    @property
    def weekly_items(self) -> list[dict]:
        """当前脚本支持的周常列表（供 QML 多周常布局）。

        每种周常：{name, has_dungeon, dungeon_label}。has_dungeon 由声明是否含
        dungeons 字段（且有内容）推导，不再用 needs_instance 布尔字段；
        dungeon_label 为已选副本名，需选而未选时返回「选择副本」、无需选返回空。
        声明（支持哪些周常/可选副本）来自 weekly_list.yml，已选副本来自
        gui_state.json 的 weekly_dungeons（与副本/序列同为 UI 状态）。
        """
        script_name = self._current["script_name"]
        defs = self._dungeon_service.get_weekly_map(script_name)
        if not defs:
            return []
        saved_dungeons = self._weekly_dungeons(script_name)
        items = []
        for d in defs:
            name = d["name"]
            has_dungeon = "dungeons" in d and bool(d["dungeons"])
            label = ""
            if has_dungeon:
                # 优先反读子脚本 config（真相源，如 M7A instance_names）；
                # 无真相/未设置回退 gui_state.json 的 weekly_dungeons。
                label = "选择副本"
                cfg_dungeon = get_weekly_dungeon(script_name, name)
                if cfg_dungeon:
                    label = cfg_dungeon
                elif name in saved_dungeons and saved_dungeons[name]:
                    label = saved_dungeons[name]
            items.append(
                {"name": name, "has_dungeon": has_dungeon, "dungeon_label": label}
            )
        return items

    def _weekly_dungeons(self, script_name: str) -> dict:
        """读某脚本各周常已选副本（gui_state.json 的 weekly_dungeons）。

        Args:
            script_name: 脚本唯一标识。

        Returns:
            {周常名: 已选副本名}；无记录时返回空 dict。
        """
        if script_name not in self._ui_state:
            return {}
        saved = self._ui_state[script_name]
        if "weekly_dungeons" not in saved:
            return {}
        dungeons = saved["weekly_dungeons"]
        if not isinstance(dungeons, dict):
            return {}
        return dungeons

    def weekly_dungeon_options(self, weekly_name: str) -> list[str]:
        """某周常的可选副本名列表（如历战余响的全体副本）。

        来自 weekly_list.yml 声明（该周常的 dungeons 字段）；不再依赖游戏脚本
        私有配置。未声明或无需副本返回空列表。

        Args:
            weekly_name: 周常名（如「历战余响」）。

        Returns:
            副本名列表（含「无」）；该周常未声明副本清单时返回空列表。
        """
        script_name = self._current["script_name"]
        for d in self._dungeon_service.get_weekly_map(script_name):
            if d["name"] != weekly_name:
                continue
            return list(d["dungeons"]) if "dungeons" in d else []
        return []

    @property
    def dungeon_options(self) -> list:
        """日常副本下拉数据：[{name, clear, sequences:[{label,value}]}, ...]，从缓存读取。"""
        return self._dungeon_options_cache.get(self._current["script_name"], [])

    @property
    def ui_state(self) -> dict:
        return self._ui_state

    # ── 缓存构建（运行期不变）──────────────────────────────────────────
    def build_dungeon_cache(self, games: list):
        """一次性解析 dungeon_list.yml 并构建所有脚本的副本下拉数据（运行期不变）。"""
        self._dungeon_map_cache = self._dungeon_service.get_dungeon_map()
        self._dungeon_options_cache = {
            g["script_name"]: self._build_dungeon_options(g["script_name"])
            for g in games
        }

    def refresh(self):
        """切换游戏后发信号触发 QML 重读任务卡。"""
        self.taskStateChanged.emit()

    def _dungeon_chip_text(self, dungeon_cfg, dungeon_name: str, sequence) -> str:
        """副本 chip 文字：副本名 + 已选二级序号（如「空幕 · 轨道之夜」）。

        异环等游戏的二级序号（如轨道之夜）不自包含副本名，必须连同副本名一起
        展示，否则会误把序号当成副本本身。无二级序号时仅显示副本名。
        """
        if dungeon_name is None:
            return "选择副本"
        if dungeon_cfg and sequence is not None:
            _, seq_map, _ = parse_dungeon_config(dungeon_cfg)
            if dungeon_name in seq_map:
                return f"{dungeon_name} · {get_display_name(seq_map, dungeon_name, sequence)}"
        return dungeon_name

    def _build_dungeon_options(self, script_name: str) -> list:
        """构建日常副本下拉数据（一级副本 → 二级序列）。"""
        dungeon_cfg = self._dungeon_map_cache.get(script_name)
        if not dungeon_cfg:
            return []
        options, seq_map, _ = parse_dungeon_config(dungeon_cfg)
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
    def selectDungeon(self, dungeon_name: str, sequence):
        """选择日常副本（持久化到 gui_state.json，并实时落盘子脚本 config）。"""
        script_name = self._current["script_name"]
        saved = self._ui_state.setdefault(script_name, {})
        saved["dungeon"] = dungeon_name
        saved["sequence"] = sequence
        self._service.save_ui_state(self._ui_state)
        # 实时落盘子脚本 config（与周常副本 selectWeeklyDungeon 一致）；
        # 未选择选项已移除，下拉只含真实副本，此处不再区分清空调度。
        if dungeon_name:
            set_config(script_name, dungeon_name=dungeon_name, sequence=sequence)
        self.refresh()

    @Slot(str, str)
    def selectWeeklyDungeon(self, weekly_name: str, dungeon_name: str):
        """选择某周常的副本（持久化 gui_state.json 并写脚本自身 config）。

        Args:
            weekly_name: 周常名（如「历战余响」）。
            dungeon_name: 选中的副本名（来自 weekly_dungeon_options）。
        """
        script_name = self._current["script_name"]
        # 1) 持久化到 gui_state.json 的 weekly_dungeons（与副本/序列同为 UI 状态）
        saved = self._ui_state.setdefault(script_name, {})
        saved.setdefault("weekly_dungeons", {})[weekly_name] = dungeon_name
        self._service.save_ui_state(self._ui_state)
        # 2) 写回脚本自身 config（如 M7A config.yaml 的 instance_names[weekly_name]）
        set_weekly_dungeon(script_name, weekly_name, dungeon_name)
        self.refresh()
