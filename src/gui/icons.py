"""图标模块：自绘图标 widget/绘制函数 + 脚本 exe 图标获取。

- 自绘部分（2026-08-16 从 main_window.py 拆分）：``GlyphButton`` /
  ``IconButton`` 与悬浮条/窗口控制/左侧栏按钮的 ``draw_*`` 绘制函数。
- 脚本图标部分（2026-08-16 从 src/gui/icons.py 合并）：``get_script_icon``
  同步链——external 脚本用 exe 自带图标（崩铁优先同目录 March7th Launcher.exe），
  python 脚本用默认图标（Python 解释器图标，取不到回退 assets/ds.ico）。
  原 src/gui/icons.py 的后台异步加载机制（Win32 提取 + QThreadPool）已随旧 GUI
  删除：新 GUI 的 GameIcon 同步取图标，无需后台线程。

依赖单向：icons → theme / config.subscript / utils，main_window → icons。
"""

import logging
import os
import sys
from functools import lru_cache

from PySide6.QtCore import QFileInfo, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import QFileIconProvider, QWidget

from src.config.subscript import resolve_script_path
from src.gui.theme import C_BLUE_TEXT, C_BTN_DARK, C_WHITE
from src.utils import get_root_dir, safe_path_join

logger = logging.getLogger(__name__)


# ═══════════════════════ 自绘图标 widget ═══════════════════════════════════
class GlyphButton(QWidget):
    """自绘图标 widget：draw_fn 接受已经 translate 到中心的 QPainter。"""

    def __init__(self, draw_fn, parent=None):
        super().__init__(parent)
        self._draw_fn = draw_fn

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.translate(self.width() / 2, self.height() / 2)
        self._draw_fn(p)


class IconButton(QWidget):
    """36x36 深底圆角按钮，内容由 draw_fn 自绘（白色图形）。
    hover 时背景提亮，点击触发 clicked 信号。"""

    clicked = Signal()

    def __init__(self, draw_fn, parent=None, size=36, radius=12, bg=C_BTN_DARK):
        super().__init__(parent)
        self._draw_fn = draw_fn
        self._radius = radius
        self._bg = QColor(bg)
        self._hover = False
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            event.accept()
            self.clicked.emit()
        super().mousePressEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # 深底圆角（hover 提亮）
        bg = self._bg
        if self._hover:
            bg = bg.lighter(140)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(self.rect(), self._radius, self._radius)
        # 内容
        p.translate(self.width() / 2, self.height() / 2)
        self._draw_fn(p)


