"""QML 应用桥接：把 Python 业务逻辑（ChainService / set_config）暴露给 QML。

QML 侧通过 context property `Bridge` 访问脚本列表与背景状态；脚本图标经
`image://scripticon/<script_name>` 由 ScriptIconProvider 提供（复用 get_script_icon，
避免 QML 直接读 exe 图标）。旧 Widgets GUI（main_window/widgets/task_card）已删除，
QML GUI 为正式入口。
"""

import os
import subprocess
import sys
import webbrowser

from PySide6.QtCore import (
    Property,
    QObject,
    QPointF,
    QRect,
    QRectF,
    Qt,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtQuick import QQuickImageProvider

from src.config.dungeon_config import get_display_name, parse_dungeon_config
from src.config.set_config import get_game_bg_img as _get_game_bg_img
from src.config.set_config import get_game_bilibili as _get_game_bilibili
from src.config.set_config import get_game_exe_path as _get_game_exe_path
from src.config.set_config import get_game_github as _get_game_github
from src.config.set_config import get_game_homepage as _get_game_homepage
from src.config.set_config import is_adapted
from src.config.set_config import supports_weekly as _supports_weekly
from src.config.subscript import get_script_name, resolve_script_path
from src.gui.game_list_model import GameListModel
from src.gui.icons import _GITHUB_SVG
from src.gui.theme import (
    _URL_BILIBILI,
    _URL_HOME,
    C_GAME_DIM,
    DEFAULT_BG,
    WEEKDAY_NAMES,
)
from src.service.chain_service import ChainService
from src.utils import get_config_yml_path_under_root
from src.utils_runner import build_script_command
from src.utils_weekly import is_weekly_start_reached

# 走 QML VideoOutput 的扩展名（其余一律按图片处理）
VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".mov"}


def is_video(path: str) -> bool:
    """扩展名识别是否走视频背景。"""
    return os.path.splitext(path)[1].lower() in VIDEO_EXTS


class ScriptIconProvider(QQuickImageProvider):
    """QML Image 的脚本图标源：`image://scripticon/<script_name>`。

    cache key 用 script_name 这个**稳定标识**而非行 index：重排只改行位置、
    index 不变，若按 index 缓存每格图标会停在启动时的旧图标（"图标不跟着
    重排"的根因）。按 script_name 缓存后，无论行位置怎么变，图标都按游戏身份
    正确解析。

    构造时在主线程预生成全部图标缓存（Shell 提取 exe 图标较慢，集中到
    启动阶段一次性完成），requestPixmap 只查内存缓存——避免 QML 场景
    加载期间逐图标同步提取导致窗口卡住。
    """

    def __init__(self, games: list):
        super().__init__(QQuickImageProvider.Pixmap)
        self._cache: dict[str, QPixmap] = {}
        self.refresh(games)

    def _load_icon(self, script_data: dict) -> QPixmap:
        # 复用 icons.get_script_icon（exe 内嵌图标 / python 默认图标）
        from src.gui.icons import get_script_icon

        icon = get_script_icon(script_data)
        return icon.pixmap(48, 48)

    def refresh(self, games: list):
        """增量更新缓存：只为新脚本提取图标，已有脚本复用缓存（避免重复 Shell 提取）。

        增删脚本后（_reload_games）调用，保证新脚本也能取到图标。
        """
        for game in games:
            name = game["script_name"]
            if name not in self._cache:
                self._cache[name] = self._load_icon(game["script_data"])

    def requestPixmap(self, id: str, size, requestedSize):
        return self._cache.get(id, QPixmap())


# UI 通用矢量图标（重绘版）：旧 icons.py 的 draw_* 造型不佳且无法直接用于 QML，
# 此处用干净的矢量重画，经 image://uiicon/<name> 提供给 QML Image。
# 每个 draw 方法把 painter translate 到画布中心，在 48x48 画布内绘制（白图形）。
_WHITE = QColor("#FFFFFF")
_CUT = QColor("#1F2937")  # 图标内部"挖空"色，对齐按钮底色，使镂空处透出按钮背景


