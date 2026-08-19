"""QML 图像提供器与背景工具：脚本图标、UI 矢量图标、视频扩展名识别。

脚本图标经 `image://scripticon/<script_name>` 提供（按 script_name 缓存，避免
重排后图标不跟）；UI 矢量图标经 `image://uiicon/<name>` 提供（重绘版，旧
icons.draw_* 造型不佳且无法直接用于 QML）。两者均由 launcher 注册到 QML 引擎。
"""

import os

from PySide6.QtCore import QByteArray, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtQuick import QQuickImageProvider
from PySide6.QtSvg import QSvgRenderer

from src.gui.icons import _GITHUB_SVG, get_script_icon

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


__all__ = ["ScriptIconProvider", "UiIconProvider", "is_video", "VIDEO_EXTS"]