# ═══════════════════════ 悬浮条图标绘制函数（白色图形，24x24 视觉区）═══════
def draw_home(p: QPainter):
    p.setPen(QPen(QColor(C_WHITE), 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    p.drawLine(-10, -3, 0, -11)  # 屋顶左
    p.drawLine(0, -11, 10, -3)  # 屋顶右
    p.drawLine(-7, -1, -7, 9)  # 左墙
    p.drawLine(7, -1, 7, 9)  # 右墙
    p.drawLine(-7, 9, 7, 9)  # 地
    p.setBrush(QColor(C_WHITE))
    p.setPen(Qt.NoPen)
    p.drawRect(-2, 2, 4, 5)  # 门


def draw_controller(p: QPainter):
    p.setPen(Qt.NoPen)
    # 手柄主体：扁圆角矩形（窄于握把外缘，避免盖住握把像"脸"）
    p.setBrush(QColor(C_WHITE))
    p.drawRoundedRect(QRect(-9, -8, 18, 11), 4, 4)
    # 左/右握把：从主体两端向下伸出（下端露出主体下缘 3px，一眼是手柄）
    p.drawRoundedRect(QRect(-12, -4, 5, 10), 2.5, 2.5)
    p.drawRoundedRect(QRect(7, -4, 5, 10), 2.5, 2.5)
    # 十字键：主体左侧
    p.setBrush(QColor(C_BTN_DARK))
    p.drawRoundedRect(QRect(-5.5, -5.5, 2.4, 7), 1, 1)
    p.drawRoundedRect(QRect(-7.8, -3.2, 7, 2.4), 1, 1)
    # AB 按钮：主体右侧斜排（不再对称居中，避免像眼睛）
    p.drawEllipse(QRect(2, -4.5, 2.6, 2.6))
    p.drawEllipse(QRect(4.8, -1.5, 2.6, 2.6))


def draw_tv(p: QPainter):
    """B站 图标：小电视 logo（顶部天线 + 圆角机身 + 屏幕双眼）。"""
    pen = QPen(QColor(C_WHITE), 2.0, Qt.SolidLine, Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawLine(-6, -7, -8, -9)  # 左天线
    p.drawLine(6, -7, 8, -9)  # 右天线
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(C_WHITE))
    p.drawRoundedRect(QRect(-9, -7, 18, 14), 4, 4)  # 机身
    p.setBrush(QColor(C_BTN_DARK))
    p.drawEllipse(QRect(-5, -2, 3, 3))  # 左眼
    p.drawEllipse(QRect(2, -2, 3, 3))  # 右眼


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

_github_renderer = None


def draw_github(p: QPainter):
    """GitHub 图标（Octocat 单色，QSvgRenderer 缓存渲染）。"""
    global _github_renderer
    if _github_renderer is None:
        from PySide6.QtCore import QByteArray
        from PySide6.QtSvg import QSvgRenderer

        _github_renderer = QSvgRenderer(QByteArray(_GITHUB_SVG.encode()))
    _github_renderer.render(p, QRect(-10, -10, 20, 20))


def draw_wallpaper(p: QPainter):
    """壁纸图标：图片框（圆角矩形 + 太阳圆 + 山形）。"""
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(C_WHITE), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(-9, -8, 18, 16), 3, 3)  # 相框
    p.drawEllipse(QRectF(-5.5, -5.5, 3.4, 3.4))  # 太阳
    path = QPainterPath()  # 山
    path.moveTo(-7, 6)
    path.lineTo(-1.5, -1)
    path.lineTo(2, 3.5)
    path.lineTo(4.5, 1)
    path.lineTo(8, 6)
    p.drawPath(path)


_FOLDER_SVG = (
    '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" '
    'xmlns="http://www.w3.org/2000/svg">'
    '<path d="M3 7C3 5.89543 3.89543 5 5 5H9.58579C9.851 5 10.1054 5.10536 '
    "10.2929 5.29289L12 7H19C20.1046 7 21 7.89543 21 9V17C21 18.1046 "
    '20.1046 19 19 19H5C3.89543 19 3 18.1046 3 17V7Z" stroke="#FFFFFF" '
    'stroke-width="1.8" stroke-linejoin="round"/>'
    "</svg>"
)

_folder_renderer = None


def draw_folder(p: QPainter):
    """文件夹图标（打开脚本所在路径，线性描边，QSvgRenderer 缓存渲染）。"""
    global _folder_renderer
    if _folder_renderer is None:
        from PySide6.QtCore import QByteArray
        from PySide6.QtSvg import QSvgRenderer

        _folder_renderer = QSvgRenderer(QByteArray(_FOLDER_SVG.encode()))
    _folder_renderer.render(p, QRect(-10, -10, 20, 20))


# ═══════════════════════ 窗口控制图标 ══════════════════════════════════════
def draw_min(p: QPainter):
    p.setPen(QPen(QColor(C_WHITE), 2, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(-8, 0, 8, 0)


def draw_config(p: QPainter):
    """配置文件：白色齿轮（外齿 8 线 + 主体圆 + 内孔）。"""
    import math

    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(C_WHITE), 2, Qt.SolidLine, Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    for i in range(8):  # 外齿
        a = math.radians(i * 45)
        x1, y1 = 6.5 * math.cos(a), 6.5 * math.sin(a)
        x2, y2 = 9.5 * math.cos(a), 9.5 * math.sin(a)
        p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
    p.drawEllipse(QRectF(-6.5, -6.5, 13, 13))  # 主体圆
    p.drawEllipse(QRectF(-2.5, -2.5, 5, 5))  # 内孔


def draw_close(p: QPainter):
    p.setPen(QPen(QColor(C_WHITE), 2, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(-6, -6, 6, 6)
    p.drawLine(6, -6, -6, 6)


# ═══════════════════════ 左侧栏按钮图标 ════════════════════════════════════
def draw_grid(p: QPainter):
    """⊞ 工具网格（3x3 点阵，蓝色调）。

    圆点用"中心点定位"绘制：中心点 (i-1)*10, (j-1)*10，外接矩形左上角
    = 中心 - 半径 2.5。之前用 -10+i*10 当左上角导致整体偏右下 2.5px。"""
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(C_BLUE_TEXT))
    for i in range(3):
        for j in range(3):
            cx = (i - 1) * 10
            cy = (j - 1) * 10
            p.drawEllipse(QRect(cx - 2.5, cy - 2.5, 5, 5))


def draw_launch(p: QPainter):
    """启动全部：白色 ▶（黄色按钮上的图形）。"""
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#1A1A1A"))
    pts = QPolygonF([QPointF(-4, -8), QPointF(-4, 8), QPointF(8, 0)])
    p.drawPolygon(pts)


def draw_select_all(p: QPainter):
    """全选：白色对勾 √（绿色按钮上的图形）。"""
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(C_WHITE), 2.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    path = QPainterPath()
    path.moveTo(-6, 0)
    path.lineTo(-2, 5)
    path.lineTo(7, -6)
    p.drawPath(path)


def draw_deselect_all(p: QPainter):
    """清空：白色 ×（暗底按钮上的图形）。"""
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(C_WHITE), 2.5, Qt.SolidLine, Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawLine(-5, -5, 5, 5)
    p.drawLine(-5, 5, 5, -5)


def draw_add(p: QPainter):
    """添加脚本：白色 +（暗底按钮上的图形）。"""
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(C_WHITE), 2.5, Qt.SolidLine, Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawLine(-6, 0, 6, 0)
    p.drawLine(0, -6, 0, 6)


# ═══════════════════════ 脚本 exe 图标获取（2026-08-16 从 src/gui/icons.py 合并）═══
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
