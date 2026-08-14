"""OneDragon-Helper 启动器式 GUI 原型（严格还原 Ardot 设计稿）。

画布：1280x720 (16:9) · 保留原画布 + 等比缩放
结构：
  左侧游戏栏(80x720) + HERO区(1200x720，官方 ZZZ 背景图 cover)
  右上：窗口控制（最小化/关闭）
  左下：专题卡（鸣潮·任务调度，日常/周本两行）
  右下：启动脚本蓝色大胶囊
  右侧：玻璃悬浮条（主页/启动游戏/B站/小红书/帮助）

修改记录：
  - 左侧栏改为 RailContainer，支持鼠标滚轮 + 拖动滚动（无 scrollbar）
  - ⊞ 用 _GlyphButton 自绘 3x3 点阵（替代 QLabel "≡"）
  - 小红书图标用官方红 #FF2442 + 白 R 字（draw_xhs）
  - paintEvent 加 SmoothPixmapTransform 抑制背景颗粒感
"""

import sys

from PySide6.QtCore import QPointF, QRect, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QLabel,
    QWidget,
)

# ═══════════════════════ 设计稿常量（Ardot 画布原值）═══════════════════════
CANVAS_W, CANVAS_H = 1280, 720

# 颜色（从画布 fills 换算 hex）
C_WINDOW_BG = "#0A0E1A"      # 主窗口底色
C_RAIL_BG = "#070A14"        # 左侧游戏栏
C_RAIL_DIV = "#0F1524"       # 游戏栏描边
C_BTN_DARK = "#1F2937"       # 悬浮条/窗口控制深底
C_YELLOW = "#F4C242"         # 启动全部 / 启动脚本主色
C_YELLOW_DEEP = "#3D2E00"    # 黄色胶囊内圆深底
C_BLUE = "#2196F3"           # 启动脚本蓝色大胶囊
C_BLUE_DEEP = "#0F2A4D"      # 蓝色胶囊内圆深底
C_WHITE = "#FFFFFF"
C_BLUE_TEXT = "#7DA8FF"      # 选中/文字高亮蓝
C_MUTED = "#8A9AB8"          # 次要文字
C_FAINT = "#4A5568"          # 停用文字
C_GREEN = "#3DD68C"          # 启用开关
C_GRAY_TRACK = "#2A2F38"     # 停用开关轨道
C_GRAY_KNOB = "#5A6470"      # 停用开关滑块
C_CARD_BG = "#0A1020"        # 专题卡玻璃底
C_ROW_DAILY = "#0E1A30"      # 日常行
C_ROW_WEEKLY = "#0E1420"     # 周本行
C_CHIP_BG = "#0F1A2E"        # 副本 chip
C_GAME_SELECT = "#2A4A8A"    # 鸣潮选中
C_GAME_DIM = "#161C28"       # 停用游戏图标
C_XHS_RED = "#FF2442"        # 小红书品牌红

BG_IMG = r"D:/game_helper/zzz_od/assets/ui/static_background.webp"

# 字体
FONT_FAMILY = "Microsoft YaHei"

# ── 左侧游戏栏数据：名称 / 底色 / 文字色 / 是否启用 ─────────────────────────
GAMES = [
    ("鸣", C_GAME_SELECT, C_WHITE, True, True),      # 鸣潮：选中+启用
    ("原", "#3A3A6A", "#C8C8E8", True, False),
    ("崩", "#2A4A7A", "#C8D0E8", True, False),
    ("粥", C_GAME_DIM, C_FAINT, False, False),
    ("绝", "#1E5A4A", "#B8E0C8", True, False),
    ("异", C_GAME_DIM, C_FAINT, False, False),
    ("终", C_GAME_DIM, C_FAINT, False, False),
]


def make_font(size: int, weight: int = 400) -> QFont:
    """统一像素字号 QFont（与 QSS px 渲染一致）。"""
    f = QFont(FONT_FAMILY)
    f.setPixelSize(size)
    f.setWeight(QFont.Weight(weight))
    return f


def rgba(hex_color: str, alpha: int) -> QColor:
    c = QColor(hex_color)
    c.setAlpha(alpha)
    return c


