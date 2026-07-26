import argparse
import copy
import json
import logging
import os
import subprocess
import sys
from datetime import datetime

import yaml
from PySide6.QtCore import QMimeData, Qt, QThread, Signal
from PySide6.QtGui import QColor, QDrag, QFont, QIntValidator, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.config.dungeon_config import (
    get_display_name,
    load_dungeon_map,
    parse_dungeon_config,
    restore_sequence_type,
)
from src.config.init_config import config_workflow, need_config_workflow
from src.config.set_config import set_config
from src.utils import (
    get_config_yml_path_under_root,
    get_path_under_onedragon,
    get_root_dir,
    get_weekly_timeouts_yml_path_under_root,
    safe_path_join,
)

logger = logging.getLogger(__name__)

# 拖拽重排使用的自定义 MIME 类型（仅在本应用内传递脚本 display_name）
_DRAG_MIME = "application/x-onedragon-script"

# ---- UI 状态持久化 ----
_STATE_FILE = safe_path_join(get_root_dir(), "config", "gui_state.json")


def _load_ui_state() -> dict:
    """读取上次保存的 UI 状态"""
    if os.path.exists(_STATE_FILE):
        with open(_STATE_FILE, encoding='utf-8') as f:
            return json.load(f)
    return {}


def _save_ui_state(state: dict):
    """保存 UI 状态"""
    with open(_STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def get_week_num() -> int:
    """返回星期数字：0周一 ~ 6周日"""
    return datetime.now().weekday()


def _build_chain_command(chain_name: str) -> tuple:
    """构造 ScriptChainer 启动命令与运行目录（GUI 与无界面模式共用）"""
    cwd = get_path_under_onedragon("src")
    command = [
        sys.executable,
        "-m",
        "script_chainer.win_exe.launcher",
        "--onedragon",
        "--chain",
        chain_name,
    ]
    return command, cwd


class ScriptChainRunner(QThread):
    """后台运行 ScriptChainer"""
    finished_signal = Signal(int)

    def __init__(self, chain_name="88"):
        super().__init__()
        self.chain_name = chain_name

    def run(self):
        command, cwd = _build_chain_command(self.chain_name)
        res = subprocess.run(command, cwd=cwd)
        self.finished_signal.emit(res.returncode)


class SingleScriptConfigDialog(QDialog):
    """单个脚本的配置弹窗（路径选择 + 每周超时时间）"""
    FILE_FILTER = "可执行文件 Executable files (*.exe *.bat *.py);;所有文件 All files (*.*)"
    LABEL_WIDTH = 80

    def __init__(self, script_name, script_path="", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"配置 {script_name}")
        self.resize(680, 280)
        self.setStyleSheet("background-color: #f7f8fa;")

        self.script_name = script_name
        self.script_path = script_path
        self._result_path = script_path
        self._result_timeouts = []

        self.init_ui()
        self.load_data()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        row1 = QHBoxLayout()
        row1.setSpacing(8)

        label = QLabel("脚本路径:")
        label.setFont(QFont("Microsoft YaHei", 10))
        label.setFixedWidth(self.LABEL_WIDTH)
        label.setStyleSheet("color: #303030;")

        self.path_input = QLineEdit(self)
        self.path_input.setFont(QFont("Microsoft YaHei", 10))
        self.path_input.setText(self.script_path)
        self.path_input.setStyleSheet("""
            QLineEdit {
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 4px 8px;
                background: white;
                font-size: 10px;
            }
            QLineEdit:focus {
                border-color: #0078D4;
                outline: none;
            }
        """)

        self.browse_btn = QPushButton("选择")
        self.browse_btn.setFixedHeight(28)
        self.browse_btn.setFont(QFont("Microsoft YaHei", 10))
        self.browse_btn.setStyleSheet("""
            QPushButton {
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                background: white;
                font-size: 10px;
                color: #303030;
                padding: 0 16px;
            }
            QPushButton:hover { border-color: #a0a0a0; }
            QPushButton:pressed { border-color: #0078D4; }
        """)
        self.browse_btn.clicked.connect(self.browse_file)

        row1.addWidget(label)
        row1.addWidget(self.path_input)
        row1.addWidget(self.browse_btn)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(8)

        timeout_label = QLabel("超时(秒):")
        timeout_label.setFont(QFont("Microsoft YaHei", 10))
        timeout_label.setFixedWidth(self.LABEL_WIDTH)
        timeout_label.setStyleSheet("color: #303030;")
        row2.addWidget(timeout_label)

        day_names = ["一", "二", "三", "四", "五", "六", "日"]
        self.timeout_inputs = []

        for day_idx in range(7):
            day_label = QLabel(f"周{day_names[day_idx]}")
            day_label.setFont(QFont("Microsoft YaHei", 9))
            day_label.setStyleSheet("color: #606060;")
            day_label.setFixedWidth(30)

            lineedit = QLineEdit(self)
            lineedit.setFont(QFont("Microsoft YaHei", 10))
            lineedit.setValidator(QIntValidator(0, 86400, self))
            lineedit.setFixedWidth(70)
            lineedit.setStyleSheet("""
                QLineEdit {
                    border: 1px solid #d0d0d0;
                    border-radius: 4px;
                    padding: 3px 6px;
                    background: white;
                    font-size: 9px;
                    text-align: center;
                }
                QLineEdit:focus {
                    border-color: #0078D4;
                    outline: none;
                }
            """)

            row2.addWidget(day_label)
            row2.addWidget(lineedit)
            self.timeout_inputs.append(lineedit)

        row2.addStretch()
        layout.addLayout(row2)

        btn_layout = QHBoxLayout()
        self.save_btn = QPushButton("保存")
        self.save_btn.setFixedHeight(32)
        self.save_btn.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        self.save_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                            stop:0 #4f8cff, stop:1 #3b82f6);
                color: white;
                border: none;
                border-radius: 6px;
                padding: 0 24px;
                font-size: 10px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                            stop:0 #5b96ff, stop:1 #2f6fed);
            }
            QPushButton:pressed { background: #2f6fed; }
        """)
        self.save_btn.clicked.connect(self.save_data)

        cancel_btn = QPushButton("取消")
        cancel_btn.setFixedHeight(32)
        cancel_btn.setFont(QFont("Microsoft YaHei", 10))
        cancel_btn.setStyleSheet("""
            QPushButton {
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                background: white;
                font-size: 10px;
                color: #303030;
                padding: 0 24px;
            }
            QPushButton:hover { border-color: #3b82f6; color: #3b82f6; }
        """)
        cancel_btn.clicked.connect(self.reject)

        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(self.save_btn)
        layout.addLayout(btn_layout)

    def load_data(self):
        weekly_timeouts_path = get_weekly_timeouts_yml_path_under_root()
        weekly_timeouts_map = {}
        if os.path.exists(weekly_timeouts_path):
            with open(weekly_timeouts_path, encoding='utf-8') as f:
                weekly_timeouts_map = yaml.safe_load(f) or {}

        timeouts = weekly_timeouts_map.get(self.script_name, [0] * 7)
        if len(timeouts) < 7:
            timeouts.extend([0] * (7 - len(timeouts)))

        for idx, le in enumerate(self.timeout_inputs):
            le.setText(str(timeouts[idx]))

    def browse_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择脚本文件", "", self.FILE_FILTER)
        if file_path:
            self.path_input.setText(os.path.normpath(file_path))

    def save_data(self):
        path_val = self.path_input.text().strip()
        if not path_val:
            QMessageBox.warning(self, "警告", "脚本路径为空，可能会导致运行问题！")
            return

        timeouts = []
        for le in self.timeout_inputs:
            val = int(le.text().strip())
            timeouts.append(val)

        config_path = get_config_yml_path_under_root()
        with open(config_path, encoding='utf-8') as f:
            config_data = yaml.safe_load(f)

        for script in config_data.get('script_list', []):
            if script.get('display_name') == self.script_name:
                script['script_path'] = path_val
                break

        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(config_data, f, allow_unicode=True, sort_keys=False)

        weekly_timeouts_path = get_weekly_timeouts_yml_path_under_root()
        weekly_timeouts_map = {}
        if os.path.exists(weekly_timeouts_path):
            with open(weekly_timeouts_path, encoding='utf-8') as f:
                weekly_timeouts_map = yaml.safe_load(f) or {}
        weekly_timeouts_map[self.script_name] = timeouts

        with open(weekly_timeouts_path, 'w', encoding='utf-8') as f:
            yaml.dump(weekly_timeouts_map, f, allow_unicode=True, sort_keys=False)

        QMessageBox.information(self, "成功", "配置已保存！")
        self.accept()


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

    def __init__(self, script_data, dungeon_options=None, sequence_options_map=None,
                 show_sequence=False, saved_state=None, reorder_callback=None):
        super().__init__()
        assert 'display_name' in script_data, "[gui_launcher] 脚本配置缺少 display_name 字段"
        assert 'script_type' in script_data, "[gui_launcher] 脚本配置缺少 script_type 字段"
        self.display_name = script_data['display_name']
        self.script_type = script_data['script_type']
        self.script_path = script_data.get('script_path', '')
        self.dungeon_btn = None
        self._selected_dungeon = None   # 一级副本名（None 表示未选择）
        self._selected_sequence = None  # 二级序列名
        self.enabled = True  # 纯内存态：每次启动默认全开，仅当次会话可临时关（不读 config）
        self._state_callback = None  # 状态变化回调，由 MainWindow 注入
        self._reorder_callback = reorder_callback  # 拖拽重排回调，由 MainWindow 注入
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

        # 脚本名称
        self.title_label = QLabel(self.display_name)
        self.title_label.setFont(QFont("Microsoft YaHei", 11))
        self.title_label.setStyleSheet("color: #1f2937;")
        layout.addWidget(self.title_label, stretch=1)

        # 副本选择按钮（点击弹出级联菜单：一级 → 二级从右侧弹出）
        has_real_dungeons = (
            dungeon_options
            and len(dungeon_options) > 1
            and not (len(dungeon_options) == 1 and dungeon_options[0] == "未选择")
        )
        if self.script_type != 'python' and has_real_dungeons:
            self.dungeon_btn = QPushButton("选择副本")
            self.dungeon_btn.setFixedHeight(28)
            self.dungeon_btn.setMinimumWidth(160)
            self.dungeon_btn.setCursor(Qt.PointingHandCursor)
            self.dungeon_btn.setStyleSheet("""
                QPushButton {
                    border: 1px solid #d0d0d0;
                    border-radius: 8px;
                    padding: 0 10px;
                    background: white;
                    font-size: 11px;
                    color: #303030;
                    text-align: center;
                }
                QPushButton:hover { border-color: #a0a0a0; }
                QPushButton:pressed { border-color: #0078D4; }
            """)
            self.dungeon_btn.clicked.connect(self._show_dungeon_menu)
            layout.addWidget(self.dungeon_btn)

            # 恢复上次选择（仅当副本在选项列表中时）
            if saved_state and saved_state.get('dungeon') and saved_state['dungeon'] in self._dungeon_options:  # optional: 保存状态可能没有选择过副本
                self._selected_dungeon = saved_state['dungeon']
                if saved_state.get('sequence'):  # optional: 保存状态可能没有选择过序列
                    self._selected_sequence = saved_state['sequence']
                self.dungeon_btn.setText(self._dungeon_btn_text())

        # 开关（自定义滑动开关）
        self.toggle = ToggleSwitch(checked=self.enabled)
        self.toggle.toggled.connect(self._on_toggle_changed)
        self._update_switch_style()
        layout.addWidget(self.toggle)

        # 配置按钮（最右边，圆形图标按钮）
        self.config_btn = QPushButton("⚙")
        self.config_btn.setFixedSize(30, 30)
        self.config_btn.setCursor(Qt.PointingHandCursor)
        self.config_btn.setStyleSheet("""
            QPushButton {
                border: none;
                border-radius: 15px;
                background: transparent;
                font-size: 15px;
                color: #9aa3b2;
            }
            QPushButton:hover { background-color: #eef2f7; color: #3b82f6; }
            QPushButton:pressed { background-color: #e2e8f0; }
        """)
        self.config_btn.clicked.connect(self._show_config_dialog)
        layout.addWidget(self.config_btn)

    def _show_config_dialog(self):
        """打开单脚本配置弹窗"""
        dialog = SingleScriptConfigDialog(self.display_name, self.script_path, self)
        dialog.exec()

    def _show_dungeon_menu(self):
        """点击副本按钮，弹出级联菜单"""
        menu = QMenu(self)
        menu.setStyleSheet("""
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
            }
            QMenu::item:selected {
                background-color: #0078D4;
                color: white;
            }
            QMenu::separator {
                height: 1px;
                background: #e0e0e0;
                margin: 4px 8px;
            }
        """)

        for dungeon_name in self._dungeon_options:
            if dungeon_name == "未选择":
                action = menu.addAction(dungeon_name)
                action.triggered.connect(lambda checked, dn=dungeon_name: self._on_dungeon_selected(dn))
                menu.addSeparator()
                continue

            seq_options = self._sequence_options_map.get(dungeon_name, [])  # optional: 副本可能没有二级选项
            if seq_options:
                # 有二级选项 → 子菜单（从右侧弹出）
                submenu = menu.addMenu(dungeon_name)
                for display_name, actual_value in seq_options:
                    sub_action = submenu.addAction(display_name)
                    sub_action.triggered.connect(
                        lambda checked, dn=dungeon_name, sq=actual_value: self._on_dungeon_selected(dn, sq)
                    )
            else:
                # 无二级选项 → 直接选择
                action = menu.addAction(dungeon_name)
                action.triggered.connect(lambda checked, dn=dungeon_name: self._on_dungeon_selected(dn))

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
            state['dungeon'] = self._selected_dungeon
            if self._selected_sequence:
                state['sequence'] = self._selected_sequence
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
        if (event.pos() - self._drag_start_pos).manhattanLength() < QApplication.startDragDistance():
            return
        self._drag_start_pos = None
        self._start_drag()

    def _handle_mouse_release(self, event):
        self._drag_start_pos = None
        QLabel.mouseReleaseEvent(self.handle, event)

    def _start_drag(self):
        mime = QMimeData()
        mime.setText(self.display_name)
        mime.setData(_DRAG_MIME, self.display_name.encode('utf-8'))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(self.grab())
        drag.exec(Qt.MoveAction)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(_DRAG_MIME) and self._reorder_callback:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if not (event.mimeData().hasFormat(_DRAG_MIME) and self._reorder_callback):
            event.ignore()
            return
        src_name = bytes(event.mimeData().data(_DRAG_MIME)).decode('utf-8')
        if src_name != self.display_name:
            self._reorder_callback(src_name, self.display_name)
        event.acceptProposedAction()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("OneDragon 脚本启动器")
        self.setMinimumSize(520, 640)

        self.script_items = []
        self.all_config_data = None
        self.runner = None
        self._ui_state = _load_ui_state()

        self._init_ui()
        self._load_scripts()

    def _init_ui(self):
        central = QWidget()
        central.setStyleSheet("background-color: #eef1f6;")
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(14)

        # 脚本列表
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("""
            QScrollArea {
                background-color: transparent;
                border: none;
            }
            QScrollBar:vertical {
                width: 8px;
                background: transparent;
            }
            QScrollBar::handle:vertical {
                background: #cbd5e1;
                border-radius: 4px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover { background: #94a3b8; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)

        self.scroll_content = QWidget()
        self.scroll_content.setStyleSheet("background-color: transparent;")
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(2, 2, 2, 2)
        self.scroll_layout.setSpacing(10)
        self.scroll_layout.addStretch()
        scroll.setWidget(self.scroll_content)
        layout.addWidget(scroll, stretch=1)

        # 快捷操作按钮（全选 / 清空）
        action_layout = QHBoxLayout()
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(8)

        self.select_all_btn = QPushButton("一键全选")
        self.select_all_btn.setFixedHeight(32)
        self.select_all_btn.setMinimumWidth(72)
        self.select_all_btn.setCursor(Qt.PointingHandCursor)
        self.select_all_btn.setStyleSheet("""
            QPushButton {
                border: 1px solid #d8dee9;
                border-radius: 8px;
                background: white;
                font-size: 11px;
                color: #4b5563;
                padding: 0 16px;
            }
            QPushButton:hover { border-color: #3b82f6; color: #3b82f6; }
            QPushButton:pressed { background: #f0f4ff; }
        """)
        self.select_all_btn.clicked.connect(self._select_all)
        action_layout.addWidget(self.select_all_btn)

        self.deselect_all_btn = QPushButton("清空选择")
        self.deselect_all_btn.setFixedHeight(32)
        self.deselect_all_btn.setMinimumWidth(72)
        self.deselect_all_btn.setCursor(Qt.PointingHandCursor)
        self.deselect_all_btn.setStyleSheet("""
            QPushButton {
                border: 1px solid #d8dee9;
                border-radius: 8px;
                background: white;
                font-size: 11px;
                color: #4b5563;
                padding: 0 16px;
            }
            QPushButton:hover { border-color: #ef4444; color: #ef4444; }
            QPushButton:pressed { background: #fef2f2; }
        """)
        self.deselect_all_btn.clicked.connect(self._deselect_all)
        action_layout.addWidget(self.deselect_all_btn)

        action_layout.addStretch()
        layout.addLayout(action_layout)

        # 运行按钮
        self.run_btn = QPushButton("▶ 运行全部开启的脚本")
        self.run_btn.setFixedHeight(46)
        self.run_btn.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        self.run_btn.setCursor(Qt.PointingHandCursor)
        self.run_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                            stop:0 #4f8cff, stop:1 #3b82f6);
                color: white;
                border: none;
                border-radius: 10px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                            stop:0 #5b96ff, stop:1 #2f6fed);
            }
            QPushButton:pressed { background: #2f6fed; }
            QPushButton:disabled { background: #cbd5e1; }
        """)
        self.run_btn.clicked.connect(self._run_selected)
        layout.addWidget(self.run_btn)



    def _load_scripts(self):
        with open(get_config_yml_path_under_root(), encoding='utf-8') as f:
            self.all_config_data = yaml.safe_load(f)

        self.dungeon_map = load_dungeon_map()

        assert 'script_list' in self.all_config_data, "[gui_launcher] config.yml 缺少 script_list 字段"

        for item in self.script_items:
            item.deleteLater()
        self.script_items.clear()

        for data in self.all_config_data['script_list']:
            name = data['display_name']
            dungeon_cfg = self.dungeon_map.get(name)  # optional: 不是所有脚本都有副本配置
            options, seq_map, show_seq = parse_dungeon_config(dungeon_cfg)

            saved = self._ui_state.get(name)  # optional: 新脚本可能没有保存的状态
            if saved:
                saved = restore_sequence_type(saved, seq_map)
            item = ScriptItem(data, dungeon_options=options if options else None,
                              sequence_options_map=seq_map if show_seq else None,
                              show_sequence=show_seq, saved_state=saved,
                              reorder_callback=self._reorder_scripts)
            item.set_state_callback(self._persist_ui_state)
            self.scroll_layout.insertWidget(len(self.script_items), item)
            self.script_items.append(item)


    def _persist_ui_state(self):
        """收集所有脚本的 UI 状态并保存"""
        state = {}
        for item in self.script_items:
            state[item.display_name] = item.get_state()
        _save_ui_state(state)

    def _reorder_scripts(self, src_name, dst_name):
        """把 src_name 对应的脚本移动到 dst_name 所在位置，并同步 UI 与 config.yml"""
        script_items = self.script_items
        src_idx = next(i for i, it in enumerate(script_items) if it.display_name == src_name)
        dst_idx = next(i for i, it in enumerate(script_items) if it.display_name == dst_name)
        item = script_items.pop(src_idx)
        script_items.insert(dst_idx, item)

        # 同步 config.yml 中的顺序（以 UI 顺序为准）
        scripts = self.all_config_data['script_list']
        s_idx = next(i for i, s in enumerate(scripts) if s['display_name'] == src_name)
        script = scripts.pop(s_idx)
        scripts.insert(dst_idx, script)

        self._relayout_script_widgets()
        self._save_script_order()

    def _relayout_script_widgets(self):
        """按 self.script_items 当前顺序重排滚动区内的 widget（不销毁 widget）"""
        while self.scroll_layout.count():
            self.scroll_layout.takeAt(0)
        for item in self.script_items:
            self.scroll_layout.addWidget(item)
        self.scroll_layout.addStretch()

    def _save_script_order(self):
        """把当前脚本顺序写回 config.yml"""
        config_path = get_config_yml_path_under_root()
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(self.all_config_data, f, allow_unicode=True, sort_keys=False)

    def _generate_config(self, chain_name="88"):
        """生成 ScriptChainer 配置文件（仅含启用的脚本）"""
        # 每周超时
        weekly_timeouts = {}
        weekly_path = get_weekly_timeouts_yml_path_under_root()
        if os.path.exists(weekly_path):
            with open(weekly_path, encoding='utf-8') as f:
                weekly_timeouts = yaml.safe_load(f) or {}

        week_num = get_week_num()

        # 收集每个启用脚本的副本选择、序列选择
        enabled_dungeons = {}
        enabled_sequences = {}
        for item in self.script_items:
            if item.enabled:
                dungeon = item.get_selected_dungeon()
                if dungeon:
                    enabled_dungeons[item.display_name] = dungeon
                seq = item.get_sequence()
                if seq is not None:
                    enabled_sequences[item.display_name] = seq

        enabled_names = [i.display_name for i in self.script_items if i.enabled]

        data = copy.deepcopy(self.all_config_data)
        filtered = []
        for script in data['script_list']:
            name = script['display_name']
            if name in enabled_names:
                timeouts = weekly_timeouts.get(name)
                if timeouts and len(timeouts) == 7:
                    script['run_timeout_seconds'] = timeouts[week_num]

                # 外观模式：写入各脚本内部 config（副本、序列）
                dungeon = enabled_dungeons.get(name)
                seq = enabled_sequences.get(name)
                set_config(name, dungeon_name=dungeon, sequence=seq)

                filtered.append(script)

        data['script_list'] = filtered

        output_dir = get_path_under_onedragon("config", "script_chain")
        output_file = safe_path_join(output_dir, f"{chain_name}.yml")
        with open(output_file, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, allow_unicode=True, sort_keys=False)

        return len(filtered)

    def _run_selected(self):
        enabled_count = sum(1 for i in self.script_items if i.enabled)
        if enabled_count == 0:
            QMessageBox.warning(self, "提示", "请至少开启一个脚本")
            return

        reply = QMessageBox.question(
            self, "确认运行",
            f"即将运行 {enabled_count} 个脚本，是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self._generate_config("88")

        self.run_btn.setEnabled(False)
        self.run_btn.setText("运行中...")


        self.runner = ScriptChainRunner("88")
        self.runner.finished_signal.connect(self._on_finished)
        self.runner.start()

    def _on_finished(self, return_code):
        self.run_btn.setEnabled(True)
        self.run_btn.setText("▶ 运行全部开启的脚本")

        if return_code == 0:

            QMessageBox.information(self, "完成", "所有脚本运行完成！")
        else:
            QMessageBox.warning(self, "提示", f"脚本运行结束，退出码: {return_code}")

    def _select_all(self):
        """全选所有脚本"""
        for item in self.script_items:
            if not item.enabled:
                item.enabled = True
                item._update_switch_style()
    def _deselect_all(self):
        """清空所有选择"""
        for item in self.script_items:
            if item.enabled:
                item.enabled = False
                item._update_switch_style()


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description="OneDragon 脚本启动器")
    parser.add_argument(
        "--no-set-config",
        action="store_true",
        help="计划任务模式：跳过 GUI 与各脚本内部 config 写入，直接按 config.yml 中已启用的脚本运行",
    )
    return parser.parse_args()


def run_direct(chain_name="88") -> int:
    """无界面直接运行（计划任务模式）。

    `enabled` 为纯内存态、默认全开，故跳过 GUI 与各脚本内部 config（set_config）
    写入，直接运行全部脚本（生成 ScriptChainer 配置并运行），便于计划任务调用。
    """
    with open(get_config_yml_path_under_root(), encoding='utf-8') as f:
        data = yaml.safe_load(f)
    assert 'script_list' in data, "[gui_launcher] config.yml 缺少 script_list 字段"

    weekly_timeouts = {}
    weekly_path = get_weekly_timeouts_yml_path_under_root()
    if os.path.exists(weekly_path):
        with open(weekly_path, encoding='utf-8') as f:
            weekly_timeouts = yaml.safe_load(f) or {}

    week_num = get_week_num()

    filtered = []
    for script in data['script_list']:
        name = script['display_name']
        timeouts = weekly_timeouts.get(name)
        if timeouts and len(timeouts) == 7:
            script['run_timeout_seconds'] = timeouts[week_num]
        filtered.append(script)

    if not filtered:
        logger.warning("[gui_launcher] 没有可运行的脚本（script_list 为空），直接退出")
        return 0

    data['script_list'] = filtered
    output_dir = get_path_under_onedragon("config", "script_chain")
    output_file = safe_path_join(output_dir, f"{chain_name}.yml")
    with open(output_file, 'w', encoding='utf-8') as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False)

    command, cwd = _build_chain_command(chain_name)
    res = subprocess.run(command, cwd=cwd)
    return res.returncode


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    args = parse_args()
    if need_config_workflow():
        config_workflow()
    if args.no_set_config:
        sys.exit(run_direct("88"))
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
