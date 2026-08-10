"""自定义控件：ToggleSwitch 滑动开关与 ScriptItem 脚本卡片。"""

import contextlib
import logging
import os
import subprocess

from PySide6.QtCore import QMimeData, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QDrag, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QWidget,
)

from src.config.dungeon_config import get_display_name
from src.config.subscript import get_script_path, resolve_script_path
from src.gui import icons, theme
from src.gui.dialogs import SingleScriptConfigDialog
from src.gui.utils import (
    _styled_msg_box,
    safe_startfile,
)
from src.utils_runner import build_script_command

logger = logging.getLogger(__name__)

# 拖拽重排使用的自定义 MIME 类型（仅在本应用内传递脚本 display_name）
DRAG_MIME = "application/x-onedragon-script"

# 弹出菜单统一样式（theme 模板）：白底深字，避免深色系统主题下文字不可读
_MENU_STYLE = theme.menu_qss()

# 副本按钮 QSS（与脚本名 chip 风格统一）：透明底 + 雾蓝边框 + 钢蓝 hover
_DUNGEON_BTN_QSS = (
    f"QPushButton {{"
    f"  border: 1px solid {theme.BORDER}; border-radius: 8px;"
    f"  padding: 0 10px; background: transparent;"
    f"  color: {theme.DARK_BLUE}; font-family: {theme.FONT_FAMILY};"
    f"  font-size: {theme.FONT_SIZE_BODY}px; text-align: center;"
    f"}}"
    f"QPushButton:hover {{"
    f"  border-color: {theme.BLUE}; background: transparent;"
    f"  color: {theme.BLUE};"
    f"}}"
    f"QPushButton:pressed {{"
    f"  border-color: {theme.BLUE}; background: transparent;"
    f"  color: {theme.DARK_BLUE};"
    f"}}"
)

# 标题列宽度常量（详见 MainWindow._sync_title_widths）
TITLE_DEFAULT_WIDTH = 110  # 构造期占位宽度；加载完成后会被 sync 流程覆盖
TITLE_MIN_WIDTH = 60
TITLE_MAX_WIDTH = 180


class ToggleSwitch(QWidget):
    """自定义滑动开关（圆角轨道 + 圆形滑块）"""

    toggled = Signal(bool)

    TRACK_ON = theme.BLUE
    TRACK_OFF = theme.DISABLED
    KNOB = theme.BG_CARD

    def __init__(self, parent=None, checked=True):
        super().__init__(parent)
        self._checked = checked
        self.setFixedSize(42, 24)
        self.setCursor(Qt.PointingHandCursor)

    def setChecked(self, value):
        if self._checked != value:
            self._checked = value
            self.update()

    def isChecked(self):
        return self._checked

    def mousePressEvent(self, event):
        self._checked = not self._checked
        self.update()
        self.toggled.emit(self._checked)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = h / 2
        # 轨道
        track = QColor(self.TRACK_ON if self._checked else self.TRACK_OFF)
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(0, 0, w, h, r, r)
        # 滑块
        knob_d = h - 6
        kx = (w - knob_d - 3) if self._checked else 3
        ky = (h - knob_d) / 2
        p.setBrush(QColor(self.KNOB))
        p.drawEllipse(int(kx), int(ky), knob_d, knob_d)


