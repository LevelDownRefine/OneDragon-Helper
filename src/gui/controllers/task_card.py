"""任务卡控制器：日常副本 / 周常周几（数据 + 选择持久化）。

共享状态（_games / _ui_state / _dungeon_*_cache / _weekly_toggle_state /
_master_on）由 BridgeBase 持有。dungeonOptions 从缓存读取（_reload_games 时
构建），避免每次访问重新读盘解析。
"""

from PySide6.QtCore import Property, Signal, Slot

from src.config.dungeon_config import get_display_name, parse_dungeon_config
from src.config.set_config import is_adapted
from src.config.set_config import supports_weekly as _supports_weekly
from src.gui.controllers.game_list import GameListController
from src.gui.theme import WEEKDAY_NAMES
from src.utils_weekly import is_weekly_start_reached


class TaskCardController(GameListController):
    # notify 信号就地定义（与 property 同类），避免 PySide6 跨类 notify 段错误
    taskStateChanged = Signal()

    @Property(str, notify=taskStateChanged)
    def taskTitle(self) -> str:
        """当前游戏显示名（任务卡标题）。"""
        return self._games[self.current_index]["display_name"]

    @Property(bool, notify=taskStateChanged)
    def taskAdapted(self) -> bool:
        """当前游戏是否已注册副本适配（决定日常/周常行显隐）。"""
        return is_adapted(self._games[self.current_index]["script_name"])

    @Property(bool, notify=taskStateChanged)
    def dailySupported(self) -> bool:
        """当前游戏是否有可配置日常副本（dungeon_map 有配置 → 显示日常行）。

        区别于 taskAdapted（是否在 _CONFIGS 注册）：部分游戏虽已注册，但
        dungeon_list 无实际副本（如原神仅检查、终末地骨架），无需日常行。
        """
        return bool(
            self._dungeon_map_cache.get(self._games[self.current_index]["script_name"])
        )

    @Property(str, notify=taskStateChanged)
    def dailyDungeonText(self) -> str:
        """日常副本 chip 文字（持久化于 gui_state.json）。"""
        game = self._games[self.current_index]
        saved = self._ui_state.get(game["script_name"], {})
        if not saved.get("dungeon"):
            return "选择副本"
        dungeon_cfg = self._dungeon_map_cache.get(game["script_name"])
        return self._dungeon_chip_text(
            dungeon_cfg, saved.get("dungeon"), saved.get("sequence")
        )

    @Property(bool, notify=taskStateChanged)
    def weeklySupported(self) -> bool:
        """当前游戏是否支持周常（决定周常行可选性 / 整行样式）。"""
        return _supports_weekly(self._games[self.current_index]["script_name"])

    @Property(str, notify=taskStateChanged)
    def weeklyStartLabel(self) -> str:
        """周常 chip 文字（周几起 / 选择周几）。"""
        game = self._games[self.current_index]
        saved = self._ui_state.get(game["script_name"], {})
        start_day = saved.get("weekly_start")
        return "选择周几" if start_day is None else f"{WEEKDAY_NAMES[start_day]}起"

    @Property(bool, notify=taskStateChanged)
    def masterOn(self) -> bool:
        """总开关状态（全局 UI 态；驱动日常行开关）。"""
        return self._master_on

    @Property(bool, notify=taskStateChanged)
    def dailyOn(self) -> bool:
        """日常行开关（镜像总开关，由 toggleMaster 驱动）。"""
        return self._master_on

    @Property(bool, notify=taskStateChanged)
    def weeklyOn(self) -> bool:
        """周常行开关（内存态，由 toggleMaster / selectWeekly 置位）。"""
        return self._weekly_toggle_state.get(
            self._games[self.current_index]["script_name"], False
        )

    @Property("QVariantList", notify=taskStateChanged)
    def dungeonOptions(self) -> list:
        """日常副本下拉数据：[{name, clear, sequences:[{label,value}]}, ...]。

        从缓存读取（_reload_games 时构建），避免每次访问重新读盘解析。
        """
        return self._dungeon_options_cache.get(
            self._games[self.current_index]["script_name"], []
        )

    def _refresh_task_card(self):
        """切换游戏后刷新任务卡（标题/适配态/日常/周常由 Property getter 实时读取）。

        仅发信号触发 QML 重读；无需缓存字段。
        """
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

    def _init_weekly_toggle_states(self) -> dict:
        """初始化各脚本周常开关（纯内存 UI 态，不持久化、不写脚本配置）。

        启动时由 weekly_start 决定：已设置「周几起」且今天周几 >= 起始日 → True，
        否则 False。对齐旧 GUI._init_weekly_toggle_states（QML 版此前漏迁移，
        导致周常行始终显示关闭）。
        """
        states: dict[str, bool] = {}
        for game in self._games:
            script_name = game["script_name"]
            if not _supports_weekly(script_name):
                continue
            saved = self._ui_state.get(script_name)
            weekly_start = saved.get("weekly_start") if saved else None
            states[script_name] = weekly_start is not None and is_weekly_start_reached(
                weekly_start
            )
        return states

    @Slot(bool)
    def toggleMaster(self, on: bool):
        """总开关：一键同步日常/周本（支持周常时周常开关一并置位）。"""
        self._master_on = on
        script_name = self._games[self.current_index]["script_name"]
        if _supports_weekly(script_name):
            self._weekly_toggle_state[script_name] = on
        self.taskStateChanged.emit()

    @Slot(bool)
    def toggleWeekly(self, on: bool):
        """周常开关（内存态，不持久化；与日常开关模型一致）。"""
        script_name = self._games[self.current_index]["script_name"]
        self._weekly_toggle_state[script_name] = on
        self.taskStateChanged.emit()

    @Slot(str, "QVariant")
    def selectDungeon(self, dungeon_name: str, sequence):
        """选择日常副本（持久化到 gui_state.json 的 dungeon/sequence）。"""
        script_name = self._games[self.current_index]["script_name"]
        saved = self._ui_state.setdefault(script_name, {})
        if not dungeon_name or dungeon_name == "未选择":
            saved.pop("dungeon", None)
            saved.pop("sequence", None)
        else:
            saved["dungeon"] = dungeon_name
            saved["sequence"] = sequence
        self.service.save_ui_state(self._ui_state)
        self._refresh_task_card()

    @Slot(int)
    def selectWeekly(self, start_day: int):
        """选择周常起始日（持久化 weekly_start；周常开关按「今天>=起始日」置位）。"""
        assert start_day in WEEKDAY_NAMES, f"[bridge] 非法周几: {start_day}"
        script_name = self._games[self.current_index]["script_name"]
        saved = self._ui_state.setdefault(script_name, {})
        saved["weekly_start"] = start_day
        enabled = is_weekly_start_reached(start_day)
        self._weekly_toggle_state[script_name] = enabled
        self.service.save_ui_state(self._ui_state)
        self._refresh_task_card()
