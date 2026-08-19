"""脚本图标获取与 QML 通用 UI 矢量图标提供器。

提供脚本 exe 图标获取（``get_script_icon``）、GitHub SVG 常量（``_GITHUB_SVG``）
及 QML 矢量图标源 ``UiIconProvider``（``image://uiicon/<name>``）。
"""

import logging
import os
import sys
from functools import lru_cache

from PySide6.QtCore import QByteArray, QFileInfo, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtQuick import QQuickImageProvider
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QFileIconProvider

from src.config.subscript import resolve_script_path
from src.utils import get_root_dir, safe_path_join

logger = logging.getLogger(__name__)


# GitHub Octocat 单色 SVG（Simple Icons 路径，白色）
_GITHUB_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    '<path fill="#FFFFFF" d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 '
    "8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724"
    "-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744"
    ".084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 "
    "1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466"
    "-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 "
    "1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 "
    "2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 "
    "1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 "
    "2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 "
    '17.592 24 12.297c0-6.627-5.373-12-12-12"/>'
    "</svg>"
)


# 复用的文件图标提供器：避免每个 exe 都 new 一个 QFileIconProvider 的开销
_ICON_PROVIDER = QFileIconProvider()

# 默认图标：没有自带图标的脚本（如 python 脚本，或 external 但取不到 exe 图标的）使用。
# 优先用当前 Python 解释器（sys.executable）的 OS 文件图标，即 Python 官方图标；
# 极个别取不到时（如冻结后 sys.executable 指向自身 exe）回退到 assets/ds.ico。
_DEFAULT_ICON_PATH = safe_path_join(get_root_dir(), "assets", "ds.ico")
_DEFAULT_ICON: QIcon | None = None


def _default_icon() -> QIcon:
    """懒加载默认图标（缺自带图标时回退用）：优先 Python 解释器图标，否则 ds。"""
    global _DEFAULT_ICON
    if _DEFAULT_ICON is None:
        python_icon = _exe_icon(sys.executable)
        _DEFAULT_ICON = (
            python_icon if python_icon is not None else QIcon(_DEFAULT_ICON_PATH)
        )
    return _DEFAULT_ICON


@lru_cache
def _exe_icon(path: str) -> QIcon | None:
    """返回 exe 自带图标（OS 文件图标，即程序内嵌图标）。

    文件缺失 / 取不到时返回 None；异常也一并吞掉，不让列表渲染崩溃。
    """
    if not path or not os.path.isfile(path):
        return None
    try:
        icon = _ICON_PROVIDER.icon(QFileInfo(path))
    except Exception:  # noqa: BLE001  # 取图标失败不应影响整个列表
        logger.warning("取 %s 的图标失败", path, exc_info=True)
        return None
    return icon if (icon is not None and not icon.isNull()) else None


def get_icon_source(script_data: dict) -> str | None:
    """返回脚本图标所用的 exe 路径（崩铁优先同目录 March7th Launcher.exe）。"""
    if script_data.get("script_type") != "external":
        return None
    raw = script_data.get("script_path", "")
    if not raw:
        return None
    script_path = resolve_script_path(raw)
    launcher = os.path.join(os.path.dirname(script_path), "March7th Launcher.exe")
    if os.path.isfile(launcher):
        return launcher
    return script_path


def get_script_icon(script_data: dict) -> QIcon:
    """返回脚本在列表中显示的图标。

    - external 脚本（指向 exe）：优先使用 exe 内嵌的自带图标；
      取不到（文件缺失 / 无图标）时回退默认图标。
    - python 脚本及其他：使用默认图标。

    调用方（GameIcon）可缓存结果，本函数仅做轻量解析与缓存。
    """
    source = get_icon_source(script_data)
    if source:
        icon = _exe_icon(source)
        if icon is not None:
            return icon
    return _default_icon()


# UI 通用矢量图标：各 draw 方法把 painter translate 到画布中心，在 48x48 内绘制白图形。
_WHITE = QColor("#FFFFFF")
_CUT = QColor("#1F2937")  # 图标内部镂空色，透出按钮底色


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
        # Octocat 单色 logo，缩放至与其他图标一致的视觉尺寸（半径≈15）。
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
