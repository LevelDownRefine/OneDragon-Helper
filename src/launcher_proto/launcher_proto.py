"""OneDragon-Helper 启动器式 GUI（接入真实 ChainService 数据）。

画布：1280x720 (16:9) · 无系统标题栏（frameless，按住空白处可拖动窗口）
运行：项目根下 `python -m src.launcher_proto.launcher_proto`（模块方式，
  项目根在 sys.path，直接 import src.*）。
数据源：ChainService.load_config() 的 script_list（左侧栏 = 全部脚本，含 python
  辅助脚本）；set_config._CONFIGS 决定该脚本是否有「任务卡」适配；
  get_game_exe_path() 供「打开游戏」。背景图经 set_config.get_game_bg_img()
  获取（ScriptConfig.bg_img 相对脚本根目录声明，接口解析为绝对路径并校验存在）；
  B站链接经 set_config.get_game_bilibili() 获取（ScriptConfig.bilibili 声明，
  各游戏官方 B 站空间）；GitHub 链接经 set_config.get_game_github() 获取
  （ScriptConfig.github 声明，各脚本项目主页）；未配置的走通用占位链接。
结构：
  左侧游戏栏(80x720，脚本图标 + ⊞ + 启动全部整体可滚轮/拖动滚动)
   + HERO区(1280x720，按选中游戏画背景：官方图或渐变占位)
  右上：窗口控制（最小化/关闭）
  左下：专题卡（选中游戏的任务调度，日常/周本两行；未适配游戏隐藏）
  右下：启动脚本蓝色大胶囊（单脚本直跑；右侧 ☰ 弹配置）
  右侧：悬浮图标条（主页/启动游戏/文件夹/B站/GitHub，无背景框）
"""

import json
import os
import subprocess
import webbrowser

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QMimeData,
    QPointF,
    QRect,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QDrag,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QLabel,
    QMenu,
    QMessageBox,
    QWidget,
)

from src.config.dungeon_config import get_display_name, parse_dungeon_config
from src.config.set_config import _CONFIGS, ScriptConfig
from src.config.set_config import get_game_bg_img as _get_game_bg_img
from src.config.set_config import get_game_bilibili as _get_game_bilibili
from src.config.set_config import get_game_exe_path as _get_game_exe_path
from src.config.set_config import get_game_github as _get_game_github
from src.config.set_config import get_game_homepage as _get_game_homepage
from src.config.set_config import supports_weekly as _supports_weekly
from src.config.subscript import get_script_name, resolve_script_path
from src.gui.dialogs import SingleScriptConfigDialog, confirm_config_update
from src.gui.icons import get_script_icon
from src.service.chain_service import ChainService
from src.utils import get_config_yml_path_under_root
from src.utils_runner import build_script_command
from src.utils_weekly import get_week_num, is_weekly_start_reached

# ═══════════════════════ 设计稿常量（Ardot 画布原值）═══════════════════════
CANVAS_W, CANVAS_H = 1280, 720

# 颜色（从画布 fills 换算 hex）
C_WINDOW_BG = "#0A0E1A"  # 主窗口底色
C_BTN_DARK = "#1F2937"  # 悬浮条/窗口控制深底
C_YELLOW = "#F4C242"  # 启动全部 / 启动脚本主色
C_BLUE = "#2196F3"  # 启动脚本蓝色大胶囊
C_BLUE_DEEP = "#0F2A4D"  # 蓝色胶囊内圆深底
C_WHITE = "#FFFFFF"
C_BLUE_TEXT = "#7DA8FF"  # 选中/文字高亮蓝
C_MUTED = "#8A9AB8"  # 次要文字

# 拖拽重排 MIME（脚本唯一标识 script_name；与旧 GUI src/gui/widgets.py 一致）
DRAG_MIME = "application/x-onedragon-script"
C_FAINT = "#4A5568"  # 停用文字
C_GREEN = "#3DD68C"  # 启用开关
C_GRAY_TRACK = "#2A2F38"  # 停用开关轨道
C_GRAY_KNOB = "#5A6470"  # 停用开关滑块
C_GAME_DIM = "#161C28"  # 停用游戏图标

# 字体
FONT_FAMILY = "Microsoft YaHei"

# 兜底背景：脚本未配置背景图时使用（相对项目根）
DEFAULT_BG = "assets/ds.jpg"

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

