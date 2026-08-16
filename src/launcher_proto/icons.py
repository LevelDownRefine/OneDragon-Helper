"""launcher_proto 图标绘制模块：自绘图标 widget 与全部 draw_* 绘制函数。

从 launcher_proto.py 按职责拆分而来（2026-08-16）：图标类（_GlyphButton /
IconButton）与图标绘制函数（悬浮条/窗口控制/左侧栏按钮图形）独立成模块，
主窗口只负责组装。依赖单向：icons → 无（Qt 标准库），launcher_proto → icons。

颜色常量自包含：不反向 import 主窗口常量（避免循环导入）；值与
launcher_proto.py 顶层常量同源，待后续抽 theme.py 时统一收敛。
"""

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import QWidget

# 图标绘制用色（与 launcher_proto.py 顶层常量同值；待 theme.py 抽取后合并）
C_WHITE = "#FFFFFF"
C_BTN_DARK = "#1F2937"  # 悬浮条/窗口控制深底
C_BLUE_TEXT = "#7DA8FF"  # 选中/文字高亮蓝


class _GlyphButton(QWidget):
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
