"""自定义控件：ToggleSwitch 滑动开关与 ScriptItem 脚本卡片。"""

import os
import subprocess

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QWidget,
)

from src.config.dungeon_config import get_display_name
from src.config.subscript import get_config_path, get_script_path
from src.gui.controls import make_icon_button, make_secondary_button
from src.gui.dialogs import SingleScriptConfigDialog
from src.gui.runner import build_script_command
from src.gui.utils import _safe_startfile, _styled_msg_box

# 拖拽重排使用的自定义 MIME 类型（仅在本应用内传递脚本 display_name）
DRAG_MIME = "application/x-onedragon-script"

# 弹出菜单统一样式：白底深字，避免深色系统主题下文字不可读
_MENU_STYLE = """
QMenu {
    border: 1px solid #d0d0d0;
    border-radius: 4px;
    background: white;
    padding: 4px;
    font-size: 11px;
}
QMenu::item {
    padding: 4px 20px 4px 12px;
    border-radius: 3px;
    color: #1f2937;
}
QMenu::item:selected {
    background-color: #3b82f6;
    color: white;
}
QMenu::item:disabled {
    color: #c0c4cc;
}
QMenu::separator {
    height: 1px;
    background: #e0e0e0;
    margin: 4px 8px;
}
"""


class ToggleSwitch(QWidget):
    """自定义滑动开关（圆角轨道 + 圆形滑块）"""

    toggled = Signal(bool)

    TRACK_ON = "#3b82f6"
    TRACK_OFF = "#cbd5e1"
    KNOB = "#ffffff"

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
        self._drag_start_pos = None  # 拖拽起点（仅在手柄上按下时记录）
        self._sequence_options_map = sequence_options_map or {}  # 副本名 → 二级选项列表
        self._dungeon_options = dungeon_options or []  # 一级副本列表

        self.setFrameShape(QFrame.NoFrame)
        self.setObjectName("ScriptItem")
        self.setAcceptDrops(True)
        self._apply_card_style()
        # 卡片阴影，营造悬浮层次感
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(14)
        shadow.setColor(QColor(15, 23, 42, 22))
        shadow.setOffset(0, 3)
        self.setGraphicsEffect(shadow)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        # 拖拽手柄（仅此处可发起拖拽，避免与开关/副本/配置按钮冲突）
        self.handle = QLabel("⠿")
        self.handle.setFixedSize(20, 20)
        self.handle.setAlignment(Qt.AlignCenter)
        self.handle.setCursor(Qt.OpenHandCursor)
        self.handle.setStyleSheet("color: #c4c9d4; font-size: 16px;")
        self.handle.mousePressEvent = self._handle_mouse_press
        self.handle.mouseMoveEvent = self._handle_mouse_move
        self.handle.mouseReleaseEvent = self._handle_mouse_release
        layout.addWidget(self.handle)

        # 脚本名称（固定宽度：所有卡片脚本名区等宽，副本按钮居中后才跨卡对齐）
        self.title_label = QLabel(self.display_name)
        title_font = QFont("Microsoft YaHei", 11)
        self.title_label.setFont(title_font)
        self.title_label.setStyleSheet("color: #1f2937;")
        self.title_label.setFixedWidth(60)
        # QLabel 无 setElideMode，用 QFontMetrics 手动截断超长名字
        self.title_label.setText(
            QFontMetrics(title_font).elidedText(
                self.display_name, Qt.TextElideMode.ElideRight, 110
            )
        )
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

        # 操作菜单按钮：把删除 / 打开脚本 / 打开配置 / 配置 全部收进 ⋮，避免卡片按钮过多
        self.overflow_btn = make_icon_button(
            "⋮",
            accent="#3b82f6",
            normal_color="#9aa3b2",
            font_size=18,
            hover_bg="#eef2f7",
            pressed_bg="#e2e8f0",
        )
        self.overflow_btn.clicked.connect(self._show_overflow_menu)
        layout.addWidget(self.overflow_btn)

    def _show_overflow_menu(self):
        """点击 ⋮ 弹出操作菜单（不阻塞：菜单内动作才触发实际操作）。"""
        menu = self._build_overflow_menu()
        menu.exec(self.overflow_btn.mapToGlobal(self.overflow_btn.rect().bottomRight()))

    def _build_overflow_menu(self):
        """构造操作菜单：打开脚本 / 打开脚本配置 / 分隔线 / 配置 / 删除。"""
        menu = QMenu(self)
        menu.setStyleSheet(_MENU_STYLE)

        open_action = menu.addAction("启动脚本")
        open_action.triggered.connect(self._open_script)

        config_file_action = menu.addAction("配置文件")
        config_file_action.triggered.connect(self._open_script_config)

        setting_action = menu.addAction("脚本参数")
        setting_action.triggered.connect(self._show_config_dialog)

        delete_action = menu.addAction("删除脚本")
        if self._delete_callback:
            delete_action.triggered.connect(self._on_delete_clicked)
        else:
            delete_action.setEnabled(False)
        return menu

    def _on_delete_clicked(self):
        """点击删除按钮，通知删除本脚本"""
        if self._delete_callback:
            self._delete_callback(self.display_name)

    def _show_config_dialog(self):
        """打开单脚本配置弹窗；保存成功(accept)后通知 MainWindow 重新吸收磁盘改动"""
        dialog = SingleScriptConfigDialog(self.display_name, self.script_path, self)
        if dialog.exec() == QDialog.Accepted and self._config_saved_callback:
            self._config_saved_callback(self.display_name)

    def _open_script(self):
        """打开/运行该脚本。
        - python 脚本：用 python 解释器直接运行（不阻塞 GUI）；
        - external 脚本：用 get_script_path 解析出 exe 并以 startfile 启动。
        """
        if self.script_type == "python":
            if not self.script_path or not os.path.isfile(self.script_path):
                _styled_msg_box(
                    self,
                    QMessageBox.Warning,
                    "提示",
                    f"找不到脚本文件：\n{self.script_path or '(未设置路径)'}",
                ).exec()
                return
            # 命令构造（含 frozen/非 frozen 判断）全部委托给 build_script_command，
            # 这里只管拿 cmd list 去 spawn，不再关心运行环境。
            command, cwd, env = build_script_command(["--script", self.script_path])
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
        _safe_startfile(self, exe_path, "无法打开脚本")

    def _open_script_config(self):
        """打开该脚本的配置文件（文本）。
        - python 脚本：无独立配置文件，直接打开其 .py 源文件；
        - external 脚本：用 get_config_path 解析并打开其内部 config 文本文件；
          未适配或文件缺失时给出清晰提示。
        """
        if self.script_type == "python":
            if not self.script_path or not os.path.isfile(self.script_path):
                _styled_msg_box(
                    self,
                    QMessageBox.Warning,
                    "提示",
                    f"找不到脚本文件：\n{self.script_path or '(未设置路径)'}",
                ).exec()
                return
            _safe_startfile(self, self.script_path, "无法打开脚本文件")
            return

        # external 脚本：解析并打开内部 config 文件
        try:
            config_path = get_config_path(self.display_name)
        except AssertionError as e:
            _styled_msg_box(
                self,
                QMessageBox.Warning,
                "提示",
                f"该脚本暂未适配配置文件，无法打开：\n{e}",
            ).exec()
            return
        _safe_startfile(self, config_path, "无法打开配置文件")

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
            self.dungeon_btn = make_secondary_button(
                "选择副本", radius=8, padding="0 10px", font_size=11
            )
            # 固定宽度：所有卡片副本条等宽，右边缘对齐
            self.dungeon_btn.setFixedWidth(220)
            # 文本居中；按钮本身由左右等宽 stretch 夹在中间实现居中
            self.dungeon_btn.setStyleSheet(
                self.dungeon_btn.styleSheet() + "\nQPushButton { text-align: center; }"
            )
            self.dungeon_btn.clicked.connect(self._show_dungeon_menu)
            # 插入到左 spacer(index 2) 与右 spacer(即将在 index 4) 之间 → 居中
            self.layout().insertWidget(3, self.dungeon_btn)
        self.dungeon_btn.setVisible(True)
        if self._selected_dungeon:
            self.dungeon_btn.setText(self._dungeon_btn_text())

    def sync_from_script_data(self, script_data: dict) -> None:
        """配置弹窗保存后，从最新 script 数据同步内存态（路径、类型、副本按钮）。"""
        assert "script_path" in script_data, "[widgets] 同步缺少 script_path 字段"
        assert "script_type" in script_data, "[widgets] 同步缺少 script_type 字段"
        self.script_path = script_data["script_path"]
        self.script_type = script_data["script_type"]
        self._ensure_dungeon_button()

    def _toggle(self):
        self.enabled = not self.enabled
        self._update_switch_style()

    def _on_toggle_changed(self, checked):
        """ToggleSwitch 状态变化回调"""
        self.enabled = checked
        self._update_switch_style()

    def _apply_card_style(self, muted=False):
        """卡片外观：启用=白底蓝边；停用=灰底浅边"""
        if muted:
            self.setStyleSheet("""
                QFrame#ScriptItem {
                    background-color: #f7f8fa;
                    border: 1px solid #eceef2;
                    border-radius: 12px;
                }
                QFrame#ScriptItem:hover { border-color: #cbd5e1; }
            """)
        else:
            self.setStyleSheet("""
                QFrame#ScriptItem {
                    background-color: #ffffff;
                    border: 1px solid #e6e9f0;
                    border-radius: 12px;
                }
                QFrame#ScriptItem:hover { border-color: #3b82f6; }
            """)

    def _update_switch_style(self):
        self.toggle.setChecked(self.enabled)
        self._apply_card_style(not self.enabled)
        if self.enabled:
            self.title_label.setStyleSheet("color: #1f2937;")
        else:
            self.title_label.setStyleSheet("color: #9ca3af;")

    # ---- 拖拽重排（仅手柄可发起） ----
    def _handle_mouse_press(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start_pos = event.pos()
        QLabel.mousePressEvent(self.handle, event)

    def _handle_mouse_move(self, event):
        if self._drag_start_pos is None or not (event.buttons() & Qt.LeftButton):
            return
        if (
            event.pos() - self._drag_start_pos
        ).manhattanLength() < QApplication.startDragDistance():
            return
        self._drag_start_pos = None
        self._start_drag()

    def _handle_mouse_release(self, event):
        self._drag_start_pos = None
        QLabel.mouseReleaseEvent(self.handle, event)

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
