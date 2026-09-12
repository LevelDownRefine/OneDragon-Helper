"""任务卡控制器：日常副本 / 周常周几（数据 + 选择持久化）。

日常声明缓存于 _daily_map_cache；选择与菜单由 service 提供。
原生任务启停经 service 更新，控制器只转发操作和刷新界面。
"""

from PySide6.QtCore import QObject, Signal, Slot

from src.config.set_config import is_adapted

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
        # 副本下拉数据缓存：task_list.yml 解析较贵且运行期不变，
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
        """当前脚本的日常行，由 service 反读各自的选择。"""
        script_name = self._current["script_name"]
        definitions = self._daily_map_cache.get(script_name, [])  # 未声明日常时无行
        return self._app_service.get_daily_items(script_name, definitions)

    @property
    def weekly_supported(self) -> bool:
        """当前游戏是否支持周常（决定周常行显隐）。

        唯一真相源为 task_list.yml：声明了该脚本周常即支持。
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
        """当前脚本的周常行，由 service 反读选择并组装。"""
        return self._app_service.get_weekly_items(self._current["script_name"])

    def weekly_task_options(self, weekly_name: str) -> list[str]:
        """指定周常的菜单名称，由 service 提供。"""
        return self._app_service.get_weekly_task_options(
            self._current["script_name"], weekly_name
        )

    def build_daily_cache(self):
        """缓存日常声明；当前选择在刷新时由 service 反读。"""
        self._daily_map_cache = self._app_service.get_daily_map()

    def refresh(self):
        """切换游戏后发信号触发 QML 重读任务卡。"""
        self.taskStateChanged.emit()

    @Slot(str, str, "QVariant")
    def selectDailyTask(self, daily_name: str, option_name: str, sequence):
        """选择指定日常的副本，经 service 实时写回。"""
        if option_name:
            self._app_service.set_daily_task(
                self._current["script_name"],
                daily_name,
                option_name=option_name,
                sequence=sequence,
            )
        self.refresh()

    @Slot(str, bool)
    def setTaskEnabled(self, task_name: str, enabled: bool):
        self._app_service.set_task_enabled(
            self._current["script_name"], task_name, enabled
        )
        self.refresh()

    @Slot(str, str)
    @Slot(str, str, "QVariant")
    def selectWeeklyTaskOption(self, weekly_name: str, option_name: str, sequence=None):
        """选择某周常的副本（写回脚本自身 config）。

        Args:
            weekly_name: 周常名（如「历战余响」）。
            option_name: 选中的副本名（来自 weekly_task_options）。
        """
        script_name = self._current["script_name"]
        # 写回脚本自身 config（如 M7A config.yaml 的 instance_names[weekly_name]），经 service
        self._app_service.set_weekly_task_option(
            script_name, weekly_name, option_name, sequence
        )
        self.refresh()
