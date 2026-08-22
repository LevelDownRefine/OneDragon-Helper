"""QML GUI 中央控制器（单例）：组合各职责控制器，编排初始化与跨控制器流程。

经 qmlRegisterSingletonInstance 注册为 QML 的 `Bridge`（见 launcher.py）。
各职责在 src/gui/controllers/ 下独立实现，本门面只做组合、委托与编排
（选脚本 → 刷背景 + 任务卡）。
"""

from PySide6.QtCore import Property, QObject, Signal, Slot

from src.gui.controllers.background import BackgroundController
from src.gui.controllers.game_list import GameListController
from src.gui.controllers.launch import LaunchController
from src.gui.controllers.links import LinksController
from src.gui.controllers.task_card import TaskCardController
from src.gui.controllers.window import WindowController
from src.gui.icons import UiIconProvider
from src.service.chain_service import ChainService


class QmlBridge(QObject):
    # QML 面向 Bridge 的信号（转发自子控制器）
    toastRequested = Signal(str)
    gamesChanged = Signal()
    currentIndexChanged = Signal()
    enabledChanged = Signal()
    controlModeChanged = Signal()
    backgroundChanged = Signal()
    taskStateChanged = Signal()
    gameAdded = Signal()

    def __init__(self):
        super().__init__()
        self.service = ChainService()
        # 组合各职责控制器：每个自管状态 + 信号；经构造注入显式依赖
        self.game_list = GameListController(
            service=self.service,
            toast=self.toastRequested.emit,
            on_reload=lambda: self._reload_games(),
        )
        self.task_card = TaskCardController(
            game_list=self.game_list,
            service=self.service,
            toast=self.toastRequested.emit,
        )
        self.background = BackgroundController(
            game_list=self.game_list,
            task_card=self.task_card,
            toast=self.toastRequested.emit,
        )
        self.launch = LaunchController(
            game_list=self.game_list,
            task_card=self.task_card,
            service=self.service,
            toast=self.toastRequested.emit,
        )
        self.links = LinksController(
            game_list=self.game_list,
            toast=self.toastRequested.emit,
        )
        self.window = WindowController()
        # UI 矢量图标提供器（无状态，门面持有）
        self._ui_icon_provider = UiIconProvider()

        # 转发子控制器信号 → Bridge 同名信号（供 QML 绑定）
        self.game_list.gamesChanged.connect(self.gamesChanged.emit)
        self.game_list.currentIndexChanged.connect(self.currentIndexChanged.emit)
        self.game_list.currentIndexChanged.connect(self._on_current_changed)
        self.game_list.enabledChanged.connect(self.enabledChanged.emit)
        self.game_list.controlModeChanged.connect(self.controlModeChanged.emit)
        self.game_list.gameAdded.connect(self.gameAdded.emit)
        self.game_list.toastRequested.connect(self.toastRequested.emit)
        self.background.backgroundChanged.connect(self.backgroundChanged.emit)
        self.background.toastRequested.connect(self.toastRequested.emit)
        self.task_card.taskStateChanged.connect(self.taskStateChanged.emit)
        self.task_card.toastRequested.connect(self.toastRequested.emit)
        self.launch.toastRequested.connect(self.toastRequested.emit)
        self.links.toastRequested.connect(self.toastRequested.emit)

        # 编排启动：重建列表 → 构建副本缓存 → 还原周常开关 → 刷新当前
        self._reload_games()
        self.task_card.init_weekly_toggle_states()
        self._on_current_changed()

    # ── QML 属性（委托到子控制器）────────────────────────────────────
    games = Property(
        "QVariantList", lambda self: self.game_list.games, notify=gamesChanged
    )
    gameModel = Property(
        QObject, lambda self: self.game_list.game_model, notify=gamesChanged
    )
    currentIndex = Property(
        int, lambda self: self.game_list.current_index, notify=currentIndexChanged
    )
    enabledStates = Property(
        "QVariantList", lambda self: self.game_list.enabled, notify=enabledChanged
    )
    controlMode = Property(
        bool, lambda self: self.game_list.control_mode, notify=controlModeChanged
    )
    backgroundMode = Property(
        str, lambda self: self.background.background_mode, notify=backgroundChanged
    )
    backgroundUrl = Property(
        str, lambda self: self.background.background_url, notify=backgroundChanged
    )
    backgroundVersion = Property(
        int, lambda self: self.background.background_version, notify=backgroundChanged
    )
    gradientColor = Property(
        str, lambda self: self.background.gradient_color, notify=backgroundChanged
    )
    gradientChar = Property(
        str, lambda self: self.background.gradient_char, notify=backgroundChanged
    )
    taskTitle = Property(
        str, lambda self: self.task_card.task_title, notify=taskStateChanged
    )
    taskAdapted = Property(
        bool, lambda self: self.task_card.task_adapted, notify=taskStateChanged
    )
    dailySupported = Property(
        bool, lambda self: self.task_card.daily_supported, notify=taskStateChanged
    )
    dailyDungeonText = Property(
        str, lambda self: self.task_card.daily_dungeon_text, notify=taskStateChanged
    )
    weeklySupported = Property(
        bool, lambda self: self.task_card.weekly_supported, notify=taskStateChanged
    )
    weeklyStartLabel = Property(
        str, lambda self: self.task_card.weekly_start_label, notify=taskStateChanged
    )
    masterOn = Property(
        bool, lambda self: self.task_card.master_on, notify=taskStateChanged
    )
    dailyOn = Property(
        bool, lambda self: self.task_card.daily_on, notify=taskStateChanged
    )
    weeklyOn = Property(
        bool, lambda self: self.task_card.weekly_on, notify=taskStateChanged
    )
    dungeonOptions = Property(
        "QVariantList",
        lambda self: self.task_card.dungeon_options,
        notify=taskStateChanged,
    )

    # ── QML 图像提供器（供 launcher 注册到引擎）──────────────────────
    @property
    def ui_icon_provider(self):
        """通用 UI 矢量图标源 `image://uiicon`（无状态，门面持有）。"""
        return self._ui_icon_provider

    # ── QML 槽（委托到子控制器）──────────────────────────────────────
    @Slot(int)
    def selectGame(self, index):
        self.game_list.selectGame(index)

    @Slot()
    def toggleMode(self):
        self.game_list.toggleMode()

    @Slot()
    def selectAll(self):
        self.game_list.selectAll()

    @Slot()
    def deselectAll(self):
        self.game_list.deselectAll()

    @Slot(int, int)
    def reorderGames(self, src, dst):
        self.game_list.reorderGames(src, dst)

    @Slot()
    def addScript(self):
        self.game_list.addScript()

    @Slot()
    def configCurrent(self):
        self.game_list.configCurrent()

    @Slot()
    def launchAll(self):
        self.launch.launchAll()

    @Slot()
    def launchScript(self):
        self.launch.launchScript()

    @Slot()
    def launchGame(self):
        self.links.launchGame()

    @Slot()
    def openHome(self):
        self.links.openHome()

    @Slot()
    def openBilibili(self):
        self.links.openBilibili()

    @Slot()
    def openGithub(self):
        self.links.openGithub()

    @Slot()
    def openScriptFolder(self):
        self.links.openScriptFolder()

    @Slot()
    def openLogFolder(self):
        self.links.openLogFolder()

    @Slot()
    def openSettings(self):
        self.links.openSettings()

    @Slot()
    def startWindowMove(self):
        self.window.startWindowMove()

    @Slot()
    def minimize(self):
        self.window.minimize()

    @Slot()
    def closeWindow(self):
        self.window.closeWindow()

    @Slot(bool)
    def toggleMaster(self, on):
        self.task_card.toggleMaster(on)

    @Slot(bool)
    def toggleWeekly(self, on):
        self.task_card.toggleWeekly(on)

    @Slot(str, "QVariant")
    def selectDungeon(self, name, seq):
        self.task_card.selectDungeon(name, seq)

    @Slot(int)
    def selectWeekly(self, day):
        self.task_card.selectWeekly(day)

    @Slot(str)
    def videoError(self, reason):
        self.background.videoError(reason)

    @Slot()
    def openWallpaper(self):
        self.background.open_wallpaper()

    # ── 编排 / 门面协调方法（保持既有测试可直接调用）─────────────────
    def _reload_games(self):
        """重建脚本列表 + 构建副本下拉缓存（编排 game_list 与 task_card）。"""
        self.game_list.reload_games()
        self.task_card.build_dungeon_cache(self.game_list.games)

    def _on_current_changed(self):
        """当前选中变化 → 刷新背景 + 任务卡（编排集中于此）。"""
        self._apply_current()

    def _apply_current(self):
        self.background.apply_current(self.game_list.current_game)


__all__ = ["QmlBridge", "ChainService", "UiIconProvider"]
