"""QML GUI 中央控制器（单例）：组合各职责控制器，编排初始化与跨控制器流程。

经 qmlRegisterSingletonInstance 注册为 QML 的 `Bridge`（见 launcher.py）。
各职责在 src/gui/controllers/ 下独立实现，本门面只做组合、委托与编排
（选脚本 → 刷背景 + 任务卡）。
"""

import logging

from PySide6.QtCore import Property, QCoreApplication, QObject, Signal, Slot
from ruamel.yaml.error import YAMLError

from src.gui.config_warmer import ConfigWarmer
from src.gui.controllers.background import BackgroundController
from src.gui.controllers.backup import BackupController
from src.gui.controllers.game_list import GameListController
from src.gui.controllers.launch import LaunchController
from src.gui.controllers.links import LinksController
from src.gui.controllers.task_card import TaskCardController
from src.gui.controllers.window import WindowController
from src.gui.icons import UiIconProvider
from src.service.app_service import AppService

logger = logging.getLogger(__name__)


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

    def __init__(self, *, cli_backend=False, cli_client=None):
        super().__init__()
        self.app_service = AppService()
        self._cli_client = None
        self._snapshot_generation = 0
        if cli_backend:
            from src.gui.cli_client import CliClient

            self._cli_client = cli_client or CliClient(self)
            app = QCoreApplication.instance()
            assert app is not None
            app.aboutToQuit.connect(self.close_cli)
        # 组合各职责控制器：每个自管状态 + 信号；经构造注入显式依赖
        self.game_list = GameListController(
            app_service=self.app_service,
            toast=self.toastRequested.emit,
            on_reload=lambda: self._reload_games(),
        )
        if self._cli_client is None:
            self.task_card = TaskCardController(
                game_list=self.game_list,
                app_service=self.app_service,
                toast=self.toastRequested.emit,
            )
        else:
            from src.gui.controllers.cli_task_card import CliTaskCardController

            self.task_card = CliTaskCardController(
                self.game_list,
                self.app_service,
                self.toastRequested.emit,
                self._cli_client,
            )
        self.background = BackgroundController(
            game_list=self.game_list,
            app_service=self.app_service,
            toast=self.toastRequested.emit,
        )
        self.launch = LaunchController(
            game_list=self.game_list,
            task_card=self.task_card,
            app_service=self.app_service,
            toast=self.toastRequested.emit,
        )
        self.links = LinksController(
            game_list=self.game_list,
            toast=self.toastRequested.emit,
            app_service=self.app_service,
        )
        self.backup = BackupController(
            app_service=self.app_service,
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
        self.background.backgroundChanged.connect(self.backgroundChanged.emit)
        self.background.toastRequested.connect(self.toastRequested.emit)
        self.task_card.taskStateChanged.connect(self.taskStateChanged.emit)
        self.task_card.toastRequested.connect(self.toastRequested.emit)
        self.launch.toastRequested.connect(self.toastRequested.emit)
        self.links.toastRequested.connect(self.toastRequested.emit)
        self.backup.toastRequested.connect(self.toastRequested.emit)
        self.backup.restoreCompleted.connect(self.task_card.refresh)
        # 首次加载固化旧计划名单，之后的手动勾选不影响每日计划。
        if self._cli_client is None:
            self.game_list.gamesChanged.connect(self.backup.daily_plan.refresh)

        # 编排启动：重建列表 → 构建副本缓存 → 刷新当前（_reload_games 收尾即刷）
        self._reload_games()

        # 启动后空闲预热各脚本 config：事件循环驱动、逐脚本、错开关键路径，
        # 用户点选时已在缓存（functools.cache 单例复用）。失败不拖垮启动。
        self._config_warmer = ConfigWarmer(
            self.app_service.get_registered_script_names()
            if self._cli_client is None
            else [],
            self.app_service.warm_config,
            self,
        )

    def start_config_warmup(self) -> None:
        """窗口可见后启动空闲预热（由 launcher 在首帧渲染后调用）。

        warmup 经 QTimer 在事件循环中逐脚本跑，错开关键路径；此处仅在
        窗口已显示后才挂起定时器，避免装载/模态期间提前占用主线程。
        收尾再接一次输入框预热（见 _prewarm_line_edit），不与 config 预热争首帧后的时间。
        """
        self._config_warmer.finished.connect(self._prewarm_line_edit)
        self._config_warmer.start()

    @Slot()
    def _prewarm_line_edit(self) -> None:
        """建一次 QLineEdit 后立即丢弃。

        QLineEdit 在进程内首次实例化要花约 0.3 秒（Qt 侧一次性初始化），配置弹窗含多个
        输入框；提前在启动后空闲付掉，点右下齿轮打开弹窗时不必再等这笔开销。此处不读配置、
        不构造窗口，预热的对象就是这一次性初始化本身。
        """
        from PySide6.QtWidgets import QLineEdit

        edit = QLineEdit()
        edit.deleteLater()

    # ── QML 属性（委托到子控制器）────────────────────────────────────
    cliBackend = Property(
        bool, lambda self: self._cli_client is not None, constant=True
    )
    taskBusy = Property(
        bool,
        lambda self: self._cli_client is not None and self.task_card.busy,
        notify=taskStateChanged,
    )
    taskStatus = Property(
        str,
        lambda self: self.task_card.status if self._cli_client is not None else "",
        notify=taskStateChanged,
    )

    @Slot()
    def close_cli(self):
        if self._cli_client is not None:
            self._cli_client.close()

    @Slot()
    def refreshTasks(self):
        if not self.taskBusy:
            self._reload_games()

    def _allow_local_action(self) -> bool:
        if self._cli_client is None:
            return True
        self.toastRequested.emit("CLI 测试模式仅开放脚本浏览与任务卡编辑")
        return False

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
    backgroundPreviewUrl = Property(
        str,
        lambda self: self.background.background_preview_url,
        notify=backgroundChanged,
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
    dailyItems = Property(
        "QVariantList", lambda self: self.task_card.daily_items, notify=taskStateChanged
    )
    weeklySupported = Property(
        bool, lambda self: self.task_card.weekly_supported, notify=taskStateChanged
    )
    weeklyItems = Property(
        "QVariantList",
        lambda self: self.task_card.weekly_items,
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
        if self._allow_local_action():
            self.game_list.reorderGames(src, dst)

    @Slot()
    def addScript(self):
        if self._allow_local_action():
            self.game_list.addScript()

    @Slot("QVariantList", result=bool)
    def canDropScripts(self, urls):
        return self._cli_client is None and self.game_list.canDropScripts(urls)

    @Slot("QVariantList", result=bool)
    def dropScripts(self, urls):
        return self._allow_local_action() and self.game_list.dropScripts(urls)

    @Slot(int)
    def deleteScript(self, index):
        if self._allow_local_action():
            self.game_list.deleteScript(index)

    @Slot()
    def configCurrent(self):
        if self._allow_local_action():
            self.game_list.configCurrent()

    @Slot()
    def launchAll(self):
        if self._allow_local_action():
            self.launch.launchAll()

    def maybe_auto_launch(self) -> None:
        """按启动设置弹倒计时确认；关闭自动启动或未启用脚本时不弹窗。

        与自动关机（shutdown_dialog）同款 UX：倒计时归零/点「立即启动」→ 启动全部，
        取消/关窗 → 不启动。无人值守启动跳过运行前确认窗（``confirm=False``），直接按
        已落盘的 config/schedule 启动当前启用的脚本。无启用脚本时无需弹窗。
        """
        if self._cli_client is not None or not any(self.game_list.enabled):
            return
        try:
            if self.app_service.load_daily_plan().enabled:
                return
            options = self.app_service.load_startup_options()
        except (OSError, YAMLError) as exc:
            logger.error("读取启动设置失败：%s: %s", type(exc).__name__, exc)
            self.toastRequested.emit(f"读取启动设置失败，已取消自动启动：{exc}")
            return
        if not options.enabled:
            return
        from src.gui.startup_dialog import confirm_startup

        if confirm_startup(options.delay_seconds):
            self.launch.launchAll(confirm=False)

    @Slot()
    def launchScript(self):
        if self._allow_local_action():
            self.launch.launchScript()

    @Slot()
    def launchGame(self):
        if self._allow_local_action():
            self.links.launchGame()

    @Slot(result=str)
    def gameIconSource(self):
        return self.links.gameIconSource()

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
        if self._allow_local_action():
            self.links.openSettings()

    @Slot()
    def openScriptConfig(self):
        self.links.openScriptConfig()

    @Slot()
    def startWindowMove(self):
        self.window.startWindowMove()

    @Slot()
    def minimize(self):
        self.window.minimize()

    @Slot()
    def closeWindow(self):
        self.window.closeWindow()

    @Slot(str, str, "QVariant")
    def selectDaily(self, daily_name, task_name, seq):
        self.task_card.selectDaily(daily_name, task_name, seq)

    @Slot(str, bool)
    def setDailyEnabled(self, daily_name, enabled):
        self.task_card.setDailyEnabled(daily_name, enabled)

    @Slot(str, result="QVariantList")
    def dailyOptions(self, daily_name):
        return self.task_card.daily_options(daily_name)

    @Slot(str, str)
    def selectWeekly(self, weekly_name, task_name):
        self.task_card.selectWeekly(weekly_name, task_name)

    @Slot(str, result="QVariantList")
    def weeklyOptions(self, weekly_name):
        return self.task_card.weekly_task_options(weekly_name)

    @Slot(result="QVariantList")
    def weeklyStartOptions(self):
        return self.task_card.weekly_start_options

    @Slot(str, int)
    def selectWeeklyStart(self, weekly_name, start_day):
        self.task_card.selectWeeklyStart(weekly_name, start_day)

    @Slot(str)
    def videoError(self, reason):
        self.background.videoError(reason)

    @Slot(QObject, int, result=bool)
    def videoFrameReady(self, sink, version):
        return self.background.video_frame_ready(sink, version)

    @Slot()
    def openWallpaper(self):
        if self._allow_local_action():
            self.background.open_wallpaper()

    @Slot()
    def openConfig(self):
        if self._allow_local_action():
            self.backup.openConfig()

    @Slot()
    def backupConfig(self):
        if self._allow_local_action():
            self.backup.backupConfig()

    @Slot()
    def restoreConfig(self):
        if self._allow_local_action():
            self.backup.restoreConfig()

    # ── 编排 / 门面协调方法（保持既有测试可直接调用）─────────────────
    def _reload_games(self):
        """重建脚本列表 + 构建副本下拉缓存 + 刷新当前项（编排集中于此）。

        编辑当前脚本（configCurrent/addScript/deleteScript）后数据已变，
        必须强制刷新背景与任务卡，否则 UI 停在旧数据直到重新点选。
        """
        if self._cli_client is not None:
            self._snapshot_generation += 1
            generation = self._snapshot_generation
            self.task_card.build_daily_cache()
            self.task_card.busy = True
            self.task_card.status = "加载列表"
            self.taskStateChanged.emit()

            def loaded(result, error):
                if generation != self._snapshot_generation:
                    return
                if error is not None:
                    assert "message" in error
                    self.task_card.busy = False
                    self.task_card.status = "连接失败 · 请刷新"
                    self.taskStateChanged.emit()
                    self.toastRequested.emit(error["message"])
                    return
                self.game_list.reload_games(result)
                self._on_current_changed()

            self._cli_client.request("app.snapshot", {}, loaded)
            return
        self.game_list.reload_games()
        self.task_card.build_daily_cache()
        self._on_current_changed()

    def _on_current_changed(self):
        """当前选中变化 → 刷新背景 + 任务卡（编排集中于此）。"""
        self._apply_current()
        self.task_card.refresh()

    def _apply_current(self):
        if not self.game_list.games:
            return  # 空列表（手改 config 删空）无当前项，跳过背景刷新
        self.background.apply_current(self.game_list.current_game)


__all__ = ["QmlBridge", "UiIconProvider"]
