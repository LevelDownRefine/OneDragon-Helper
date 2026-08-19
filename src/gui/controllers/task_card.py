"""任务卡控制器：日常副本 / 周常周几（数据 + 选择持久化）。

独立 QObject，自管状态（_ui_state / _dungeon_*_cache / _weekly_toggle_state /
_master_on）。当前游戏经构造注入的 game_list 引用读取。dungeonOptions 从缓存读取
（build_dungeon_cache 时构建）。
"""

from PySide6.QtCore import QObject, Signal, Slot

from src.config.dungeon_config import get_display_name, parse_dungeon_config
from src.config.set_config import is_adapted
from src.config.set_config import supports_weekly as _supports_weekly
from src.utils_weekly import is_weekly_start_reached

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
        # 任务卡状态：gui_state.json 的副本/序列/周常（按 script_name 索引）
        self._ui_state = self._service.load_ui_state()
        # 副本下拉数据缓存：dungeon_list.yml 解析较贵且运行期不变，
        # build_dungeon_cache 时一次性构建。
        self._dungeon_map_cache: dict = {}
        self._dungeon_options_cache: dict[str, list] = {}
        # 周常开关 UI 态（纯内存，不持久化）；总开关为全局 UI 态（驱动日常行开关）
        self._weekly_toggle_state: dict[str, bool] = {}
        self._master_on = True

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
        """日常副本 chip 文字（持久化于 gui_state.json）。"""
        game = self._current
        saved = self._ui_state.get(game["script_name"], {})
        if not saved.get("dungeon"):
            return "选择副本"
        dungeon_cfg = self._dungeon_map_cache.get(game["script_name"])
        return self._dungeon_chip_text(
            dungeon_cfg, saved.get("dungeon"), saved.get("sequence")
        )

    @property
    def weekly_supported(self) -> bool:
        """当前游戏是否支持周常（决定周常行可选性 / 整行样式）。"""
        return _supports_weekly(self._current["script_name"])

    @property
    def weekly_start_label(self) -> str:
        """周常 chip 文字（周几起 / 选择周几）。"""
        game = self._current
        saved = self._ui_state.get(game["script_name"], {})
        start_day = saved.get("weekly_start")
        return "选择周几" if start_day is None else f"{WEEKDAY_NAMES[start_day]}起"

    @property
    def master_on(self) -> bool:
        """总开关状态（全局 UI 态；驱动日常行开关）。"""
        return self._master_on

    @property
    def daily_on(self) -> bool:
        """日常行开关（镜像总开关，由 toggle_master 驱动）。"""
        return self._master_on

    @property
    def weekly_on(self) -> bool:
        """周常行开关（内存态，由 toggle_master / select_weekly 置位）。"""
        return self._weekly_toggle_state.get(self._current["script_name"], False)

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
        self._dungeon_map_cache = self._service.dungeon_map()
        self._dungeon_options_cache = {
            g["script_name"]: self._build_dungeon_options(g["script_name"])
            for g in games
        }

    def refresh(self):
        """切换游戏后发信号触发 QML 重读任务卡。"""
        self.taskStateChanged.emit()

    def _dungeon_chip_text(self, dungeon_cfg, dungeon_name: str, sequence) -> str:
        """副本 chip 文字：有二级序列且选了二级 → 二级展示名；否则副本名本身。"""
        if dungeon_name is None:
            return "选择副本"
        if dungeon_cfg:
            _, seq_map, _ = parse_dungeon_config(dungeon_cfg)
            if sequence is not None and dungeon_name in seq_map:
                return get_display_name(seq_map, dungeon_name, sequence)
        return dungeon_name

    def _build_dungeon_options(self, script_name: str) -> list:
        """构建日常副本下拉数据（一级副本 → 二级序列）。"""
        dungeon_cfg = self._dungeon_map_cache.get(script_name)
        if not dungeon_cfg:
            return []
        options, seq_map, _ = parse_dungeon_config(dungeon_cfg)
        result = []
        for name in options:
            if name == "未选择":
                result.append({"name": "未选择", "clear": True, "sequences": []})
            else:
                seqs = seq_map.get(name, [])
                result.append(
                    {
                        "name": name,
                        "clear": False,
                        "sequences": [
                            {"label": lbl, "value": val} for lbl, val in seqs
                        ],
                    }
                )
        return result

    def init_weekly_toggle_states(self) -> dict:
        """初始化各脚本周常开关（纯内存 UI 态，不持久化）。

        已设置「周几起」且今天 >= 起始日 → True，否则 False。
        """
        states: dict[str, bool] = {}
        for game in self._game_list.games:
            script_name = game["script_name"]
            if not _supports_weekly(script_name):
                continue
            saved = self._ui_state.get(script_name)
            weekly_start = saved.get("weekly_start") if saved else None
            states[script_name] = weekly_start is not None and is_weekly_start_reached(
                weekly_start
            )
        self._weekly_toggle_state = states
        return states

    # ── 交互 ───────────────────────────────────────────────────────────
    @Slot(bool)
    def toggleMaster(self, on: bool):
        """总开关：一键同步日常/周本（支持周常时周常开关一并置位）。"""
        self._master_on = on
        script_name = self._current["script_name"]
        if _supports_weekly(script_name):
            self._weekly_toggle_state[script_name] = on
        self.taskStateChanged.emit()

    @Slot(bool)
    def toggleWeekly(self, on: bool):
        """周常开关（内存态，不持久化；与日常开关模型一致）。"""
        script_name = self._current["script_name"]
        self._weekly_toggle_state[script_name] = on
        self.taskStateChanged.emit()

    @Slot(str, "QVariant")
    def selectDungeon(self, dungeon_name: str, sequence):
        """选择日常副本（持久化到 gui_state.json 的 dungeon/sequence）。"""
        script_name = self._current["script_name"]
        saved = self._ui_state.setdefault(script_name, {})
        if not dungeon_name or dungeon_name == "未选择":
            saved.pop("dungeon", None)
            saved.pop("sequence", None)
        else:
            saved["dungeon"] = dungeon_name
            saved["sequence"] = sequence
        self._service.save_ui_state(self._ui_state)
        self.refresh()

    @Slot(int)
    def selectWeekly(self, start_day: int):
        """选择周常起始日（持久化 weekly_start；周常开关按「今天>=起始日」置位）。"""
        assert start_day in WEEKDAY_NAMES, f"[bridge] 非法周几: {start_day}"
        script_name = self._current["script_name"]
        saved = self._ui_state.setdefault(script_name, {})
        saved["weekly_start"] = start_day
        enabled = is_weekly_start_reached(start_day)
        self._weekly_toggle_state[script_name] = enabled
        self._service.save_ui_state(self._ui_state)
        self.refresh()