# ── 游戏元数据（display_name → 图标底色 / 背景主色 / 链接）───────────────
# 通用占位链接（对应内容未配置时使用）
_URL_HOME = "https://github.com/"
_URL_BILIBILI = "https://www.bilibili.com/"


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
        # 背景由 paintEvent 自绘（不依赖样式表 WA_StyledBackground），
        # 保证 content 透明后栏背景稳定；背景图铺满全画布透出。
        self._content = QWidget(self)
        self._content.setFixedSize(80, CANVAS_H - fixed_bottom_height)
        self._content.move(0, 0)
        # content 透明：背景由 RailContainer 固定提供，过滚时图标在固定背景上滑动
        self._content.setStyleSheet("background:transparent;")
        self._content.setAttribute(Qt.WA_NoSystemBackground, True)
        self._content.show()
        self._offset = 0
        self._max_offset = 0
        self._drag_pos = None
        # 平滑滚动动画（滚轮）：从当前 offset 缓动到目标
        self._anim = QVariantAnimation(self)
        self._anim.valueChanged.connect(self._on_anim_value)
        self._anim.finished.connect(self._snap_back)
        # 拖动惯性：松手后按末速度减速滑行（16ms 逐帧，速度 ×0.95）
        self._fling_velocity = 0.0
        self._fling_timer = QTimer(self)
        self._fling_timer.setInterval(16)
        self._fling_timer.timeout.connect(self._fling_step)
        self._last_pos = None
        self._last_time = 0

    def _clamp_soft(self, value: int) -> int:
        """软钳制：边界内原值；超出部分压缩为 1/3（过滚手感，回弹由 _snap_back 负责）。"""
        if value < 0:
            return value // 3
        if value > self._max_offset:
            return self._max_offset + (value - self._max_offset) // 3
        return value

    def _snap_back(self):
        """过滚回弹：offset 在边界外时动画回到边界（到达边界即返回）。"""
        if 0 <= self._offset <= self._max_offset:
            return
        target = max(0, min(self._max_offset, self._offset))
        self._anim.stop()
        self._anim.setStartValue(self._offset)
        self._anim.setEndValue(target)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.start()

    def content(self) -> QWidget:
        return self._content

    def paintEvent(self, event):
        """自绘半透明栏背景 + 右边框（不依赖样式表，content 透明时背景稳定）。"""
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(7, 10, 20, 184))  # rgba(7,10,20,0.72)
        p.fillRect(
            QRect(self.width() - 1, 0, 1, self.height()),
            QColor(15, 21, 36, 204),  # rgba(15,21,36,0.8) 右边框
        )

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

    # ── 平滑滚动（滚轮/触控板）─────────────────────────────────────────
    def wheelEvent(self, event):
        pixel = event.pixelDelta().y()  # 触控板像素滚动
        delta = (
            pixel if pixel != 0 else (event.angleDelta().y() // 8) * 4
        )  # 每咔嗒 60px
        if delta == 0:
            return
        base = self._current_scroll()
        self._animate_to(base - delta)  # 方向取反：滚轮向上 → 内容上移
        event.accept()

    def _current_scroll(self) -> int:
        """当前滚动基准：动画进行中取动画目标值（连续滚动累加），否则取 _offset。"""
        if self._anim.state() == QAbstractAnimation.State.Running:
            return int(self._anim.endValue())
        return self._offset

    def _animate_to(self, target: int):
        """缓动到目标 offset（滚轮使用）；超出边界时软钳制（过滚，回弹由 _snap_back 负责）。

        动画进行中再滚动时以动画当前值为基准，避免重置回旧 offset。
        """
        base = self._current_scroll()
        target = self._clamp_soft(target)
        if target == base:
            return
        self._anim.stop()
        self._anim.setStartValue(base)
        self._anim.setEndValue(target)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.start()

    def _on_anim_value(self, value):
        self._offset = int(value)
        self._apply_offset()

    # ── 拖动滚动 + 惯性滑行 ────────────────────────────────────────────
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._anim.stop()
            self._fling_timer.stop()
            self._drag_pos = event.position().y()
            self._last_pos = event.position().y()
            self._last_time = event.timestamp()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            now = event.timestamp()
            dy = self._drag_pos - event.position().y()
            self._offset = int(self._clamp_soft(self._offset + dy))
            self._apply_offset()
            dt = now - self._last_time
            if dt > 0:
                self._fling_velocity = dy / dt  # px/ms 末速度
            self._drag_pos = event.position().y()
            self._last_time = now
            event.accept()

    def mouseReleaseEvent(self, event):
        if self._drag_pos is not None:
            self._drag_pos = None
            if abs(self._fling_velocity) > 0.4:  # 速度阈值，开启惯性滑行
                self._fling_timer.start()
            else:
                self._snap_back()  # 无惯性时若划过边界则回弹

    def _fling_step(self):
        self._offset = int(self._clamp_soft(self._offset + self._fling_velocity * 16))
        self._apply_offset()
        self._fling_velocity *= 0.95
        # 触底或速度过低停止
        hit_edge = (self._offset <= 0 and self._fling_velocity < 0) or (
            self._offset >= self._max_offset and self._fling_velocity > 0
        )
        if hit_edge or abs(self._fling_velocity) < 0.05:
            self._fling_timer.stop()
            self._snap_back()


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


# ═══════════════════════ 脚本图标（左侧栏）══════════════════════════════════
class GameIcon(QWidget):
    """脚本图标按钮：显示脚本真实图标（get_script_icon），点击切换选中态。
    支持拖拽重排（DRAG_MIME 传 script_name；对齐旧 GUI ScriptItem）。"""

    clicked = Signal(int)
    dropped = Signal(str, str)  # (源 script_name, 目标 script_name)

    def __init__(
        self, index, script_name, script_data, selected=False, enabled=True, parent=None
    ):
        super().__init__(parent)
        self._index = index
        self._script_name = script_name
        self._icon = get_script_icon(script_data)
        self._selected = selected
        self._enabled = enabled  # 纯内存态：默认全开，会话内可临时关（对齐旧 GUI）
        self._drag_start_pos = None
        # 56×56（含 4px 内边距）：图标 48 居中画在 (4,4)，选中白框画在 56 边界
        # ——与画布 3:15（56 容器）3:16（白框）3:17（48 图标）结构一致
        self.setFixedSize(56, 56)
        self.setCursor(Qt.PointingHandCursor)
        self.setAcceptDrops(True)

    def set_selected(self, selected: bool):
        self._selected = selected
        self.update()

    def set_enabled(self, enabled: bool):
        """启用/停用切换（控制模式下点击图标）：停用图标盖半透明黑。"""
        self._enabled = enabled
        self.update()

    def is_enabled(self) -> bool:
        """当前是否启用（纯内存态，默认全开）。"""
        return self._enabled

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            event.accept()
            self._drag_start_pos = (
                event.position().toPoint()
            )  # 记录拖拽起点（超过阈值才发起拖拽）
            self.clicked.emit(self._index)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_start_pos is not None and (event.buttons() & Qt.LeftButton):
            if (
                event.position().toPoint() - self._drag_start_pos
            ).manhattanLength() >= QApplication.startDragDistance():
                self._drag_start_pos = None
                self._start_drag()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_start_pos = None
        super().mouseReleaseEvent(event)

    def _start_drag(self):
        mime = QMimeData()
        mime.setText(self._script_name)
        mime.setData(DRAG_MIME, self._script_name.encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(self.grab())
        drag.exec(Qt.MoveAction)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(DRAG_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if not event.mimeData().hasFormat(DRAG_MIME):
            event.ignore()
            return
        src_name = bytes(event.mimeData().data(DRAG_MIME)).decode("utf-8")
        if src_name != self._script_name:
            self.dropped.emit(src_name, self._script_name)
        event.acceptProposedAction()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # 选中：粗白色圆角方框（画在 56 边界，完整包住 48 图标；画布 3:16 一致）
        if self._selected:
            pen = QPen(QColor(C_WHITE), 3)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(self.rect(), 16, 16)
        # 真实图标（48×48 居中画在 (4,4)，与画布 3:17 一致）
        pix = self._icon.pixmap(48, 48)
        p.drawPixmap(4, 4, pix)
        # 停用：盖半透明黑（光暗表达启停，只盖图标区域，对齐设计稿）
        if not self._enabled:
            p.fillRect(4, 4, 48, 48, QColor(0, 0, 0, 150))


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
        self.service = ChainService()
        self.games = self._load_games()
        assert self.games, "[launcher_proto] config.yml 中没有脚本"
        self._current_index = 0
        self._control_mode = (
            False  # ⊞ 模式：False=浏览（点图标选脚本），True=控制（点图标启停）
        )
        # 任务调度（副本/序列选择）持久化到 gui_state.json（与旧 GUI 一致）；
        # 仅 enabled 按钮状态不持久化（内存态，重启默认全开）
        self._dungeon_state: dict = self.service.load_ui_state()
        self._weekly_toggle_state: dict[str, bool] = self._init_weekly_toggle_states()
        self._custom_bg: dict[str, str] = self._load_wallpapers()  # 脚本 → 壁纸路径
        self._bg = QPixmap()  # 按选中游戏延迟加载
        self._build_ui()
        self._apply_current_game()
        # 周常开关（enabled）是纯内存态：启动时由 weekly_start 初始化（_init_weekly_toggle_states），
        # 脚本配置的周常开关由运行链时 chain_gen 按 weekly_start 判断写入，启动时不落盘

    def _init_weekly_toggle_states(self) -> dict[str, bool]:
        """初始化各脚本周常开关（纯内存 UI 态，不持久化、不写脚本配置）。

        启动时由 weekly_start 决定：已设置「周几起」且今天周几 >= 起始日 → True，
        否则 False。仅用于 UI 显示；周常是否执行由运行链时 chain_gen 按
        weekly_start 判断（与日常开关模型一致）。
        """
        states: dict[str, bool] = {}
        for game in self.games:
            script_name = game["script_name"]
            if not _supports_weekly(script_name):
                continue
            saved = self._dungeon_state.get(script_name)
            weekly_start = saved.get("weekly_start") if saved else None
            states[script_name] = weekly_start is not None and is_weekly_start_reached(
                weekly_start
            )
        return states

    def _load_games(self) -> list[dict]:
        """从 config.yml 构建左侧栏脚本列表（全部 script_list，含 python 辅助脚本）。

        Returns:
            每个元素：{display_name, script_name, script_data, char, color}。
            script_data 供 get_script_icon 取真实图标；color/char 仅供兜底渐变背景。
        """
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
        return games

    def _apply_current_game(self):
        """选中游戏切换后：刷新任务卡（所有脚本都显示，未适配只留标题）、
        日常 chip、周常 chip 与开关、背景图。"""
        game = self.games[self._current_index]
        adapted = game["script_name"] in _CONFIGS
        self._set_task_card_title(game["display_name"])
        self._set_task_rows_visible(adapted)
        if adapted:
            self._refresh_daily_chip()
            self._refresh_weekly_chip()
            self._sync_weekly_toggle()
        self._bg = self._load_bg(game)
        self.update()

    def _sync_weekly_toggle(self):
        """把当前游戏的周常开关内存态同步到 UI toggle（set_on 不发信号，无循环）。"""
        script_name = self._current_game()["script_name"]
        self.weekly_toggle.set_on(self._weekly_toggle_state.get(script_name, False))

    def _on_weekly_toggled(self, on: bool):
        """周常开关点击：只更新内存态（纯 UI，不持久化、不写脚本配置）。

        与日常开关模型一致：enabled 只在内存，周常是否执行由 weekly_start
        按「今天周几 >= 起始日」在运行链时决定（chain_gen → set_config）。
        """
        self._weekly_toggle_state[self._current_game()["script_name"]] = on

    def _load_bg(self, game: dict) -> QPixmap:
        """加载背景图：自定义壁纸（_open_wallpaper）→ 脚本背景（set_config）
        → 兜底 assets/ds.jpg → 空（渐变）。

        所有脚本通用：未配置背景图（get_game_bg_img 返回空）时用项目根
        assets/ds.jpg；该文件也缺失时才返回空走渐变占位。
        """
        bg_path = self._custom_bg.get(game["script_name"]) or (
            _get_game_bg_img(game["script_name"]) or DEFAULT_BG
        )
        resolved = resolve_script_path(bg_path)
        if not os.path.isfile(resolved):
            return QPixmap()
        return QPixmap(resolved)

    # ── 无边框窗口拖动（按住空白处移动窗口）─────────────────────────────
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
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
        self._build_select_buttons()
        self._build_float_bar()
        self._build_window_controls()
        self._build_toast()
        # hero 全画布（后创建）会盖住 rail，最后统一把 rail 提到最上保证可交互
        self.rail.raise_()

    def _build_toast(self):
        """右下角 toast 浮层（frameless 窗口无标题栏，提示必须用浮层显示）。"""
        self.toast_lbl = QLabel(self)
        self.toast_lbl.setStyleSheet(
            "background:rgba(10,16,32,0.92); color:#FFFFFF;"
            "border-radius:12px; padding:10px 18px; font-size:14px;"
        )
        self.toast_lbl.hide()
        self.toast_lbl.raise_()
        # 单实例 timer：连续触发时 restart，避免旧 timer 提前隐藏新 toast
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self.toast_lbl.hide)

    def _build_left_rail(self):
        """左侧游戏栏：脚本图标可滚动（滚轮/拖动，无 scrollbar）；
        ⊞ 与启动全部固定在栏底（画布 3:33/3:151 常驻最下方）。"""
        # 底部固定区（贴底，底部间距 16）：启动全部 48 + 8 + ⊞ 48 + 8 + 分割线 1 = 113
        self.rail = RailContainer(self, fixed_bottom_height=113)
        self.rail.move(0, 0)
        # hero 全画布后覆盖 rail 区域（0..80），raise 让 rail 浮在最上（可交互）
        self.rail.raise_()
        # 显式 show：首次构建时窗口未显示可省略，但拖拽重排（窗口已显示）重建时
        # 新建 QWidget 默认隐藏，不 show 会导致整个左侧栏消失
        self.rail.show()
        content = self.rail.content()

        # 脚本图标（滚动区，56×56 stride 64（含 8 间距，画布 itemSpacing=8）；
        # rail.add() 触发滚动范围重算；x=12 在 80 宽栏内居中）
        self.game_icons = []
        for i, game in enumerate(self.games):
            icon = GameIcon(
                i,
                game["script_name"],
                game["script_data"],
                i == self._current_index,
                parent=content,
            )
            self.rail.add(icon, 12, 16 + i * 64)
            icon.clicked.connect(self._select_game)
            icon.dropped.connect(self._reorder_scripts)
            self.game_icons.append(icon)

        # 固定区遮罩：z-order 在 content 之上、固定区元素之下——滚动内容显示到
        # 分割线以下就被盖住，不会透过 ⊞（透明背景）与 ▶ 区域造成"重合"。
        # 必须完全不透明：半透明会把滚过的图标透出来。
        self._fixed_overlay = QFrame(self.rail)
        self._fixed_overlay.setGeometry(0, 591, 80, CANVAS_H - 591)
        self._fixed_overlay.setStyleSheet("background:#070A14;")
        self._fixed_overlay.show()

        # 分割线（⊞ 上方 8px，固定区顶；与画布 10:5 一致）
        divider = QFrame(self.rail)
        divider.setGeometry(16, 591, 48, 1)
        divider.setStyleSheet("background:#2A3850;")
        divider.show()

        # ⊞ 工具网格（固定：y=600；48×48；点击切换浏览/控制模式）
        self.grid_frame = QFrame(self.rail)
        self.grid_frame.setGeometry(16, 600, 48, 48)
        self.grid_frame.setStyleSheet(
            "background:transparent; border:1px solid #4D6A8C; border-radius:12px;"
        )
        self.grid_frame.setCursor(Qt.PointingHandCursor)
        self.grid_frame.mousePressEvent = lambda e: (
            self._toggle_mode() if e.button() == Qt.LeftButton else None
        )
        grid_glyph = _GlyphButton(draw_grid, self.grid_frame)
        grid_glyph.setGeometry(0, 0, 48, 48)
        grid_glyph.show()
        self.grid_frame.show()

        # 启动全部按钮（固定最底部：y=656；48×48；QFrame + WA_Hover 启用 :hover 反馈）
        launch_btn = QFrame(self.rail)
        launch_btn.setGeometry(16, 656, 48, 48)
        launch_btn.setAttribute(Qt.WA_Hover, True)
        launch_btn.setStyleSheet(
            f"QFrame {{ background:{C_YELLOW}; border-radius:12px; }}"
            f"QFrame:hover {{ background:{QColor(C_YELLOW).lighter(118).name()}; }}"
        )
        launch_btn.setCursor(Qt.PointingHandCursor)
        launch_glyph = _GlyphButton(draw_launch, launch_btn)
        launch_glyph.setGeometry(0, 0, 48, 48)
        launch_glyph.show()
        launch_btn.show()

        # 点击事件（accept 防止冒泡触发 RailContainer 拖动）
        def _on_launch_press(e):
            if e.button() == Qt.LeftButton:
                e.accept()
                self._launch_all()

        launch_btn.mousePressEvent = _on_launch_press
        # 固定区元素直接放 rail 上，滚动只影响 content；重建后恢复 ⊞ 模式样式
        self._apply_mode_style()

    def _rebuild_left_rail(self):
        """（重）建左侧栏：销毁旧 rail 后按 self.games 重建（脚本增删/改名后调用）。

        旧 rail 先 setParent(None) 脱离显示，再 deleteLater 排队销毁；
        _build_left_rail 内 self.rail / self.game_icons 均重新赋值。
        """
        if getattr(self, "rail", None) is not None:
            self.rail.setParent(None)
            self.rail.deleteLater()
        self._build_left_rail()

    def _apply_mode_style(self):
        """刷新 ⊞ 的模式样式（浏览/控制），供 _toggle_mode 与重建后恢复用。

        控制模式：⊞ 高亮 + 显示全选/清空按钮；浏览模式：⊞ 常态 + 隐藏。
        _build_left_rail 重建时 _build_select_buttons 尚未创建，getattr 保护。
        """
        if self._control_mode:
            self.grid_frame.setStyleSheet(
                "background:#1A2A4A; border:1px solid #7DA8FF; border-radius:14px;"
            )
        else:
            self.grid_frame.setStyleSheet(
                "background:transparent; border:1px solid #4D6A8C; border-radius:14px;"
            )
        for attr in ("clear_btn", "select_all_btn"):
            btn = getattr(self, attr, None)
            if btn is not None:
                btn.setVisible(self._control_mode)

    def _build_hero(self):
        """HERO 区：全画布 1280x720（子元素用画布绝对坐标）。

        背景图由 LauncherWindow.paintEvent 铺满全画布（16:9 零裁切）；
        hero 只是子元素容器（透明），坐标与画布绝对坐标一致。"""
        self.hero = QWidget(self)
        self.hero.setGeometry(0, 0, CANVAS_W, CANVAS_H)

    def _build_task_card(self):
        """专题卡（左下 x:48 y:428 w:480，玻璃半透明）。

        标题随选中游戏变化；所有脚本都显示卡片（任务调度），未适配副本配置
        的游戏（不在 set_config._CONFIGS）只留标题，隐藏总开关/分隔线/任务行
        （通过 _set_task_rows_visible 控制，卡片高度随之收缩）。
        """
        self.task_card = QFrame(self.hero)
        self.task_card.setGeometry(128, 428, 480, 268)
        # 玻璃感：半透明
        self.task_card.setStyleSheet(
            "background:rgba(10,16,32,0.78); border-radius:16px;"
        )
        shadow = QGraphicsDropShadowEffect(self.task_card)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 130))
        self.task_card.setGraphicsEffect(shadow)
        self.task_card.show()

        # 标题行（ico 36×36 与任务行 ico 对齐：x=12；文字 x=58 与行名对齐）
        title_row = QWidget(self.task_card)
        title_row.setGeometry(20, 18, 440, 36)
        t_ico = QLabel("▶", title_row)
        t_ico.setGeometry(12, 0, 36, 36)
        t_ico.setStyleSheet(
            f"background:{C_YELLOW}; color:#1A1A1A; font-size:16px;"
            "border-radius:10px; qproperty-alignment:AlignCenter;"
        )
        self.task_title = QLabel("", title_row)
        self.task_title.setGeometry(58, 5, 260, 26)
        self.task_title.setStyleSheet(
            f"color:{C_WHITE}; font-size:19px; font-weight:700; background:transparent;"
        )

        # 总开关（标题行右侧，与任务行开关右边缘对齐 x=388；一键同步日常/周本）
        self.master_toggle = Toggle(True, title_row)
        self.master_toggle.move(388, 7)
        self.master_toggle.toggled.connect(self._on_master_toggled)

        # 分隔线
        self.card_divider = QFrame(self.task_card)
        self.card_divider.setGeometry(20, 56, 440, 1)
        self.card_divider.setStyleSheet("background:#2A3850;")

        # 日常行（启用；chip 点击弹出副本选择菜单）
        self.daily_row, self.daily_chip_lbl = self._task_row(
            self.task_card,
            20,
            68,
            "日常",
            "#0F1A2E",
            C_BLUE_TEXT,
            "⚡",
            "#1A3A7A",
            C_BLUE_TEXT,
            "选择副本",
            True,
        )
        self.daily_chip_lbl.setCursor(Qt.PointingHandCursor)
        self.daily_chip_lbl.mousePressEvent = lambda e: (
            self._show_daily_menu() if e.button() == Qt.LeftButton else None
        )
        # 周常行（周几以后开始执行；支持态由 _supports_weekly 决定，
        # 支持则 chip 可点选周一起始日，未支持保持「未支持」禁用）
        self.weekly_row, self.weekly_chip_lbl = self._task_row(
            self.task_card,
            20,
            134,
            "周常",
            "#1A2028",
            C_FAINT,
            "📅",
            "#2A3040",
            C_FAINT,
            "未支持",
            False,
            obj_prefix="weekly",
        )
        self.weekly_ico_lbl = self.weekly_row.findChild(QLabel, "weekly_ico")
        self.weekly_name_lbl = self.weekly_row.findChild(QLabel, "weekly_name")
        self.weekly_chip_lbl.setCursor(Qt.ArrowCursor)
        self.weekly_chip_lbl.mousePressEvent = lambda e: (
            self._show_weekly_menu() if e.button() == Qt.LeftButton else None
        )
        # 周常开关（toggle，纯内存 UI 态不持久化）：点击只改按钮，不写脚本配置；
        # 周常是否执行由运行链时 chain_gen 按 weekly_start 判断
        self.weekly_toggle = self.weekly_row.findChild(Toggle)
        self.weekly_toggle.toggled.connect(self._on_weekly_toggled)

    def _set_task_rows_visible(self, adapted: bool):
        """任务行显隐：适配脚本显示日常/周本（卡片 268 高）；未适配只留标题 + 总开关
        （隐藏分隔线/两行，卡片收缩到 100 高）。"""
        self.card_divider.setVisible(adapted)
        self.daily_row.setVisible(adapted)
        self.weekly_row.setVisible(adapted)
        height = 268 if adapted else 100
        self.task_card.setGeometry(128, 428, 480, height)

    def _set_task_card_title(self, display_name: str):
        """更新任务卡标题（只显示游戏名）。"""
        self.task_title.setText(display_name)

    def _task_row(
        self,
        card,
        x,
        y,
        name,
        chip_bg,
        name_fg,
        ico_char,
        ico_bg,
        chip_fg,
        chip_text,
        on,
        obj_prefix: str = "",
    ):
        """专题卡内任务行（56 高，图标+名称+chip+开关；行背景透明——画布已去）。

        ``obj_prefix`` 非空时给 ico/name/chip 子 QLabel 设
        ``{prefix}_ico/name/chip`` 的 objectName，供外部 ``findChild`` 拿到引用
        （如周常行支持态需同步切整行样式，日常行不需要）。

        Returns:
            (row, chip_lbl)：chip_lbl 供外部点击绑定副本选择菜单。
        """
        row = QFrame(card)
        row.setGeometry(x, y, 440, 56)
        row.setStyleSheet("background:transparent;")
        # 置灰由行内暗色参数表达（未支持行传暗色 chip/ico/文字 + toggle 灰色关闭态），
        # 不加覆盖层：QGraphicsOpacityEffect 会让子控件渲染偏移，覆盖层会叠出多余背景
        row.show()

        ico = QLabel(ico_char, row)
        ico.setGeometry(12, 10, 36, 36)
        ico.setStyleSheet(
            f"background:{ico_bg}; color:{chip_fg}; font-size:16px;"
            "border-radius:10px; qproperty-alignment:AlignCenter;"
        )
        if obj_prefix:
            ico.setObjectName(f"{obj_prefix}_ico")

        name_lbl = QLabel(name, row)
        name_lbl.setGeometry(58, 15, 60, 26)
        name_lbl.setStyleSheet(
            f"color:{name_fg}; font-size:15px; font-weight:600; background:transparent;"
        )
        if obj_prefix:
            name_lbl.setObjectName(f"{obj_prefix}_name")

        chip = QFrame(row)
        chip.setGeometry(130, 15, 96, 26)
        chip.setAttribute(Qt.WA_Hover, True)
        chip.setStyleSheet(
            f"QFrame {{ background:{chip_bg}; border-radius:13px; border:1px solid #33517A; }}"
            f"QFrame:hover {{ background:{QColor(chip_bg).lighter(125).name()};"
            " border:1px solid #7DA8FF; }"
        )
        chip_lbl = QLabel(chip_text, chip)
        chip_lbl.setStyleSheet(
            f"color:{chip_fg}; font-size:11px; background:transparent;"
        )
        chip_lbl.setGeometry(0, 0, 96, 26)
        chip_lbl.setAlignment(Qt.AlignCenter)
        if obj_prefix:
            chip_lbl.setObjectName(f"{obj_prefix}_chip")

        toggle = Toggle(on, row)
        toggle.move(388, 17)
        # toggle 关闭态自带灰色轨道/滑块视觉，行内容置灰由暗色参数表达，
        # 无需行级联动（避免 QGraphicsEffect 偏移 / 覆盖层叠出多余背景）
        return row, chip_lbl

    def _on_master_toggled(self, on):
        """总开关：一键同步日常/周本两个任务行开关（set_on 不发信号，无循环）。

        周常开关内存态一并同步（仅支持周常的脚本；总开关关 = 周常也关）。
        开关是纯内存态，不写脚本配置（由运行链时按 weekly_start 判断）。
        """
        for row in (self.daily_row, self.weekly_row):
            row.findChild(Toggle).set_on(on)
        script_name = self._current_game()["script_name"]
        if _supports_weekly(script_name):
            self._weekly_toggle_state[script_name] = on

    def _build_launch_button(self):
        """启动脚本：右下蓝色大胶囊（x:960 y:636 w:216 h:64）——可点击。

        内部布局：▶ 圆 56×56 占满高度 + 文字居中 + ☰ 圆 56×56 对称。
        文字 x=60 宽 96，中心 108 = (60+156)/2，正好在 ▶ 和 ☰ 的几何中点。"""
        btn = QFrame(self.hero)
        btn.setGeometry(960, 636, 216, 64)
        btn.setAttribute(Qt.WA_Hover, True)
        btn.setStyleSheet(
            f"QFrame {{ background:{C_BLUE}; border-radius:32px; }}"
            f"QFrame:hover {{ background:{QColor(C_BLUE).lighter(118).name()}; }}"
        )
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
        play_ico.setStyleSheet(
            f"color:{C_WHITE}; font-size:22px; font-weight:700; background:transparent;"
        )
        play_ico.setGeometry(0, 0, 56, 56)
        play_ico.setAlignment(Qt.AlignCenter)

        # 中间文字"启动脚本"居中于 [60, 156] 几何中点 108
        txt = QLabel("启动脚本", btn)
        txt.setGeometry(60, 0, 96, 64)
        txt.setStyleSheet(
            f"color:{C_WHITE}; font-size:18px; font-weight:700; background:transparent;"
        )
        txt.setAlignment(Qt.AlignCenter)

        # 右侧 ☰ 菜单圆（与 ▶ 对称，56×56）——点击打开当前脚本配置弹窗
        menu = QFrame(btn)
        menu.setGeometry(156, 4, 56, 56)
        menu.setStyleSheet(f"background:{C_BLUE_DEEP}; border-radius:28px;")
        menu.setCursor(Qt.PointingHandCursor)
        menu_ico = QLabel("≡", menu)
        menu_ico.setStyleSheet(
            f"color:{C_WHITE}; font-size:22px; background:transparent;"
        )
        menu_ico.setGeometry(0, 0, 56, 56)
        menu_ico.setAlignment(Qt.AlignCenter)

        def _on_menu_press(e):
            if e.button() == Qt.LeftButton:
                e.accept()  # 阻止冒泡到 btn 触发"启动脚本"
                self._open_config_dialog()

        menu.mousePressEvent = _on_menu_press

        # 点击 accept，防止事件冒泡到 LauncherWindow 触发窗口拖动
        def _on_launch_script_press(e):
            if e.button() == Qt.LeftButton:
                e.accept()
                self._launch_script()

        btn.mousePressEvent = _on_launch_script_press

    def _build_select_buttons(self):
        """全选 / 清空按钮：清空在 ⊞ 右边（hero 区），全选在启动脚本胶囊右边。

        清空按钮：48x48 暗色圆角（× 图标），紧邻 rail 右边 8px（x=88, y=600），
        与 ⊞（y=600）水平对齐。点击 → _deselect_all（所有脚本停用）。

        全选按钮：64x64 绿色圆角（√ 图标），紧邻启动脚本胶囊右边 8px
        （x=1184, y=636），与启动脚本（y=636）水平对齐。点击 → _select_all。
        """
        # 清空按钮（hero 区，⊞ 右边）
        self.clear_btn = QFrame(self.hero)
        self.clear_btn.setGeometry(88, 600, 48, 48)
        self.clear_btn.setAttribute(Qt.WA_Hover, True)
        self.clear_btn.setStyleSheet(
            f"QFrame {{ background:{C_BTN_DARK}; border-radius:14px; }}"
            f"QFrame:hover {{ background:{QColor(C_BTN_DARK).lighter(140).name()}; }}"
        )
        self.clear_btn.setCursor(Qt.PointingHandCursor)
        clear_glyph = _GlyphButton(draw_deselect_all, self.clear_btn)
        clear_glyph.setGeometry(0, 0, 48, 48)
        clear_glyph.show()
        self.clear_btn.setVisible(self._control_mode)  # 仅控制模式显示

        def _on_clear_press(e):
            if e.button() == Qt.LeftButton:
                e.accept()
                self._deselect_all()

        self.clear_btn.mousePressEvent = _on_clear_press

        # 全选按钮（启动全部按钮右边：x=88 y=656，48×48 与启动全部对齐；
        # 清空按钮在 ⊞ 右边同一列 x=88 y=600，两者垂直排列）
        self.select_all_btn = QFrame(self.hero)
        self.select_all_btn.setGeometry(88, 656, 48, 48)
        self.select_all_btn.setAttribute(Qt.WA_Hover, True)
        self.select_all_btn.setStyleSheet(
            f"QFrame {{ background:{C_GREEN}; border-radius:12px; }}"
            f"QFrame:hover {{ background:{QColor(C_GREEN).lighter(115).name()}; }}"
        )
        self.select_all_btn.setCursor(Qt.PointingHandCursor)
        select_glyph = _GlyphButton(draw_select_all, self.select_all_btn)
        select_glyph.setGeometry(0, 0, 48, 48)
        select_glyph.show()
        self.select_all_btn.setVisible(self._control_mode)  # 仅控制模式显示

        def _on_select_all_press(e):
            if e.button() == Qt.LeftButton:
                e.accept()
                self._select_all()

        self.select_all_btn.mousePressEvent = _on_select_all_press

    def _build_float_bar(self):
        """右侧悬浮条（6 个图标，无背景框——画布 3:287 已去玻璃底）。"""
        bar = QFrame(self.hero)
        bar.setGeometry(1220, 80, 60, 300)
        # 去掉玻璃底：图标按钮自身有深色底，直接悬浮在 hero 上
        bar.setStyleSheet("background:transparent;")
        bar.show()

        icons = [
            (draw_home, "主页", self._open_home),
            (draw_controller, "启动游戏", self._launch_game),
            (draw_folder, "打开脚本目录", self._open_script_folder),
            (draw_tv, "B站", self._open_bilibili),
            (draw_github, "GitHub", self._open_github),
            (draw_wallpaper, "壁纸", self._open_wallpaper),
        ]
        y = 22
        for fn, _name, action in icons:
            btn = IconButton(fn, bar, size=36, radius=12)
            btn.move(12, y)
            btn.clicked.connect(action)
            y += 48  # 36 + 12 gap

    def _build_window_controls(self):
        """窗口控制（右上角贴右边缘，深底圆按钮）。

        最右：关闭（1244..1280）；左 8px：最小化（1200..1236）；再左 8px：
        配置文件齿轮（1156..1192，打开总配置 config.yml——旧 GUI 同功能）。
        """
        cfg_btn = IconButton(draw_config, self.hero, size=36, radius=18)
        cfg_btn.move(1156, 8)
        cfg_btn.clicked.connect(self._open_config_yml)
        min_btn = IconButton(draw_min, self.hero, size=36, radius=18)
        min_btn.move(1200, 8)
        min_btn.clicked.connect(self.showMinimized)
        close_btn = IconButton(draw_close, self.hero, size=36, radius=18)
        close_btn.move(1244, 8)
        close_btn.clicked.connect(self.close)

    def _open_config_yml(self):
        """打开总配置文件 config.yml（系统默认程序）；缺失时 toast 提示（对齐旧 GUI）。"""
        config_path = get_config_yml_path_under_root()
        if not os.path.isfile(config_path):
            self._toast("未找到 config/config.yml")
            return
        os.startfile(config_path)  # noqa: S606 打开配置文件

    # ── 交互 ─────────────────────────────────────────────────────────────
    def _toggle_mode(self):
        """⊞ 模式切换：浏览（点图标选脚本）⇄ 控制（点图标切换启用/停用）。"""
        self._control_mode = not self._control_mode
        self._apply_mode_style()
        if self._control_mode:
            self._toast("控制模式：点击图标切换启用/停用")
        else:
            self._toast("浏览模式：点击图标选择脚本")

    def _select_all(self):
        """全选：所有脚本图标设为启用（纯内存态，不持久化）。"""
        for icon in self.game_icons:
            icon.set_enabled(True)
        self._toast("已全选（全部启用）")

    def _deselect_all(self):
        """清空：所有脚本图标设为停用（纯内存态，不持久化）。"""
        for icon in self.game_icons:
            icon.set_enabled(False)
        self._toast("已清空（全部停用）")

    def _select_game(self, index: int):
        """点击左侧脚本图标：控制模式切换启停，浏览模式切换选中。"""
        assert 0 <= index < len(self.games), f"game index out of range: {index}"
        if self._control_mode:
            icon = self.game_icons[index]
            icon.set_enabled(not icon.is_enabled())
            self._toast(
                f"{self.games[index]['display_name']}："
                f"{'启用' if icon.is_enabled() else '停用'}"
            )
            return
        self._current_index = index
        for i, icon in enumerate(self.game_icons):
            icon.set_selected(i == index)
        self._apply_current_game()
        self._toast(f"已切换到 {self.games[index]['display_name']}")

    def _current_game(self) -> dict:
        """当前选中游戏条目。"""
        return self.games[self._current_index]

    def _reorder_scripts(self, src_script_name: str, dst_script_name: str):
        """拖拽重排：把 src 脚本移到 dst 脚本位置，同步 UI 与 config.yml（对齐旧 GUI）。"""
        src_idx = next(
            (
                i
                for i, g in enumerate(self.games)
                if g["script_name"] == src_script_name
            ),
            None,
        )
        dst_idx = next(
            (
                i
                for i, g in enumerate(self.games)
                if g["script_name"] == dst_script_name
            ),
            None,
        )
        assert src_idx is not None, (
            f"[launcher_proto] 拖拽源脚本不存在: {src_script_name}"
        )
        assert dst_idx is not None, (
            f"[launcher_proto] 拖拽目标脚本不存在: {dst_script_name}"
        )
        cur_name = self._current_game()["script_name"]  # 重排后按名字恢复选中
        game = self.games.pop(src_idx)
        self.games.insert(dst_idx, game)

        # 同步 config.yml 顺序（以 UI 顺序为准），持久化
        config_data = self.service.load_config()
        scripts = config_data["script_list"]
        s_idx = next(
            (i for i, s in enumerate(scripts) if get_script_name(s) == src_script_name),
            None,
        )
        assert s_idx is not None, (
            f"[launcher_proto] config 中找不到源脚本: {src_script_name}"
        )
        script = scripts.pop(s_idx)
        scripts.insert(dst_idx, script)
        self.service.save_config(config_data)

        # 重建左侧栏并恢复选中（新 index 可能已变）
        new_idx = next(
            (i for i, g in enumerate(self.games) if g["script_name"] == cur_name),
            None,
        )
        assert new_idx is not None, f"[launcher_proto] 重排后丢失选中脚本: {cur_name}"
        self._current_index = new_idx
        self._rebuild_left_rail()
        self._apply_current_game()
        self._toast("已调整脚本顺序")

    def _enabled_task_names(self) -> list:
        """当前已启用（开关开启）的任务行名称。"""
        return [
            n
            for n, row in (("日常", self.daily_row), ("周常", self.weekly_row))
            if row.findChild(Toggle).is_on()
        ]

    def _confirm_run(self, enabled_keys: set[str]) -> bool:
        """运行前校验（对齐旧 GUI _warn_if_invalid_scripts）+ 确认弹窗。

        Returns:
            True 继续运行，False 取消。
        """
        config_data = self.service.load_config()
        enabled_scripts = [
            s for s in config_data["script_list"] if get_script_name(s) in enabled_keys
        ]
        invalid = self.service.collect_invalid_scripts(enabled_scripts)
        if invalid:
            details = "\n".join(f"· {name}：{msg}" for name, msg in invalid)
            reply = QMessageBox.warning(
                self,
                "脚本配置不合法",
                f"以下脚本配置不合法，运行时会被跳过：\n{details}\n\n是否仍然运行？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return False
        reply = QMessageBox.question(
            self,
            "确认运行",
            f"即将运行 {len(enabled_keys)} 个脚本，是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return reply == QMessageBox.Yes

    def _run_chain(self, config_data: dict, enabled_keys: set[str], label: str) -> None:
        """生成并运行脚本链（真实 ChainService；ui_state 用内存副本选择，不持久化）。

        周常开关（enabled）是纯内存 UI 态，不参与配置写入；周常是否执行由
        chain_gen 按 ui_state 持久化的 weekly_start（周几起）判断，运行链时
        写入脚本配置（与日常副本选择落盘模型一致）。

        直接 Popen 新控制台窗口运行 runner（cmd 可见链日志）：
        - runner 用 python.exe（pythonw 无控制台，输出无处可去）
        - CREATE_NEW_CONSOLE 开独立 cmd 窗口（复用 run_chain_command(block=False)
          会把 stdout/stderr 丢到 DEVNULL，看不到任何信息）
        """
        ui_state = {name: dict(entry) for name, entry in self._dungeon_state.items()}
        chain_path = self.service.generate_chain(
            config_data, enabled_keys, chain_name="today", ui_state=ui_state
        )
        command, cwd, env = build_script_command(["--chain", chain_path])
        command[0] = command[0].replace("pythonw.exe", "python.exe")
        subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
        self._toast(f"{label}：已生成并运行链 ({len(enabled_keys)} 个脚本)")

    def _launch_all(self):
        """启动全部：生成仅含启用（亮着）脚本的链并运行（对齐旧 GUI enabled 语义）。"""
        # games 与 game_icons 一一对应（同一循环构建），长度必然一致
        keys = {
            g["script_name"]
            for g, icon in zip(self.games, self.game_icons, strict=True)
            if icon.is_enabled()
        }
        if not keys:
            self._toast("没有启用的脚本")
            return
        if not self._confirm_run(keys):
            return
        config_data = self.service.load_config()
        self._run_chain(config_data, keys, "启动全部")

    def _launch_script(self):
        """启动当前选中脚本（直接运行，不走链；对齐旧 GUI 图标左键语义）。

        - python 脚本：走 runner 的 --script 参数用解释器运行
        - external 脚本：解析 exe 路径后 startfile 启动
        """
        game = self._current_game()
        script = game["script_data"]
        if script.get("script_type") == "python":
            resolved = resolve_script_path(script["script_path"])
            if not resolved or not os.path.isfile(resolved):
                self._toast(f"找不到脚本文件：{script['script_path']}")
                return
            command, cwd, env = build_script_command(["--script", resolved])
            subprocess.Popen(command, cwd=cwd, env=env)
        else:
            # external：容错解析（不走 get_script_path 的 assert，配置损坏时 toast 提示）
            exe_path = script.get("script_path", "")
            resolved = resolve_script_path(exe_path) if exe_path else None
            if not resolved or not os.path.isfile(resolved):
                self._toast(f"找不到脚本：{exe_path}")
                return
            os.startfile(resolved)  # noqa: S606 启动脚本本体
        self._toast(f"已启动 {game['display_name']}")

    def _show_daily_menu(self):
        """日常副本选择：弹出 dungeon_list.yml 级联菜单（一级副本 → 二级序列）。

        选择经 _set_daily 持久化到 gui_state.json；运行链时由
        generate_chain → set_config 写入脚本 config。
        """
        game = self._current_game()
        dungeon_cfg = self.service.dungeon_map().get(game["script_name"])
        options, seq_map, _ = parse_dungeon_config(dungeon_cfg)
        if not options:
            self._toast(f"{game['display_name']}：暂无副本选项")
            return
        menu = QMenu(self)
        menu.setStyleSheet("background:#0F1A2E; color:#FFFFFF;")
        for dungeon_name in options:
            if dungeon_name == "未选择":
                menu.addAction("未选择").triggered.connect(
                    lambda _c=False: self._set_daily(None, None)
                )
                menu.addSeparator()
                continue
            seqs = seq_map.get(dungeon_name, [])
            if seqs:
                submenu = menu.addMenu(dungeon_name)
                for display, value in seqs:
                    submenu.addAction(display).triggered.connect(
                        lambda _c=False, dn=dungeon_name, sq=value: self._set_daily(
                            dn, sq
                        )
                    )
            else:
                menu.addAction(dungeon_name).triggered.connect(
                    lambda _c=False, dn=dungeon_name: self._set_daily(dn, None)
                )
        menu.exec(
            self.daily_chip_lbl.mapToGlobal(self.daily_chip_lbl.rect().bottomLeft())
        )

    def _dungeon_chip_text(self, dungeon_cfg, dungeon_name: str, sequence) -> str:
        """副本 chip 文字：有二级序列且选了二级 → 二级展示名；否则副本名本身。

        避免 get_display_name 找不到二级匹配时返回字符串 "None"。
        """
        _, seq_map, _ = parse_dungeon_config(dungeon_cfg)
        if sequence is not None and dungeon_name in seq_map:
            return get_display_name(seq_map, dungeon_name, sequence)
        return dungeon_name

    def _refresh_daily_chip(self):
        """从 _dungeon_state（gui_state.json）恢复当前脚本的日常副本 chip 文字。"""
        game = self._current_game()
        saved = self._dungeon_state.get(game["script_name"])
        if not saved or not saved.get("dungeon"):
            self.daily_chip_lbl.setText("选择副本")
            return
        dungeon_cfg = self.service.dungeon_map().get(game["script_name"])
        self.daily_chip_lbl.setText(
            self._dungeon_chip_text(
                dungeon_cfg, saved["dungeon"], saved.get("sequence")
            )
        )

    def _refresh_weekly_chip(self):
        """刷新周常行整行样式：支持周常的脚本切到亮蓝可点，未支持保持暗色置灰。

        周常行整行（图标 + "周常"文字 + chip + toggle）必须在支持/未支持间整体切换，
        否则只有 chip 变亮、图标和文字仍暗，视觉割裂（之前 bug：支持态下整行
        仍像「未支持」）。切换点：切游戏（_apply_current_game）与 toggle 状态
        同步时。
        """
        game = self._current_game()
        supported = _supports_weekly(game["script_name"])
        saved = self._dungeon_state.get(game["script_name"])
        start_day = saved.get("weekly_start") if saved else None
        chip = self.weekly_chip_lbl.parent()
        if not supported:
            self.weekly_chip_lbl.setText("未支持")
            chip.setStyleSheet(
                "QFrame { background:#1A2028; border-radius:13px;"
                " border:1px solid #2A3850; }"
            )
            self.weekly_chip_lbl.setStyleSheet(
                f"color:{C_FAINT}; font-size:11px; background:transparent;"
            )
            self.weekly_chip_lbl.setCursor(Qt.ArrowCursor)
            self.weekly_toggle.setEnabled(False)
            self.weekly_ico_lbl.setStyleSheet(
                f"background:#2A3040; color:{C_FAINT}; font-size:16px;"
                "border-radius:10px; qproperty-alignment:AlignCenter;"
            )
            self.weekly_name_lbl.setStyleSheet(
                f"color:{C_FAINT}; font-size:15px; font-weight:600; background:transparent;"
            )
            return
        self.weekly_toggle.setEnabled(True)
        if start_day is None:
            self.weekly_chip_lbl.setText("选择周几")
        else:
            self.weekly_chip_lbl.setText(f"{WEEKDAY_NAMES[start_day]}起")
        chip.setStyleSheet(
            f"QFrame {{ background:#0F1A2E; border-radius:13px; border:1px solid #33517A; }}"
            f"QFrame:hover {{ background:{QColor('#0F1A2E').lighter(125).name()};"
            " border:1px solid #7DA8FF; }"
        )
        self.weekly_chip_lbl.setStyleSheet(
            f"color:{C_BLUE_TEXT}; font-size:11px; background:transparent;"
        )
        self.weekly_chip_lbl.setCursor(Qt.PointingHandCursor)
        self.weekly_ico_lbl.setStyleSheet(
            f"background:#1A3A7A; color:{C_BLUE_TEXT}; font-size:16px;"
            "border-radius:10px; qproperty-alignment:AlignCenter;"
        )
        self.weekly_name_lbl.setStyleSheet(
            f"color:{C_BLUE_TEXT}; font-size:15px; font-weight:600; background:transparent;"
        )

    def _show_weekly_menu(self):
        """周常起始日选择：弹出周一至周日菜单（含今天标注，凌晨 4 点为界）。

        选择经 _set_weekly 持久化到 gui_state.json 并同步周常开关（UI 显示）；
        脚本配置的周常开关由运行链时 chain_gen 按 weekly_start 判断写入。
        """
        game = self._current_game()
        if not _supports_weekly(game["script_name"]):
            return
        menu = QMenu(self)
        menu.setStyleSheet("background:#0F1A2E; color:#FFFFFF;")
        today = get_week_num() + 1  # 0=周一..6=周日 → 1..7
        for day in range(1, 8):
            label = WEEKDAY_NAMES[day]
            if day == today:
                label += "（今天）"
            menu.addAction(label).triggered.connect(
                lambda _c=False, d=day: self._set_weekly(d)
            )
        menu.exec(
            self.weekly_chip_lbl.mapToGlobal(self.weekly_chip_lbl.rect().bottomLeft())
        )

    def _set_weekly(self, start_day: int):
        """保存周常起始日（持久化到 gui_state.json 的 weekly_start，1=周一）并更新 chip。

        修改后立即同步周常开关（UI 显示）：今天周几 >= 起始日 → 开关开启，否则关闭。
        开关是纯内存态；脚本配置的周常开关由运行链时 chain_gen 按 weekly_start
        判断写入（与日常开关模型一致）。
        """
        assert start_day in WEEKDAY_NAMES, f"[launcher_proto] 非法周几: {start_day}"
        game = self._current_game()
        saved = self._dungeon_state.setdefault(game["script_name"], {})
        saved["weekly_start"] = start_day
        self.weekly_chip_lbl.setText(f"{WEEKDAY_NAMES[start_day]}起")
        enabled = is_weekly_start_reached(start_day)
        self._weekly_toggle_state[game["script_name"]] = enabled
        self.weekly_toggle.set_on(enabled)
        self.service.save_ui_state(self._dungeon_state)

    def _set_daily(self, dungeon_name: str | None, sequence):
        """保存日常副本选择（持久化到 gui_state.json，与旧 GUI 一致）并更新 chip 文字。

        合并更新脚本条目（保留 weekly_start 等其它字段，不整体覆盖）。
        """
        game = self._current_game()
        saved = self._dungeon_state.setdefault(game["script_name"], {})
        if dungeon_name is None:
            saved.pop("dungeon", None)
            saved.pop("sequence", None)
            self.daily_chip_lbl.setText("选择副本")
        else:
            saved["dungeon"] = dungeon_name
            saved["sequence"] = sequence
            dungeon_cfg = self.service.dungeon_map().get(game["script_name"])
            self.daily_chip_lbl.setText(
                self._dungeon_chip_text(dungeon_cfg, dungeon_name, sequence)
            )
        self.service.save_ui_state(self._dungeon_state)

    def _launch_game(self):
        """启动游戏：读取当前游戏 exe 路径并打开（未适配时提示）。"""
        game = self._current_game()
        exe_path = _get_game_exe_path(game["script_name"])
        if not exe_path:
            self._toast(f"{game['display_name']}：未找到游戏路径")
            return
        os.startfile(exe_path)  # noqa: S606 启动游戏本体
        self._toast(f"正在启动 {game['display_name']}…")

    def _open_url(self, url: str, fallback: str, label: str):
        """打开链接（游戏级 meta 有值用其值，否则用通用占位链接）。"""
        target = url or fallback
        webbrowser.open(target)
        self._toast(f"打开{label}：{target}")

    def _open_home(self):
        """打开当前游戏官方主页（set_config 声明，空则通用占位）。"""
        self._open_url(
            _get_game_homepage(self._current_game()["script_name"]),
            _URL_HOME,
            "主页",
        )

    def _open_bilibili(self):
        """打开当前游戏官方 B 站（set_config 声明，空则通用占位）。"""
        self._open_url(
            _get_game_bilibili(self._current_game()["script_name"]),
            _URL_BILIBILI,
            "B站",
        )

    def _open_github(self):
        """打开当前脚本项目的 GitHub 主页（set_config 声明，空则通用占位）。"""
        self._open_url(
            _get_game_github(self._current_game()["script_name"]),
            _URL_HOME,
            "GitHub",
        )

    def _open_script_folder(self):
        """打开当前脚本所在目录（script_path 父目录，资源管理器）。"""
        game = self._current_game()
        script_path = game["script_data"].get("script_path", "")
        resolved = resolve_script_path(script_path) if script_path else None
        if not resolved:
            self._toast(f"{game['display_name']}：未找到脚本路径")
            return
        folder = os.path.dirname(resolved)
        if not os.path.isdir(folder):
            self._toast(f"{game['display_name']}：脚本目录不存在")
            return
        os.startfile(folder)  # noqa: S606 打开脚本所在目录
        self._toast(f"已打开 {game['display_name']} 脚本目录")

    def _load_wallpapers(self) -> dict:
        """读取 config/wallpaper.json（脚本 → 壁纸路径）；缺失返回空。"""
        path = resolve_script_path("config/wallpaper.json")
        if not os.path.isfile(path):
            return {}
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def _save_wallpapers(self):
        """把 _custom_bg 写回 config/wallpaper.json。"""
        path = resolve_script_path("config/wallpaper.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._custom_bg, f, ensure_ascii=False, indent=2)

    def _open_wallpaper(self):
        """更改当前脚本壁纸并持久化。

        选图 → 记录原路径到 _custom_bg → 写 config/wallpaper.json。
        取消选择（空路径）无操作。
        """
        game = self._current_game()
        path, _ = QFileDialog.getOpenFileName(
            self,
            f"选择 {game['display_name']} 壁纸",
            "",
            "图片 (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if not path:
            return
        self._custom_bg[game["script_name"]] = path
        self._save_wallpapers()
        self._apply_current_game()
        self._toast(f"已更换 {game['display_name']} 壁纸")

    def _open_config_dialog(self):
        """打开当前脚本的配置弹窗（复用 SingleScriptConfigDialog）。

        保存成功（Accept）→ ChainService.update_script 落盘并重载左侧栏；
        删除确认（delete_requested 信号）→ ChainService.remove_script 落盘并重载。
        弹窗删除路径走 close()（非 Accepted），不会误入保存分支。
        """
        game = self._current_game()
        dialog = SingleScriptConfigDialog(
            game["script_name"],
            game["display_name"],
            game["script_data"].get("script_path", ""),
            self,
            script_service=self.service._script_service,
        )
        dialog.delete_requested.connect(self._on_delete_script)
        if dialog.exec() == QDialog.Accepted:
            assert dialog.pending_changes is not None, (
                "[launcher_proto] 配置弹窗 accept 但 pending_changes 为空"
            )
            changes = dialog.pending_changes
            self.service.update_script(
                changes["old_script_name"],
                changes["new_display_name"],
                changes["config_patch"],
                changes["weekly_timeouts"],
            )
            self._reload_games()
            self._toast(f"已保存 {changes['new_display_name']} 配置")

    def _on_delete_script(self, script_name: str):
        """配置弹窗确认删除：先落盘（config.yml + weekly 清理）再重建左侧栏。

        落盘先于 UI 重建，避免 remove_script 断言失败时界面与磁盘状态不一致。
        """
        self.service.remove_script(script_name)
        self._reload_games()
        self._toast("已删除脚本")

    def _reload_games(self):
        """配置保存后重载左侧栏：重读 config.yml 并完整重建 rail（脚本数可变）。"""
        self.games = self._load_games()
        if not self.games:
            # 删光所有脚本：索引置 -1 并清空 rail，避免越界崩溃
            self._current_index = -1
            self._rebuild_left_rail()
            return
        self._current_index = min(self._current_index, len(self.games) - 1)
        self._rebuild_left_rail()
        self._apply_current_game()

    def _toast(self, text: str):
        """右下角 toast 浮层：显示 3 秒后自动消失（frameless 无标题栏提示）。"""
        self.toast_lbl.setText(text)
        self.toast_lbl.adjustSize()
        w, h = self.toast_lbl.width(), self.toast_lbl.height()
        # 底部居中，避开任务卡（左）和启动脚本按钮（右）
        self.toast_lbl.move((CANVAS_W - w) // 2, CANVAS_H - h - 16)
        self.toast_lbl.show()
        self.toast_lbl.raise_()
        self._toast_timer.start(3000)

    # ── 背景绘制（官方图 / 渐变占位）──────────────────────────────────────
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(
            QPainter.SmoothPixmapTransform, True
        )  # 平滑缩放背景图，抑制颗粒感
        # 画布底
        p.fillRect(self.rect(), QColor(C_WINDOW_BG))
        # 背景铺满全画布（16:9 零裁切）；左侧栏半透明覆盖在背景上（双画布叠加）
        target = QRect(0, 0, CANVAS_W, CANVAS_H)
        if not self._bg.isNull():
            # cover 裁剪：按目标比例截取源图（中心对齐），避免超宽/超高图拉伸变形
            # （如崩铁 bg37 2560x1162 超宽，全图压到 16:9 会纵向压扁）
            src_w, src_h = self._bg.width(), self._bg.height()
            target_ratio = target.width() / target.height()
            src_ratio = src_w / src_h
            if src_ratio > target_ratio:
                crop_w = int(src_h * target_ratio)
                src_rect = QRect((src_w - crop_w) // 2, 0, crop_w, src_h)
            else:
                crop_h = int(src_w / target_ratio)
                src_rect = QRect(0, (src_h - crop_h) // 2, src_w, crop_h)
            p.drawPixmap(target, self._bg, src_rect)
        else:
            self._draw_gradient_bg(p, target)

    def _draw_gradient_bg(self, p: QPainter, rect: QRect):
        """渐变占位背景：游戏主色 → 深色，中央大号游戏名（背景图未实现的过渡方案）。"""
        game = self._current_game()
        base = QColor(game["color"])
        grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
        grad.setColorAt(0.0, base.lighter(130))
        grad.setColorAt(1.0, QColor(C_WINDOW_BG))
        p.fillRect(rect, grad)
        # 中央水印：游戏名首字，低透明度
        p.setFont(make_font(260, 900))
        p.setPen(QColor(255, 255, 255, 22))
        p.drawText(rect, Qt.AlignCenter, game["char"])


def main():
    app = QApplication([])
    # 全局默认字体：QLabel 的 QSS 只设 font-size 未设 font-family，中文字符会 fallback
    # 到宋体(SimSun)；显式设置应用默认字体为微软雅黑后 QSS 文字统一用它
    app.setFont(QFont(FONT_FAMILY))
    # 对齐旧 GUI：config 与模板不一致时弹窗确认（含 30s 限时，超时自动按拒绝处理；
    # CLI/测试不注入）
    ScriptConfig.confirm_before_save = confirm_config_update
    win = LauncherWindow()
    win.show()
    app.exec()


if __name__ == "__main__":
    main()
