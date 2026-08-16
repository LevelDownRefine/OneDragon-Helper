"""launcher_proto 自绘控件：左侧滚动栏、滑动开关、脚本图标按钮。

从 launcher_proto.py 按职责拆分而来（2026-08-16）：RailContainer（滚轮/拖动
滚动 + 惯性滑行）、Toggle（启停开关）、GameIcon（脚本图标 + 拖拽重排）三个
纯 UI 复用件独立成模块，零业务耦合（不碰 config/service，只经信号/方法交互）。
依赖单向：widgets → theme / src.gui.icons，launcher_proto → widgets。
"""

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QMimeData,
    QRect,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QColor, QDrag, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget

from src.gui.icons import get_script_icon
from src.launcher_proto.theme import (
    C_GRAY_KNOB,
    C_GRAY_TRACK,
    C_GREEN,
    C_WHITE,
    CANVAS_H,
    DRAG_MIME,
)


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