# ═══════════════════════ 自绘容器/按钮 ═════════════════════════════════════
class RailContainer(QWidget):
    """左侧游戏栏滚动容器：80x720，支持鼠标滚轮 + 拖动滚动（无 scrollbar）。

    所有可滚动元素放在 self._content 内；通过 _offset 调整 _content 位置实现滚动。
    self._fixed_bottom_h 为底部固定区高度（⊞ + 启动全部），固定元素直接放
    RailContainer 上（不随 content 滚动）；content 可视高度 = 720 - 固定区。
    """

    def __init__(self, parent=None, fixed_bottom_height: int = 0):
        super().__init__(parent)
        self._fixed_bottom_h = fixed_bottom_height
        self.setFixedSize(80, CANVAS_H)
        self.setStyleSheet(f"background:{C_RAIL_BG}; border-right:1px solid {C_RAIL_DIV};")
        self._content = QWidget(self)
        self._content.setFixedSize(80, CANVAS_H - fixed_bottom_height)
        self._content.move(0, 0)
        self._content.setStyleSheet(f"background:{C_RAIL_BG};")
        self._content.show()
        self._offset = 0
        self._max_offset = 0
        self._drag_pos = None

    def content(self) -> QWidget:
        return self._content

    def add(self, item: QWidget, x: int, y: int):
        """把 item 加入 content，x/y 为 content 内坐标。"""
        item.setParent(self._content)
        item.move(x, y)
        item.show()
        self._recompute_height()

    def _recompute_height(self):
        max_bottom = 0
        for child in self._content.findChildren(QWidget):
            if child.parent() is self._content and not child.isHidden():
                bottom = child.y() + child.height()
                if bottom > max_bottom:
                    max_bottom = bottom
        vis_h = self.height() - self._fixed_bottom_h
        content_h = max(vis_h, max_bottom + 16)
        self._content.setFixedSize(80, content_h)
        self._max_offset = max(0, content_h - vis_h)
        self._offset = min(self._offset, self._max_offset)
        self._apply_offset()

    def _apply_offset(self):
        self._content.move(0, -self._offset)

    def wheelEvent(self, event):
        delta = event.angleDelta().y() // 8  # 一咔嗒 15px
        if delta == 0:
            return
        self._offset = max(0, min(self._max_offset, self._offset + delta))
        self._apply_offset()
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.position().y()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            dy = self._drag_pos - event.position().y()
            self._offset = max(0, min(self._max_offset, self._offset + dy))
            self._apply_offset()
            self._drag_pos = event.position().y()
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None


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


# ═══════════════════════ 自绘图标按钮（悬浮条/窗口控制共用）════════════════
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


# 悬浮条图标绘制函数（白色图形，24x24 视觉区）
def draw_home(p: QPainter):
    p.setPen(QPen(QColor(C_WHITE), 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    p.drawLine(-10, -3, 0, -11)   # 屋顶左
    p.drawLine(0, -11, 10, -3)    # 屋顶右
    p.drawLine(-7, -1, -7, 9)     # 左墙
    p.drawLine(7, -1, 7, 9)       # 右墙
    p.drawLine(-7, 9, 7, 9)       # 地
    p.setBrush(QColor(C_WHITE))
    p.setPen(Qt.NoPen)
    p.drawRect(-2, 2, 4, 5)       # 门


def draw_controller(p: QPainter):
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(C_WHITE))
    # 手柄主体
    body = QPainterPath()
    body.addRoundedRect(QRect(-11, -7, 22, 15), 5, 5)
    p.drawPath(body)
    # 左握把 + 右握把
    p.setBrush(QColor(C_WHITE))
    p.drawRoundedRect(QRect(-11, -2, 4, 9), 2, 2)
    p.drawRoundedRect(QRect(7, -2, 4, 9), 2, 2)
    # 十字键
    p.setBrush(QColor(C_BTN_DARK))
    p.drawRoundedRect(QRect(-4, -4, 2.4, 6), 1, 1)
    p.drawRoundedRect(QRect(-6.5, -1.2, 7, 2.4), 1, 1)
    # AB 按钮
    p.drawEllipse(QRect(3, -4, 2.6, 2.6))
    p.drawEllipse(QRect(6.5, -2, 2.6, 2.6))


def draw_tv(p: QPainter):
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(C_WHITE))
    p.drawRoundedRect(QRect(-9, -8, 18, 12), 3, 3)
    p.setBrush(QColor(C_BTN_DARK))
    p.drawEllipse(QRect(-3, -4, 2, 2))
    p.drawEllipse(QRect(1, -4, 2, 2))
    p.setBrush(QColor(C_WHITE))
    p.drawRoundedRect(QRect(-2, 4, 4, 2), 1, 1)
    p.drawEllipse(QRect(-5, 6, 2, 2))
    p.drawEllipse(QRect(3, 6, 2, 2))