class ScriptItem(QFrame):
    """单个脚本项（卡片风格）"""

    def __init__(
        self,
        script_data,
        dungeon_options=None,
        sequence_options_map=None,
        show_sequence=False,
        saved_state=None,
        reorder_callback=None,
        delete_callback=None,
        config_saved_callback=None,
        script_service=None,
    ):
        super().__init__()
        assert "display_name" in script_data, "[widgets] 脚本配置缺少 display_name 字段"
        assert "script_type" in script_data, "[widgets] 脚本配置缺少 script_type 字段"
        self.display_name = script_data["display_name"]
        self.script_type = script_data["script_type"]
        self.script_path = script_data.get("script_path", "")
        self.dungeon_btn = None
        self._selected_dungeon = None  # 一级副本名（None 表示未选择）
        self._selected_sequence = None  # 二级序列名
        self.enabled = (
            True  # 纯内存态：每次启动默认全开，仅当次会话可临时关（不读 config）
        )
        self._state_callback = None  # 状态变化回调，由 MainWindow 注入
        self._reorder_callback = reorder_callback  # 拖拽重排回调，由 MainWindow 注入
        self._delete_callback = delete_callback  # 删除回调，由 MainWindow 注入
        self._config_saved_callback = (
            config_saved_callback  # 配置弹窗保存成功回调，由 MainWindow 注入
        )
        self._script_service = (
            script_service  # 配置弹窗共享的 ScriptService（None 时弹窗自建）
        )
        self._drag_start_pos = None  # 拖拽起点（在卡片空白区按下时记录）
        self._sequence_options_map = sequence_options_map or {}  # 副本名 → 二级选项列表
        self._dungeon_options = dungeon_options or []  # 一级副本列表

        self.setFrameShape(QFrame.NoFrame)
        self.setObjectName("ScriptItem")
        self.setAcceptDrops(True)
        self._apply_card_style()
        # 卡片阴影，营造悬浮层次感
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(18)
        shadow.setColor(QColor(15, 23, 42, 28))
        shadow.setOffset(0, 2)
        self.setGraphicsEffect(shadow)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        # 脚本图标：external 脚本用 exe 自带图标，其余（如 python）用默认图标
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(28, 28)
        self.icon_label.setStyleSheet(
            "padding: 0; background: transparent; border: none;"
        )
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setCursor(Qt.PointingHandCursor)
        self.icon_label.mousePressEvent = self._icon_mouse_press
        self._refresh_icon(script_data)
        layout.addWidget(self.icon_label)

        # 脚本名称：宽度由 MainWindow._sync_title_widths() 流程统一决定（避免硬编码漂移）。
        # 构造期先按默认 ``TITLE_DEFAULT_WIDTH`` 占位，load_scripts 末尾会刷新。
        self.title_label = QLabel(self.display_name)
        # 脚本名 chip：字号用像素单位（与 QSS font-size 一致渲染），见 theme.make_font
        title_font = theme.make_font(size=theme.FONT_SIZE_BODY)
        self.title_label.setFont(title_font)
        # 脚本名：透明底 + 雾蓝边框 + 圆角 8（hover 时由 enter/leaveEvent 变色，与副本按钮统一）
        self._STYLE_TITLE_NORMAL = (
            f"color: {theme.DARK_BLUE}; background: transparent;"
            f" border: 1px solid {theme.BORDER}; border-radius: 8px;"
            " padding: 4px 10px;"
        )
        self._STYLE_TITLE_HOVER = (
            f"color: {theme.BLUE}; background: transparent;"
            f" border: 1px solid {theme.BLUE}; border-radius: 8px;"
            " padding: 4px 10px;"
        )
        self._STYLE_TITLE_DISABLED = (
            f"color: {theme.TEXT_FAINT}; background: transparent;"
            f" border: 1px solid {theme.BORDER_SOFT}; border-radius: 8px;"
            " padding: 4px 10px;"
        )
        self.title_label.setStyleSheet(self._STYLE_TITLE_NORMAL)
        # 脚本名 hover 变色：与副本按钮 hover 效果一致（边框+文字变钢蓝）
        self.title_label.enterEvent = self._title_enter
        self.title_label.leaveEvent = self._title_leave
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setMinimumWidth(TITLE_MIN_WIDTH)
        self._title_width = TITLE_DEFAULT_WIDTH
        # QLabel 无 setElideMode，用 QFontMetrics 手动截断超长名字
        self.title_label.setText(
            QFontMetrics(title_font).elidedText(
                self.display_name, Qt.TextElideMode.ElideRight, self._title_width
            )
        )
        self.title_label.setCursor(Qt.PointingHandCursor)
        self.title_label.mousePressEvent = self._title_mouse_press
        layout.addWidget(self.title_label)

        # 左侧弹性空间 + 副本按钮（居中） + 右侧弹性空间
        # 无副本按钮时两块 stretch 合并为一段，脚本名靠左、开关靠右
        layout.addStretch(1)  # 左 spacer（index 2）

        # 副本选择按钮（点击弹出级联菜单：一级 → 二级从右侧弹出）
        self.dungeon_btn = None
        # 恢复上次选择（仅当副本在选项列表中时）
        if (
            saved_state
            and saved_state.get("dungeon")
            and saved_state["dungeon"] in self._dungeon_options
        ):  # optional: 保存状态可能没有选择过副本
            self._selected_dungeon = saved_state["dungeon"]
            if saved_state.get("sequence"):  # optional: 保存状态可能没有选择过序列
                self._selected_sequence = saved_state["sequence"]
        self._ensure_dungeon_button()
        layout.addStretch(1)  # 右 spacer（副本按钮在两个等宽 stretch 之间 = 居中）

        # 开关（自定义滑动开关）
        self.toggle = ToggleSwitch(checked=self.enabled)
        self.toggle.toggled.connect(self._on_toggle_changed)
        self._update_switch_style()
        layout.addWidget(self.toggle)

    def _on_delete_clicked(self):
        """点击删除按钮，通知删除本脚本"""
        if self._delete_callback:
            self._delete_callback(self.display_name)

    def _show_config_dialog(self):
        """打开单脚本配置弹窗；保存成功(accept)后通知 MainWindow 应用 patch 并写盘。

        弹窗不再自行写 config.yml——表单数据通过 pending_changes 返回，由 MainWindow
        统一在内存更新 all_config_data 后通过 ChainService 一次性落盘。
        """
        dialog = SingleScriptConfigDialog(
            self.display_name,
            self.script_path,
            self,
            script_service=self._script_service,
        )
        dialog.delete_requested.connect(self._on_delete_clicked)
        if dialog.exec() == QDialog.Accepted and self._config_saved_callback:
            assert dialog.pending_changes is not None, (
                "[widgets] 弹窗 accept 但 pending_changes 为空"
            )
            changes = dialog.pending_changes
            new_display_name = dialog.saved_display_name
            if new_display_name != self.display_name:
                self.display_name = new_display_name
                self._refresh_title()
            self._config_saved_callback(changes)

    def _refresh_title(self) -> None:
        """按当前 display_name + _title_width 刷新卡片标题（含超长截断）。

        ``_title_width`` 由 :meth:`MainWindow._sync_title_widths` 同步设置，
        所有 ScriptItem 一致；改名后调用本方法可立即以新宽度重新截断。
        """
        title_font = self.title_label.font()
        self.title_label.setText(
            QFontMetrics(title_font).elidedText(
                self.display_name, Qt.TextElideMode.ElideRight, self._title_width
            )
        )

    def _refresh_icon(self, script_data: dict) -> None:
        """按脚本数据刷新卡片图标（external 用 exe 自带，否则默认），构造与改名后调用。

        - 图标设置统一延迟到事件循环空闲（window.show() 首帧渲染之后）执行：
          QIcon.pixmap() 首次栅格化是 Qt 进程级一次性成本（~80ms），若在卡片构造时
          同步执行会阻塞首帧显示；延迟后窗口先显示、图标随后填充，用户无感。
        - external 的 exe 图标：先用默认图标占位，再提交 ``QThreadPool`` 后台线程
          用纯 Win32 提取（避开 QFileIconProvider 的 COM 限制），主线程只做轻量转换。
        """
        self._pending_script_data = script_data
        QTimer.singleShot(0, self, self._apply_icon)

    def _apply_icon(self) -> None:
        """事件循环空闲时真正设置图标（item 已销毁则跳过，如窗口快速关闭）。"""
        with contextlib.suppress(RuntimeError):
            script_data = self._pending_script_data
            size = self.icon_label.width()
            dpr = self.devicePixelRatioF()
            source = icons.get_icon_source(script_data)
            if source and os.path.isfile(source):
                # 图标源（external 的 exe）存在：先用默认图标占位，再提交后台线程
                # 提取真实图标。QIcon.pixmap(QSize, dpr) 会自动按 dpr 选高清表示，
                # 不需要再手动 setDevicePixelRatio。
                ph = icons._default_icon().pixmap(QSize(size, size), dpr)
                self.icon_label.setPixmap(ph)
                icons._schedule_icon_load(self, script_data)
            else:
                ph = icons.get_script_icon(script_data).pixmap(QSize(size, size), dpr)
                self.icon_label.setPixmap(ph)

    def _on_icon_loaded(self, source: str, qimg) -> None:
        """后台线程提取完成（主线程执行）：QImage → QPixmap 并设置，同时缓存。

        转换/缓存逻辑集中在 ``icons.on_script_icon_loaded``，这里只负责把结果
        设到本卡片的图标 label；item 已被销毁（如窗口快速关闭）时忽略该次回调。
        """
        with contextlib.suppress(RuntimeError):
            # item 已被销毁（如窗口快速关闭）时忽略该次回调（setPixmap 会抛错）
            icons.on_script_icon_loaded(self.icon_label, source, qimg)

    def _icon_mouse_press(self, event):
        """左键点击图标即启动脚本。"""
        if event.button() == Qt.LeftButton:
            self._open_script()
        QLabel.mousePressEvent(self.icon_label, event)

    def _open_script(self):
        """打开/运行该脚本：python 用解释器跑，external 解析后 startfile。"""
        if self.script_type == "python":
            resolved = resolve_script_path(self.script_path)
            if not resolved or not os.path.isfile(resolved):
                _styled_msg_box(
                    self,
                    QMessageBox.Warning,
                    "提示",
                    f"找不到脚本文件：\n{self.script_path or '(未设置路径)'}",
                ).exec()
                return
            command, cwd, env = build_script_command(["--script", resolved])
            try:
                subprocess.Popen(command, cwd=cwd, env=env)
            except OSError as e:
                _styled_msg_box(
                    self, QMessageBox.Warning, "提示", f"无法运行脚本：\n{e}"
                ).exec()
            return

        # external 脚本：解析出 exe 并启动
        try:
            exe_path = get_script_path(self.display_name)
        except AssertionError as e:
            _styled_msg_box(
                self, QMessageBox.Warning, "提示", f"无法打开脚本：\n{e}"
            ).exec()
            return
        safe_startfile(self, exe_path, "无法打开脚本")

    def _title_mouse_press(self, event):
        """左键点击脚本名称打开配置弹窗。"""
        if event.button() == Qt.LeftButton:
            self._show_config_dialog()
        QLabel.mousePressEvent(self.title_label, event)

    def _title_enter(self, _event):
        """鼠标进入脚本名区域：边框/文字变钢蓝，与副本按钮 hover 效果统一。"""
        if self.enabled:
            self.title_label.setStyleSheet(self._STYLE_TITLE_HOVER)

    def _title_leave(self, _event):
        """鼠标离开脚本名区域：恢复默认样式。"""
        if self.enabled:
            self.title_label.setStyleSheet(self._STYLE_TITLE_NORMAL)

    def _show_dungeon_menu(self):
        """点击副本按钮，弹出级联菜单"""
        menu = QMenu(self)
        menu.setStyleSheet(_MENU_STYLE)

        for dungeon_name in self._dungeon_options:
            if dungeon_name == "未选择":
                action = menu.addAction(dungeon_name)
                action.triggered.connect(
                    lambda checked, dn=dungeon_name: self._on_dungeon_selected(dn)
                )
                menu.addSeparator()
                continue

            seq_options = self._sequence_options_map.get(
                dungeon_name, []
            )  # optional: 副本可能没有二级选项
            if seq_options:
                # 有二级选项 → 子菜单（从右侧弹出）
                submenu = menu.addMenu(dungeon_name)
                for display_name, actual_value in seq_options:
                    sub_action = submenu.addAction(display_name)
                    sub_action.triggered.connect(
                        lambda checked, dn=dungeon_name, sq=actual_value: (
                            self._on_dungeon_selected(dn, sq)
                        )
                    )
            else:
                # 无二级选项 → 直接选择
                action = menu.addAction(dungeon_name)
                action.triggered.connect(
                    lambda checked, dn=dungeon_name: self._on_dungeon_selected(dn)
                )

        # 在按钮下方弹出
        menu.exec(self.dungeon_btn.mapToGlobal(self.dungeon_btn.rect().bottomLeft()))

    def _dungeon_btn_text(self):
        """根据已选的一级/二级返回按钮显示文字"""
        if not self._selected_dungeon:
            return "选择副本"
        if self._selected_sequence:
            display_name = get_display_name(
                self._sequence_options_map,
                self._selected_dungeon,
                self._selected_sequence,
            )
            return f"{self._selected_dungeon} > {display_name}"
        return self._selected_dungeon

    def _on_dungeon_selected(self, dungeon_name, sequence=None):
        """选择副本后的回调"""
        if dungeon_name == "未选择":
            self._selected_dungeon = None
            self._selected_sequence = None
        else:
            self._selected_dungeon = dungeon_name
            self._selected_sequence = sequence
        self.dungeon_btn.setText(self._dungeon_btn_text())
        self._on_state_changed()

    def get_state(self) -> dict:
        """获取当前 UI 状态，用于持久化"""
        state = {}
        if self._selected_dungeon:
            state["dungeon"] = self._selected_dungeon
            if self._selected_sequence:
                state["sequence"] = self._selected_sequence
        return state

    def set_state_callback(self, callback):
        """注入状态变化回调"""
        self._state_callback = callback

    def _on_state_changed(self, *args):
        """子控件值变化时触发回调"""
        if self._state_callback:
            self._state_callback()

    def get_selected_dungeon(self):
        return self._selected_dungeon

    def get_sequence(self):
        return self._selected_sequence

    def _ensure_dungeon_button(self):
        """根据 script_type 与副本选项，确保副本按钮存在且可见性正确。

        - external 且有真实副本选项 → 显示，文本反映已选副本；
        - python 或无副本 → 隐藏（并清除已选副本，避免残留）。
        """
        has_real_dungeons = (
            self._dungeon_options
            and len(self._dungeon_options) > 1
            and not (
                len(self._dungeon_options) == 1 and self._dungeon_options[0] == "未选择"
            )
        )
        should_show = self.script_type != "python" and has_real_dungeons
        if not should_show:
            if self.dungeon_btn is not None:
                self.dungeon_btn.setVisible(False)
            self._selected_dungeon = None
            self._selected_sequence = None
            return

        if self.dungeon_btn is None:
            self.dungeon_btn = QPushButton("选择副本")
            self.dungeon_btn.setCursor(Qt.PointingHandCursor)
            self.dungeon_btn.setFixedHeight(26)
            self.dungeon_btn.setStyleSheet(_DUNGEON_BTN_QSS)
            # 固定宽度：所有卡片副本条等宽，右边缘对齐
            self.dungeon_btn.setFixedWidth(220)
            self.dungeon_btn.clicked.connect(self._show_dungeon_menu)
            # 追加到左 spacer 之后、右 spacer（__init__ 随后添加）之前 → 居中
            self.layout().insertWidget(self.layout().count(), self.dungeon_btn)
        self.dungeon_btn.setVisible(True)
        if self._selected_dungeon:
            self.dungeon_btn.setText(self._dungeon_btn_text())

    def sync_from_script_data(self, script_data: dict) -> None:
        """配置弹窗保存后，从最新 script 数据同步内存态（路径、类型、副本按钮）。"""
        assert "script_path" in script_data, "[widgets] 同步缺少 script_path 字段"
        assert "script_type" in script_data, "[widgets] 同步缺少 script_type 字段"
        self.script_path = script_data["script_path"]
        self.script_type = script_data["script_type"]
        self._refresh_icon(script_data)
        self._ensure_dungeon_button()

    def _toggle(self):
        self.enabled = not self.enabled
        self._update_switch_style()

    def _on_toggle_changed(self, checked):
        """ToggleSwitch 状态变化回调"""
        self.enabled = checked
        self._update_switch_style()

    def _apply_card_style(self, muted=False):
        """卡片外观：启用=白底柔边 + 蓝 hover；停用=灰底浅边"""
        if muted:
            self.setStyleSheet(
                theme.card_qss(
                    background=theme.BG_MUTED,
                    border=theme.BORDER_SOFT,
                    hover_border=theme.DISABLED,
                )
            )
        else:
            self.setStyleSheet(
                theme.card_qss(
                    background=theme.BG_CARD,
                    border=theme.BORDER,
                    hover_border=theme.BLUE,
                )
            )

    def _update_switch_style(self):
        self.toggle.setChecked(self.enabled)
        self._apply_card_style(not self.enabled)
        self.title_label.setStyleSheet(
            self._STYLE_TITLE_NORMAL if self.enabled else self._STYLE_TITLE_DISABLED
        )

    # ---- 拖拽重排（整个卡片空白区域可发起，子控件点击不受影响） ----
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_start_pos is not None and (event.buttons() & Qt.LeftButton):
            if (
                event.pos() - self._drag_start_pos
            ).manhattanLength() >= QApplication.startDragDistance():
                self._drag_start_pos = None
                self._start_drag()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_start_pos = None
        super().mouseReleaseEvent(event)

    def _start_drag(self):
        mime = QMimeData()
        mime.setText(self.display_name)
        mime.setData(DRAG_MIME, self.display_name.encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(self.grab())
        drag.exec(Qt.MoveAction)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(DRAG_MIME) and self._reorder_callback:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if not (event.mimeData().hasFormat(DRAG_MIME) and self._reorder_callback):
            event.ignore()
            return
        src_name = bytes(event.mimeData().data(DRAG_MIME)).decode("utf-8")
        if src_name != self.display_name:
            self._reorder_callback(src_name, self.display_name)
        event.acceptProposedAction()