class UiIconProvider(QQuickImageProvider):
    """QML 通用 UI 矢量图标源：`image://uiicon/<name>`。

    name → 重绘矢量图标。静态图标，无需游戏数据，构造即就绪。
    支持：home / game / folder / bili / github / wallpaper / settings / min / close。
    """

    _SIZE = 48

    def __init__(self):
        super().__init__(QQuickImageProvider.Pixmap)
        self._cache: dict[str, QPixmap] = {}
        self._github_renderer = None
        self._drawers = {
            "home": self._draw_home,
            "game": self._draw_game,
            "folder": self._draw_folder,
            "bili": self._draw_bili,
            "github": self._draw_github,
            "wallpaper": self._draw_wallpaper,
            "settings": self._draw_settings,
            "min": self._draw_min,
            "close": self._draw_close,
        }

    def _render(self, name: str) -> QPixmap:
        pm = QPixmap(self._SIZE, self._SIZE)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.translate(self._SIZE / 2, self._SIZE / 2)
        self._drawers[name](p)
        p.end()
        return pm

    def requestPixmap(self, id: str, size, requestedSize):
        if id not in self._drawers:
            return QPixmap()
        if id not in self._cache:
            self._cache[id] = self._render(id)
        return self._cache[id]

    # ═══════════════ 各图标矢量绘制（中心原点，半径≈16）══════════════
    def _draw_home(self, p: QPainter):
        p.setPen(QPen(_WHITE, 3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        roof = QPainterPath()
        roof.moveTo(-13, -1)
        roof.lineTo(0, -13)
        roof.lineTo(13, -1)
        p.drawPath(roof)  # 屋顶
        p.drawLine(-10, -1, -10, 12)  # 左墙
        p.drawLine(10, -1, 10, 12)  # 右墙
        p.drawLine(-10, 12, 10, 12)  # 地
        p.setPen(Qt.NoPen)
        p.setBrush(_WHITE)
        p.drawRect(QRectF(-3, 4, 6, 8))  # 门

    def _draw_game(self, p: QPainter):
        p.setPen(Qt.NoPen)
        p.setBrush(_WHITE)
        # 手柄主体 + 两侧握把
        p.drawRoundedRect(QRectF(-13, -7, 26, 14), 7, 7)
        p.drawRoundedRect(QRectF(-16, 1, 6, 11), 3, 3)
        p.drawRoundedRect(QRectF(10, 1, 6, 11), 3, 3)
        # 十字键（镂空，左下）
        p.setBrush(_CUT)
        p.drawRect(QRectF(-11, -3, 3, 9))
        p.drawRect(QRectF(-14, 0, 9, 3))
        # AB 圆点（镂空，右上斜排）
        p.drawEllipse(QRectF(5, -4, 3, 3))
        p.drawEllipse(QRectF(9, -1, 3, 3))

    def _draw_folder(self, p: QPainter):
        p.setPen(QPen(_WHITE, 2.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        path = QPainterPath()
        path.moveTo(-15, -9)
        path.lineTo(-5, -9)
        path.lineTo(-1, -4)
        path.lineTo(11, -4)
        path.lineTo(15, -1)
        path.lineTo(15, 11)
        path.lineTo(-15, 11)
        path.closeSubpath()
        p.drawPath(path)

    def _draw_bili(self, p: QPainter):
        # B站小电视：天线 + 圆角机身 + 屏幕双眼
        pen = QPen(_WHITE, 2.4, Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawLine(-7, -11, -11, -15)  # 左天线
        p.drawLine(7, -11, 11, -15)  # 右天线
        p.setPen(Qt.NoPen)
        p.setBrush(_WHITE)
        p.drawRoundedRect(QRectF(-14, -12, 28, 22), 5, 5)  # 机身
        p.setBrush(_CUT)
        p.drawRoundedRect(QRectF(-11, -9, 22, 16), 3, 3)  # 屏幕
        p.setBrush(_WHITE)
        p.drawEllipse(QRectF(-6, -4, 3, 3))  # 左眼
        p.drawEllipse(QRectF(3, -4, 3, 3))  # 右眼

    def _draw_github(self, p: QPainter):
        # Octocat 单色 logo：缩放至与其他图标一致的视觉尺寸（半径≈15，画布 48
        # 内占 30），不复用 icons.draw_github（其渲染区仅 20×20，相对偏小）。
        from PySide6.QtCore import QByteArray
        from PySide6.QtSvg import QSvgRenderer

        if self._github_renderer is None:
            self._github_renderer = QSvgRenderer(QByteArray(_GITHUB_SVG.encode()))
        self._github_renderer.render(p, QRect(-15, -15, 30, 30))

    def _draw_wallpaper(self, p: QPainter):
        # 图片框 + 太阳 + 山形
        pen = QPen(_WHITE, 2.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(-14, -11, 28, 22), 4, 4)  # 相框
        p.setPen(Qt.NoPen)
        p.setBrush(_WHITE)
        p.drawEllipse(QRectF(-9, -8, 5, 5))  # 太阳
        mountain = QPainterPath()
        mountain.moveTo(-14, 11)
        mountain.lineTo(-4, -2)
        mountain.lineTo(2, 5)
        mountain.lineTo(8, -1)
        mountain.lineTo(14, 11)
        mountain.closeSubpath()
        p.drawPath(mountain)  # 山

    def _draw_settings(self, p: QPainter):
        # 齿轮：8 外齿 + 主体圆 + 内孔
        import math

        pen = QPen(_WHITE, 2, Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        for i in range(8):
            a = math.radians(i * 45)
            p.drawLine(
                QPointF(7 * math.cos(a), 7 * math.sin(a)),
                QPointF(11 * math.cos(a), 11 * math.sin(a)),
            )
        p.drawEllipse(QRectF(-8, -8, 16, 16))
        p.drawEllipse(QRectF(-3, -3, 6, 6))

    def _draw_min(self, p: QPainter):
        p.setPen(QPen(_WHITE, 2.4, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(-8, 0, 8, 0)

    def _draw_close(self, p: QPainter):
        p.setPen(QPen(_WHITE, 2.4, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(-7, -7, 7, 7)
        p.drawLine(7, -7, -7, 7)


class QmlBridge(QObject):
    """QML 应用与 Python 业务逻辑的桥接对象（context property: `bridge`）。"""

    backgroundChanged = Signal()  # 背景模式/URL/渐变变化
    gamesChanged = Signal()  # 脚本列表变化（增删/重排/保存配置）
    enabledChanged = Signal()  # enabled 内存态变化（纯 UI，不持久化）
    controlModeChanged = Signal()  # ⊞ 控制模式切换
    toastRequested = Signal(str)  # 右下角 toast 浮层文本
    gameAdded = Signal()  # 添加脚本成功（QML 用于滚动列表到底部）
    taskStateChanged = Signal()  # 任务卡（日常/周常）状态变化

    def __init__(self):
        super().__init__()
        self.service = ChainService()
        self._games: list = []
        # 图标缓存提供器（key=script_name）；addScript 后需 rebuild，故持有引用
        self.icon_provider = None
        # QML ListView 用的 model（QAbstractListModel，重排/增删精确刷新）
        self._game_model = GameListModel()
        self._enabled: list = [True]  # 与 games 一一对应（纯内存态，默认全开）
        self._control_mode = False  # ⊞ 模式：False=浏览，True=控制
        self.current_index = 0
        self._bg_mode = "gradient"  # video | image | gradient
        self._bg_url = ""
        self._grad_color = C_GAME_DIM
        self._grad_char = ""
        # 任务卡状态：gui_state.json 的副本/序列/周常（按 script_name 索引）
        self._ui_state = self.service.load_ui_state()
        # 副本下拉数据缓存：dungeon_list.yml 解析较贵（磁盘读 + YAML 解析），
        # 且运行期内容不变 → 在 _reload_games 时一次性构建，避免在 QML 循环/
        # 绑定反复访问 dungeonOptions 时每次重新读盘解析（曾致下拉打开卡顿）。
        self._dungeon_map_cache: dict = {}
        self._dungeon_options_cache: dict[str, list] = {}
        # 周常开关 UI 态（纯内存，不持久化）；总开关为全局 UI 态（驱动日常行开关）
        self._weekly_toggle_state: dict[str, bool] = {}
        self._master_on = True
        self._reload_games()
        # 启动时按 weekly_start 还原各游戏周常开关（对齐旧 GUI._init_weekly_toggle_states）；
        # 此前漏迁移，周常行始终显示关闭。需放在 _reload_games 之后（依赖 self._games）。
        self._weekly_toggle_state = self._init_weekly_toggle_states()
        self._apply_current()

    # ── 脚本列表 ─────────────────────────────────────────────────────────
    @Property("QVariantList", notify=gamesChanged)
    def games(self) -> list:
        """全部脚本条目：{display_name, script_name, char, color}。"""
        return self._games

    @Property(QObject, notify=gamesChanged)
    def gameModel(self):
        """QML ListView 的 model（QAbstractListModel，重排/增删精确刷新）。"""
        return self._game_model

    @Property(int, notify=backgroundChanged)
    def currentIndex(self) -> int:
        return self.current_index

    @Property("QVariantList", notify=enabledChanged)
    def enabledStates(self) -> list:
        """各脚本启用状态（与 games 一一对应；纯内存态，重启默认全开）。"""
        return self._enabled

    @Property(bool, notify=controlModeChanged)
    def controlMode(self) -> bool:
        return self._control_mode

    def _reload_games(self):
        """从 config.yml 重建脚本列表（对齐 main_window._load_games）。"""
        games = []
        for script in self.service.load_config().get("script_list", []):
            display_name = script["display_name"]
            games.append(
                {
                    "display_name": display_name,
                    "script_name": get_script_name(script),
                    "script_data": script,
                    "char": display_name[0],
                    "color": C_GAME_DIM,
                }
            )
        assert games, "[qml_bridge] config.yml 中没有脚本"
        self._games = games
        self._game_model.set_games(games)  # 同步 QML ListView model
        self.current_index = min(self.current_index, len(games) - 1)
        # 一次性解析 dungeon_list.yml 并构建所有脚本的副本下拉数据（运行期不变）
        self._dungeon_map_cache = self.service.dungeon_map()
        self._dungeon_options_cache = {
            g["script_name"]: self._build_dungeon_options(g["script_name"])
            for g in games
        }
        # 新增脚本默认启用；已存在脚本保留原状态（与旧 GUI 重建语义一致）
        self._enabled = [
            self._enabled[i] if i < len(self._enabled) else True
            for i in range(len(games))
        ]
        # 增删脚本后让图标缓存补齐新脚本（按 script_name，不重建旧图标）
        if self.icon_provider is not None:
            self.icon_provider.refresh(self._games)
        self.gamesChanged.emit()

    @Slot(int)
    def selectGame(self, index: int):
        """QML 点击左侧脚本图标：控制模式切换启停，浏览模式切换选中+刷新背景。"""
        assert 0 <= index < len(self._games), (
            f"[qml_bridge] index out of range: {index}"
        )
        if self._control_mode:
            self._enabled[index] = not self._enabled[index]
            self.enabledChanged.emit()
            self.toastRequested.emit(
                f"{self._games[index]['display_name']}："
                f"{'启用' if self._enabled[index] else '停用'}"
            )
            return
        if index == self.current_index:
            return
        self.current_index = index
        self._apply_current()

    @Slot()
    def toggleMode(self):
        """⊞ 模式切换：浏览（点图标选脚本）⇄ 控制（点图标切换启用/停用）。"""
        self._control_mode = not self._control_mode
        self.controlModeChanged.emit()
        self.toastRequested.emit(
            "控制模式：点击图标切换启用/停用"
            if self._control_mode
            else "浏览模式：点击图标选择脚本"
        )

    @Slot()
    def selectAll(self):
        """全选：所有脚本设为启用（纯内存态，不持久化）。"""
        self._enabled = [True] * len(self._games)
        self.enabledChanged.emit()
        self.toastRequested.emit("已全选（全部启用）")

    @Slot()
    def deselectAll(self):
        """清空：所有脚本设为停用（纯内存态，不持久化）。"""
        self._enabled = [False] * len(self._games)
        self.enabledChanged.emit()
        self.toastRequested.emit("已清空（全部停用）")

    @Slot(int, int)
    def reorderGames(self, src_index: int, dst_index: int):
        """拖拽重排：把 src 移到 dst 位置，同步 UI 与 config.yml（对齐旧 GUI）。"""
        assert 0 <= src_index < len(self._games), (
            f"[qml_bridge] src out of range: {src_index}"
        )
        assert 0 <= dst_index < len(self._games), (
            f"[qml_bridge] dst out of range: {dst_index}"
        )
        cur_name = self._games[self.current_index][
            "script_name"
        ]  # 重排后按名字恢复选中
        game = self._games.pop(src_index)
        self._games.insert(dst_index, game)
        # QML ListView 精确重排。注意：只发 rowsMoved（move）——PySide6 的
        # modelReset（beginResetModel/endResetModel）桥接到 QML 不可靠，
        # reset 后 delegate 卡旧状态；rowsMoved 实测能正确驱动刷新。
        self._game_model.move(src_index, dst_index)
        enabled = self._enabled.pop(src_index)
        self._enabled.insert(dst_index, enabled)

        # 同步 config.yml 顺序（以 UI 顺序为准），持久化
        config_data = self.service.load_config()
        scripts = config_data["script_list"]
        s_idx = next(
            (
                i
                for i, s in enumerate(scripts)
                if get_script_name(s) == game["script_name"]
            ),
            None,
        )
        assert s_idx is not None, "[qml_bridge] config 中找不到源脚本"
        script = scripts.pop(s_idx)
        scripts.insert(dst_index, script)
        self.service.save_config(config_data)

        # 恢复选中（新 index 可能已变）
        self.current_index = next(
            (i for i, g in enumerate(self._games) if g["script_name"] == cur_name),
            len(self._games) - 1,
        )
        self.gamesChanged.emit()
        self.enabledChanged.emit()
        self._apply_current()
        self.toastRequested.emit("已调整脚本顺序")

    @Slot()
    def addScript(self):
        """弹出文件选择框，选完追加脚本到 config.yml 并重建列表（对齐旧 GUI）。"""
        from PySide6.QtWidgets import QFileDialog

        file_path, _ = QFileDialog.getOpenFileName(
            None,
            "选择脚本文件",
            "",
            "可执行文件 Executable files (*.exe *.bat *.py);;所有文件 All files (*.*)",
        )
        if not file_path:
            return
        file_path = os.path.normpath(file_path)
        existing = {g["script_name"] for g in self._games}
        script_data = self.service._script_service.build_script_entry(
            file_path, existing
        )
        self.service.add_script(script_data)
        self._reload_games()
        self.toastRequested.emit(f"已添加 {script_data['display_name']}")
        self.gameAdded.emit()

    @Slot()
    def configCurrent(self):
        """打开当前脚本配置弹窗（复用 SingleScriptConfigDialog，对齐旧 GUI）。

        保存成功（Accepted）→ ChainService.update_script 落盘并重载脚本列表；
        删除（close，非 Accepted）不落盘、不进保存分支。
        """
        if not self._games:
            return
        game = self._games[self.current_index]
        from PySide6.QtWidgets import QDialog

        from src.gui.dialogs import SingleScriptConfigDialog

        dialog = SingleScriptConfigDialog(
            game["script_name"],
            game["display_name"],
            game["script_data"].get("script_path", ""),
            None,
            script_service=self.service._script_service,
        )
        dialog.delete_requested.connect(self._on_delete_script)
        if dialog.exec() == QDialog.Accepted:
            assert dialog.pending_changes is not None, (
                "[qml_bridge] 配置弹窗 accept 但 pending_changes 为空"
            )
            changes = dialog.pending_changes
            self.service.update_script(
                changes["old_script_name"],
                changes["new_display_name"],
                changes["config_patch"],
                changes["weekly_timeouts"],
            )
            self._reload_games()
            self.toastRequested.emit(f"已保存 {changes['new_display_name']} 配置")

    def _on_delete_script(self, script_name: str):
        """配置弹窗确认删除：落盘后重载脚本列表（对齐旧 GUI）。"""
        self.service.remove_script(script_name)
        self._reload_games()

    # ── 任务卡（日常 / 周常）──────────────────────────────────────────────
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
        assert start_day in WEEKDAY_NAMES, f"[qml_bridge] 非法周几: {start_day}"
        script_name = self._games[self.current_index]["script_name"]
        saved = self._ui_state.setdefault(script_name, {})
        saved["weekly_start"] = start_day
        enabled = is_weekly_start_reached(start_day)
        self._weekly_toggle_state[script_name] = enabled
        self.service.save_ui_state(self._ui_state)
        self._refresh_task_card()

    # ── 启动 / 运行 ─────────────────────────────────────────────────────
    @Slot()
    def launchAll(self):
        """启动全部：生成仅含启用脚本的链并运行（对齐旧 GUI enabled 语义）。"""
        keys = {
            g["script_name"]
            for g, on in zip(self._games, self._enabled, strict=True)
            if on
        }
        if not keys:
            self.toastRequested.emit("没有启用的脚本")
            return
        if not self._confirm_run(keys):
            return
        config_data = self.service.load_config()
        self._run_chain(config_data, keys, "启动全部")

    @Slot()
    def launchScript(self):
        """启动当前选中脚本（直接运行，不走链；对齐旧 GUI 图标左键语义）。"""
        game = self._games[self.current_index]
        script = game["script_data"]
        if script.get("script_type") == "python":
            resolved = resolve_script_path(script["script_path"])
            if not resolved or not os.path.isfile(resolved):
                self.toastRequested.emit(f"找不到脚本文件：{script['script_path']}")
                return
            command, cwd, env = build_script_command(["--script", resolved])
            subprocess.Popen(command, cwd=cwd, env=env)
        else:
            exe_path = script.get("script_path", "")
            resolved = resolve_script_path(exe_path) if exe_path else None
            if not resolved or not os.path.isfile(resolved):
                self.toastRequested.emit(f"找不到脚本：{exe_path}")
                return
            os.startfile(resolved)  # noqa: S606 启动脚本本体
        self.toastRequested.emit(f"已启动 {game['display_name']}")

    def _confirm_run(self, enabled_keys: set) -> bool:
        """运行前校验（对齐旧 GUI）+ 确认弹窗。True 继续，False 取消。"""
        from PySide6.QtWidgets import QMessageBox

        config_data = self.service.load_config()
        enabled_scripts = [
            s for s in config_data["script_list"] if get_script_name(s) in enabled_keys
        ]
        invalid = self.service.collect_invalid_scripts(enabled_scripts)
        if invalid:
            details = "\n".join(f"· {name}：{msg}" for name, msg in invalid)
            reply = QMessageBox.warning(
                None,
                "脚本配置不合法",
                f"以下脚本配置不合法，运行时会被跳过：\n{details}\n\n是否仍然运行？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return False
        reply = QMessageBox.question(
            None,
            "确认运行",
            f"即将运行 {len(enabled_keys)} 个脚本，是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return reply == QMessageBox.Yes

    def _run_chain(self, config_data: dict, enabled_keys: set, label: str) -> None:
        """生成并运行脚本链（真实 ChainService）。"""
        ui_state = {name: dict(entry) for name, entry in self._ui_state.items()}
        chain_path = self.service.generate_chain(
            config_data, enabled_keys, chain_name="today", ui_state=ui_state
        )
        command, cwd, env = build_script_command(["--chain", chain_path])
        command[0] = command[0].replace("pythonw.exe", "python.exe")
        creationflags = subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
        subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            creationflags=creationflags,
        )
        self.toastRequested.emit(
            f"{label}：已生成并运行链 ({len(enabled_keys)} 个脚本)"
        )

    # ── 悬浮条 ─────────────────────────────────────────────────────────
    def _current_game(self) -> dict:
        return self._games[self.current_index]

    @Slot()
    def launchGame(self):
        """启动游戏：读取当前游戏 exe 路径并打开（未适配时提示）。"""
        game = self._current_game()
        exe_path = _get_game_exe_path(game["script_name"])
        if not exe_path:
            self.toastRequested.emit(f"{game['display_name']}：未找到游戏路径")
            return
        os.startfile(exe_path)  # noqa: S606 启动游戏
        self.toastRequested.emit(f"正在启动 {game['display_name']}…")

    def _open_url(self, url: str, fallback: str, label: str):
        target = url or fallback
        webbrowser.open(target)
        self.toastRequested.emit(f"打开{label}：{target}")

    @Slot()
    def openHome(self):
        """打开当前游戏官方主页（set_config 声明，空则通用占位）。"""
        self._open_url(
            _get_game_homepage(self._current_game()["script_name"]),
            _URL_HOME,
            "主页",
        )

    @Slot()
    def openBilibili(self):
        """打开当前游戏官方 B 站（set_config 声明，空则通用占位）。"""
        self._open_url(
            _get_game_bilibili(self._current_game()["script_name"]),
            _URL_BILIBILI,
            "B站",
        )

    @Slot()
    def openGithub(self):
        """打开当前脚本项目 GitHub 主页（set_config 声明，空则通用占位）。"""
        self._open_url(
            _get_game_github(self._current_game()["script_name"]),
            _URL_HOME,
            "GitHub",
        )

    @Slot()
    def openScriptFolder(self):
        """打开当前脚本所在目录（script_path 父目录，资源管理器）。"""
        game = self._current_game()
        script_path = game["script_data"].get("script_path", "")
        resolved = resolve_script_path(script_path) if script_path else None
        if not resolved:
            self.toastRequested.emit(f"{game['display_name']}：未找到脚本路径")
            return
        folder = os.path.dirname(resolved)
        if not os.path.isdir(folder):
            self.toastRequested.emit(f"{game['display_name']}：脚本目录不存在")
            return
        os.startfile(folder)  # noqa: S606 打开脚本所在目录
        self.toastRequested.emit(f"已打开 {game['display_name']} 脚本目录")

    @Slot()
    def openSettings(self):
        """打开总配置文件 config.yml（系统默认程序）；缺失时 toast 提示（对齐旧 GUI）。"""
        config_path = get_config_yml_path_under_root()
        if not os.path.isfile(config_path):
            self.toastRequested.emit("未找到 config/config.yml")
            return
        os.startfile(config_path)  # noqa: S606 打开总配置文件
        self.toastRequested.emit("已打开总配置文件 config.yml")

    @Slot()
    def openWallpaper(self):
        """更改当前脚本壁纸并持久化到 config/wallpaper.json（对齐旧 GUI）。"""
        from PySide6.QtWidgets import QFileDialog

        game = self._current_game()
        path, _ = QFileDialog.getOpenFileName(
            None,
            f"选择 {game['display_name']} 壁纸",
            "",
            "图片/视频 (*.png *.jpg *.jpeg *.webp *.bmp *.mp4 *.webm *.mkv *.mov)",
        )
        if not path:
            return
        wallpapers = self._wallpapers()
        wallpapers[game["script_name"]] = path
        self._save_wallpapers(wallpapers)
        self._apply_current()
        self.toastRequested.emit(f"已更换 {game['display_name']} 壁纸")

    def _save_wallpapers(self, wallpapers: dict):
        import json

        path = resolve_script_path("config/wallpaper.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(wallpapers, f, ensure_ascii=False, indent=2)

    # ── 背景 ─────────────────────────────────────────────────────────────
    @Property(str, notify=backgroundChanged)
    def backgroundMode(self) -> str:
        return self._bg_mode

    @Property(str, notify=backgroundChanged)
    def backgroundUrl(self) -> str:
        return self._bg_url

    @Property(str, notify=backgroundChanged)
    def gradientColor(self) -> str:
        return self._grad_color

    @Property(str, notify=backgroundChanged)
    def gradientChar(self) -> str:
        return self._grad_char

    def _apply_current(self):
        """按当前选中脚本刷新背景：自定义壁纸 → 脚本背景 → 渐变兜底。"""
        game = self._games[self.current_index]
        path = self._load_bg(game)
        if path and is_video(path) and os.path.isfile(path):
            self._bg_mode = "video"
            self._bg_url = QUrl.fromLocalFile(path).toString()
        elif path and os.path.isfile(path):
            self._bg_mode = "image"
            self._bg_url = QUrl.fromLocalFile(path).toString()
        else:
            self._bg_mode = "gradient"
            self._bg_url = ""
        self._grad_color = game["color"]
        self._grad_char = game["char"]
        self.backgroundChanged.emit()
        self._refresh_task_card()

    def _load_bg(self, game: dict) -> str | None:
        """返回该脚本应使用的背景路径（自定义壁纸 → 脚本背景 → DEFAULT_BG）。

        文件不存在返回 None（走渐变）；扩展名由调用方分发（视频/图片）。
        """
        custom = self._wallpapers().get(game["script_name"])
        bg_path = custom or (_get_game_bg_img(game["script_name"]) or DEFAULT_BG)
        resolved = resolve_script_path(bg_path)
        if not os.path.isfile(resolved):
            return None
        return resolved

    def _wallpapers(self) -> dict:
        """读取 config/wallpaper.json（脚本 → 壁纸路径）；缺失返回空。"""
        import json

        path = resolve_script_path("config/wallpaper.json")
        if not os.path.isfile(path):
            return {}
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    # ── 视频错误回退 ─────────────────────────────────────────────────────
    @Slot(str)
    def videoError(self, reason: str):
        """QML VideoOutput 媒体错误：回退渐变（QML 侧 MediaPlayer 触发）。"""
        import warnings

        warnings.warn(
            f"[qml] 视频背景不可用，回退：{reason or '媒体解码错误'}",
            RuntimeWarning,
            stacklevel=2,
        )
        self._bg_mode = "gradient"
        self._bg_url = ""
        self.backgroundChanged.emit()

    # ── 窗口控制 ─────────────────────────────────────────────────────────
    @Slot()
    def startWindowMove(self):
        """系统原生窗口拖动（Windows DWM 接管，最流畅）。

        QML 逐帧 move 会每帧重排场景图（2K 视频纹理重绘），导致拖动不跟手；
        系统接管后窗口表面由 DWM 搬移，不触发场景重绘，与普通窗口一致。
        """
        from PySide6.QtGui import QGuiApplication

        win = QGuiApplication.focusWindow()
        if win is not None:
            win.startSystemMove()

    @Slot()
    def minimize(self):
        app = self._app()
        if app is not None:
            app.focusWindow().showMinimized()

    @Slot()
    def closeWindow(self):
        app = self._app()
        if app is not None:
            app.quit()

    def _app(self):
        from PySide6.QtWidgets import QApplication

        return QApplication.instance()


# 供 context 共享的类型引用（QML 不直接实例化，仅为类型安全预留）
__all__ = ["QmlBridge", "ScriptIconProvider", "UiIconProvider"]