def draw_xhs(p: QPainter):
    """小红书：红色圆角方块 + 白色 R 字（保留品牌识别，风格与悬浮条统一）。"""
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(C_XHS_RED))
    p.drawRoundedRect(QRect(-14, -14, 28, 28), 7, 7)  # 28×28 红芯，居中
    p.setPen(QPen(QColor(C_WHITE), 2.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    # R：竖线 + 上半圆 + 右下斜（粗描边以保证识别度）
    p.drawLine(-3, -8, -3, 8)
    p.drawArc(QRect(-3, -8, 8, 8), 90 * 16, 180 * 16)
    p.drawLine(-3, -3, 5, 8)


# GitHub Octocat 单色 SVG（Simple Icons 路径，白色）
_GITHUB_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    '<path fill="#FFFFFF" d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 '
    '8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724'
    '-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744'
    '.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 '
    '1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466'
    '-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 '
    '1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 '
    '2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 '
    '1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 '
    '2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 '
    '17.592 24 12.297c0-6.627-5.373-12-12-12"/>'
    '</svg>'
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


def draw_min(p: QPainter):
    p.setPen(QPen(QColor(C_WHITE), 2, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(-8, 0, 8, 0)


def draw_close(p: QPainter):
    p.setPen(QPen(QColor(C_WHITE), 2, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(-6, -6, 6, 6)
    p.drawLine(6, -6, -6, 6)


def draw_play(p: QPainter):
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(C_WHITE))
    pts = QPolygonF([QPointF(-4, -8), QPointF(-4, 8), QPointF(8, 0)])
    p.drawPolygon(pts)


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


# ═══════════════════════ 开关（Toggle）══════════════════════════════════════
class Toggle(QWidget):
    """滑动开关：点击切换 on/off，触发 toggled 信号。"""

    toggled = Signal(bool)

    def __init__(self, on: bool, parent=None):
        super().__init__(parent)
        self._on = on
        self.setFixedSize(40, 22)
        self.setCursor(Qt.PointingHandCursor)

    def is_on(self) -> bool:
        return self._on

    def set_on(self, on: bool):
        if self._on != on:
            self._on = on
            self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            event.accept()
            self._on = not self._on
            self.update()
            self.toggled.emit(self._on)
        super().mousePressEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        track = QColor(C_GREEN) if self._on else QColor(C_GRAY_TRACK)
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(self.rect(), 11, 11)
        # 滑块
        knob = QColor(C_WHITE) if self._on else QColor(C_GRAY_KNOB)
        p.setBrush(knob)
        x = 20 if self._on else 2
        p.drawEllipse(QRect(x, 2, 18, 18))


# ═══════════════════════ 游戏图标（左侧栏）══════════════════════════════════
class GameIcon(QWidget):
    """游戏图标按钮：点击切换选中态（浏览模式）。"""

    clicked = Signal(int)

    def __init__(self, index, char, bg, fg, enabled, selected=False, parent=None):
        super().__init__(parent)
        self._index = index
        self._char, self._bg, self._fg = char, QColor(bg), QColor(fg)
        self._enabled, self._selected = enabled, selected
        self.setFixedSize(56, 56)
        self.setCursor(Qt.PointingHandCursor)

    def set_selected(self, selected: bool):
        self._selected = selected
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            event.accept()
            self.clicked.emit(self._index)
        super().mousePressEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(self._bg)
        p.drawRoundedRect(self.rect(), 14, 14)
        # 选中光晕
        if self._selected:
            glow = QColor("#4070FF")
            glow.setAlpha(90)
            p.setBrush(glow)
            p.drawRoundedRect(self.rect().adjusted(-3, -3, 3, 3), 16, 16)
        p.setFont(make_font(24, 700))
        p.setPen(self._fg)
        p.drawText(self.rect(), Qt.AlignCenter, self._char)


# ═══════════════════════ 主窗口 ════════════════════════════════════════════
class LauncherWindow(QWidget):
    def __init__(self):
        super().__init__()
        # 无系统标题栏（画布无顶部栏，窗口控制自绘在右上角）；按住空白处可拖动窗口
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setFixedSize(CANVAS_W, CANVAS_H)
        self.setWindowTitle("OneDragon-Helper · 游戏自动化调度器")
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self._drag_offset = None
        self._bg = QPixmap(BG_IMG)
        if self._bg.isNull():
            self._bg = QPixmap(1200, 720)
            self._bg.fill(C_WINDOW_BG)
        self._build_ui()

    # ── 无边框窗口拖动（按住空白处移动窗口）─────────────────────────────
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    # ── UI 构建 ──────────────────────────────────────────────────────────
    def _build_ui(self):
        self._build_left_rail()
        self._build_hero()
        self._build_task_card()
        self._build_launch_button()
        self._build_float_bar()
        self._build_window_controls()

    def _build_left_rail(self):
        """左侧游戏栏：游戏图标可滚动；⊞ 与启动全部固定在底部（画布 3:33/3:151）。"""
        # 底部固定区 = 分割线 1 + 8 + ⊞ 56 + 8 + 启动全部 56 + 8 = 137
        self.rail = RailContainer(self, fixed_bottom_height=137)
        self.rail.move(0, 0)
        content = self.rail.content()

        # 7 个游戏图标（滚动区，y: 16..448，stride 72，最后底部 504）
        self.game_icons = []
        for i, (char, bg, fg, enabled, selected) in enumerate(GAMES):
            icon = GameIcon(i, char, bg, fg, enabled, selected, content)
            icon.move(12, 16 + i * 72)
            icon.clicked.connect(self._select_game)
            icon.show()
            self.game_icons.append(icon)

        # 分割线（⊞ 上方 8px，与画布 10:5 一致；y=584，⊞ y=592）
        divider = QFrame(self.rail)
        divider.setGeometry(12, 584, 56, 1)
        divider.setStyleSheet("background:#2A3850;")

        # ⊞ 工具网格（固定：y=592；56×56）
        grid_frame = QFrame(self.rail)
        grid_frame.setGeometry(12, 592, 56, 56)
        grid_frame.setStyleSheet(
            "background:transparent; border:1px solid #4D6A8C; border-radius:14px;"
        )
        grid_glyph = _GlyphButton(draw_grid, grid_frame)
        grid_glyph.setGeometry(0, 0, 56, 56)
        grid_glyph.show()

        # 启动全部按钮（固定最底部：y=656；56×56；rail 80 居中 x=12）
        launch_btn = QFrame(self.rail)
        launch_btn.setGeometry(12, 656, 56, 56)
        launch_btn.setStyleSheet(f"background:{C_YELLOW}; border-radius:14px;")
        launch_btn.setCursor(Qt.PointingHandCursor)
        launch_glyph = _GlyphButton(draw_launch, launch_btn)
        launch_glyph.setGeometry(0, 0, 56, 56)
        launch_glyph.show()

        # 点击事件（accept 防止冒泡触发 RailContainer 拖动）
        def _on_launch_press(e):
            if e.button() == Qt.LeftButton:
                e.accept()
                self._launch_all()

        launch_btn.mousePressEvent = _on_launch_press

    def _build_hero(self):
        """HERO 区：1200x720 官方背景图（cover）。"""
        self.hero = QWidget(self)
        self.hero.setGeometry(80, 0, 1200, CANVAS_H)

    def _build_task_card(self):
        """专题卡（左下 x:48 y:428 w:480 h:268，玻璃半透明）。"""
        card = QFrame(self.hero)
        card.setGeometry(48, 428, 480, 268)
        # 玻璃感：半透明
        card.setStyleSheet("background:rgba(10,16,32,0.78); border-radius:16px;")
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 130))
        card.setGraphicsEffect(shadow)
        card.show()

        # 标题行（ico 36×36 与任务行 ico 对齐：x=12；文字 x=58 与行名对齐）
        title_row = QWidget(card)
        title_row.setGeometry(20, 18, 440, 36)
        t_ico = QLabel("▶", title_row)
        t_ico.setGeometry(12, 0, 36, 36)
        t_ico.setStyleSheet(
            f"background:{C_YELLOW}; color:#1A1A1A; font-size:16px;"
            "border-radius:10px; qproperty-alignment:AlignCenter;"
        )
        t_txt = QLabel("鸣潮 · 任务调度", title_row)
        t_txt.setGeometry(58, 5, 260, 26)
        t_txt.setStyleSheet(f"color:{C_WHITE}; font-size:19px; font-weight:700; background:transparent;")

        # 分隔线
        divider = QFrame(card)
        divider.setGeometry(20, 56, 440, 1)
        divider.setStyleSheet("background:#2A3850;")

        # 日常行（启用）
        self.daily_row = self._task_row(
            card, 20, 68, "日常", C_ROW_DAILY, "#0F1A2E",
            C_BLUE_TEXT, "⚡", "#1A3A7A", C_BLUE_TEXT, "无音区", True
        )
        # 周本行（未支持，opacity 0.55）
        self.weekly_row = self._task_row(
            card, 20, 134, "周本", C_ROW_WEEKLY, "#1A2028",
            C_FAINT, "📅", "#2A3040", C_FAINT, "未支持", False
        )

    def _task_row(self, card, x, y, name, row_bg, chip_bg, name_fg,
                  ico_char, ico_bg, chip_fg, chip_text, on):
        """专题卡内任务行（56 高，图标+名称+chip+开关；画布已去行描边）。"""
        row = QFrame(card)
        row.setGeometry(x, y, 440, 56)
        row.setStyleSheet(f"background:{row_bg}; border-radius:12px;")
        if not on:
            row.setStyleSheet(f"background:{row_bg}; border-radius:12px;")
        row.setWindowOpacity(0.55 if not on else 1.0)
        row.show()

        ico = QLabel(ico_char, row)
        ico.setGeometry(12, 10, 36, 36)
        ico.setStyleSheet(
            f"background:{ico_bg}; color:{chip_fg}; font-size:16px;"
            "border-radius:10px; qproperty-alignment:AlignCenter;"
        )

        name_lbl = QLabel(name, row)
        name_lbl.setGeometry(58, 15, 60, 26)
        name_lbl.setStyleSheet(f"color:{name_fg}; font-size:15px; font-weight:600; background:transparent;")

        chip = QFrame(row)
        chip.setGeometry(130, 15, 96, 26)
        chip.setStyleSheet(
            f"background:{chip_bg}; border-radius:13px; border:1px solid #33517A;"
        )
        chip_lbl = QLabel(chip_text, chip)
        chip_lbl.setStyleSheet(f"color:{chip_fg}; font-size:11px; background:transparent;")
        chip_lbl.setGeometry(0, 0, 96, 26)
        chip_lbl.setAlignment(Qt.AlignCenter)

        toggle = Toggle(on, row)
        toggle.move(388, 17)
        toggle.toggled.connect(lambda v, r=row, t=toggle: self._on_task_toggled(r, t, v))
        return row

    def _on_task_toggled(self, row, toggle, on):
        """任务行开关切换：启用→整行高亮；停用→整行置灰。"""
        row.setWindowOpacity(1.0 if on else 0.55)
        # 背景色在启用/停用间切换
        base = C_ROW_DAILY if on else C_ROW_WEEKLY
        row.setStyleSheet(f"background:{base}; border-radius:12px;")

    def _build_launch_button(self):
        """启动脚本：右下蓝色大胶囊（x:960 y:636 w:216 h:64）——可点击。

        内部布局：▶ 圆 56×56 占满高度 + 文字居中 + ☰ 圆 56×56 对称。
        文字 x=60 宽 96，中心 108 = (60+156)/2，正好在 ▶ 和 ☰ 的几何中点。"""
        btn = QFrame(self.hero)
        btn.setGeometry(960, 636, 216, 64)
        btn.setStyleSheet(f"background:{C_BLUE}; border-radius:32px;")
        btn.setCursor(Qt.PointingHandCursor)
        shadow = QGraphicsDropShadowEffect(btn)
        shadow.setBlurRadius(20)
        shadow.setOffset(0, 0)
        shadow.setColor(rgba("#2196F3", 110))
        btn.setGraphicsEffect(shadow)
        btn.show()

        # 左侧 ▶ 圆（56×56，占满按钮高度仅留 4 padding）
        play = QFrame(btn)
        play.setGeometry(4, 4, 56, 56)
        play.setStyleSheet(f"background:{C_BLUE_DEEP}; border-radius:28px;")
        play_ico = QLabel("▶", play)
        play_ico.setStyleSheet(f"color:{C_WHITE}; font-size:22px; font-weight:700; background:transparent;")
        play_ico.setGeometry(0, 0, 56, 56)
        play_ico.setAlignment(Qt.AlignCenter)

        # 中间文字"启动脚本"居中于 [60, 156] 几何中点 108
        txt = QLabel("启动脚本", btn)
        txt.setGeometry(60, 0, 96, 64)
        txt.setStyleSheet(f"color:{C_WHITE}; font-size:18px; font-weight:700; background:transparent;")
        txt.setAlignment(Qt.AlignCenter)

        # 右侧 ☰ 菜单圆（与 ▶ 对称，56×56）
        menu = QFrame(btn)
        menu.setGeometry(156, 4, 56, 56)
        menu.setStyleSheet(f"background:{C_BLUE_DEEP}; border-radius:28px;")
        menu_ico = QLabel("≡", menu)
        menu_ico.setStyleSheet(f"color:{C_WHITE}; font-size:22px; background:transparent;")
        menu_ico.setGeometry(0, 0, 56, 56)
        menu_ico.setAlignment(Qt.AlignCenter)

        btn.mousePressEvent = lambda e: (
            self._launch_script() if e.button() == Qt.LeftButton else None
        )

    def _build_float_bar(self):
        """右侧悬浮条（5 个图标，无背景框——画布 3:287 已去玻璃底）。"""
        bar = QFrame(self.hero)
        bar.setGeometry(1140, 80, 60, 280)
        # 去掉玻璃底：图标按钮自身有深色底，直接悬浮在 hero 上
        bar.setStyleSheet("background:transparent;")
        bar.show()

        icons = [
            (draw_home, "主页", lambda: self._toast("主页")),
            (draw_controller, "启动游戏", lambda: self._toast("启动游戏")),
            (draw_tv, "B站", lambda: self._toast("B站")),
            (draw_xhs, "小红书", lambda: self._toast("小红书")),
            (draw_github, "GitHub", lambda: self._toast("GitHub")),
        ]
        y = 22
        for fn, _name, action in icons:
            btn = IconButton(fn, bar, size=36, radius=12)
            btn.move(12, y)
            btn.clicked.connect(action)
            y += 48  # 36 + 12 gap

    def _build_window_controls(self):
        """窗口控制（右上角，深底圆按钮）。"""
        min_btn = IconButton(draw_min, self.hero, size=36, radius=18)
        min_btn.move(1116, 8)
        min_btn.clicked.connect(self.showMinimized)
        close_btn = IconButton(draw_close, self.hero, size=36, radius=18)
        close_btn.move(1156, 8)
        close_btn.clicked.connect(self.close)

    # ── 交互 ─────────────────────────────────────────────────────────────
    def _select_game(self, index: int):
        """点击左侧游戏图标：切换当前浏览的游戏（仅选中态变化，位置不变）。"""
        for i, icon in enumerate(self.game_icons):
            icon.set_selected(i == index)
        name = GAMES[index][0]
        self._toast(f"已切换到 {name}")

    def _launch_all(self):
        """启动全部：启动所有已启用（开关开启）的任务行。"""
        enabled = [n for n, row in (("日常", self.daily_row), ("周本", self.weekly_row))
                   if row.findChild(Toggle).is_on()]
        self._toast(f"启动全部：{'、'.join(enabled) if enabled else '无已启用任务'}")

    def _launch_script(self):
        """启动脚本：启动当前游戏（鸣潮）的已启用任务。"""
        enabled = [n for n, row in (("日常", self.daily_row), ("周本", self.weekly_row))
                   if row.findChild(Toggle).is_on()]
        self._toast(f"启动脚本（鸣潮）：{'、'.join(enabled) if enabled else '无已启用任务'}")

    def _toast(self, text: str):
        """右下角 toast 提示（简单实现：标题栏显示 3 秒）。"""
        self.setWindowTitle(f"OneDragon-Helper · {text}")
        from PySide6.QtCore import QTimer
        QTimer.singleShot(3000, lambda: self.setWindowTitle("OneDragon-Helper · 游戏自动化调度器"))

    # ── 背景绘制（cover）──────────────────────────────────────────────────
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)  # 平滑缩放背景图，抑制颗粒感
        # 画布底
        p.fillRect(self.rect(), QColor(C_WINDOW_BG))
        # hero 背景图（cover 填满 1200x720，保持 16:9 无裁切）
        target = QRect(80, 0, 1200, CANVAS_H)
        if not self._bg.isNull():
            # 计算 cover 源区域：图片与目标同比例(16:9)，直接全图适配
            src = QRect(0, 0, self._bg.width(), self._bg.height())
            p.drawPixmap(target, self._bg, src)


def main():
    app = QApplication(sys.argv)
    # 全局默认字体：QLabel 的 QSS 只设 font-size 未设 font-family，中文字符会 fallback
    # 到宋体(SimSun)；显式设置应用默认字体为微软雅黑后 QSS 文字统一用它
    app.setFont(QFont(FONT_FAMILY))
    win = LauncherWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
