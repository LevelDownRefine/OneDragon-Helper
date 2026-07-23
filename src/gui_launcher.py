import copy
import json
import os
import subprocess
import sys
from datetime import datetime

import yaml
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont, QIntValidator
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
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


class ScriptChainRunner(QThread):
    """后台运行 ScriptChainer"""
    finished_signal = Signal(int)

    def __init__(self, chain_name="88"):
        super().__init__()
        self.chain_name = chain_name

    def run(self):
        launcher_work_dir = get_path_under_onedragon("src")
        command = [
            sys.executable,
            "-m",
            "script_chainer.win_exe.launcher",
            "--onedragon",
            "--chain",
            self.chain_name,
        ]
        res = subprocess.run(command, cwd=launcher_work_dir)
        self.finished_signal.emit(res.returncode)


class SingleScriptConfigDialog(QDialog):
    """单个脚本的配置弹窗（路径选择 + 每周超时时间）"""
    FILE_FILTER = "可执行文件 Executable files (*.exe *.bat *.py);;所有文件 All files (*.*)"
    LABEL_WIDTH = 80

    def __init__(self, script_name, script_path="", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"配置 {script_name}")
        self.resize(680, 280)
        self.setStyleSheet("background-color: #f3f3f3;")

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
                background-color: #0078D4;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 0 24px;
                font-size: 10px;
            }
            QPushButton:hover { background-color: #106EBE; }
            QPushButton:pressed { background-color: #005A9E; }
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
            QPushButton:hover { border-color: #a0a0a0; }
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


class ScriptItem(QFrame):
    """单个脚本项（Fluent 风格卡片）"""

    def __init__(self, script_data, dungeon_options=None, sequence_options_map=None,
                 show_sequence=False, saved_state=None):
        super().__init__()
        assert 'display_name' in script_data, "[gui_launcher] 脚本配置缺少 display_name 字段"
        assert 'script_type' in script_data, "[gui_launcher] 脚本配置缺少 script_type 字段"
        self.display_name = script_data['display_name']
        self.script_type = script_data['script_type']
        self.script_path = script_data.get('script_path', '')
        self.dungeon_btn = None
        self._selected_dungeon = None   # 一级副本名（None 表示未选择）
        self._selected_sequence = None  # 二级序列名
        self.enabled = script_data.get('enabled', True)  # 外部配置，可能缺失
        self._state_callback = None  # 状态变化回调，由 MainWindow 注入
        self._sequence_options_map = sequence_options_map or {}  # 副本名 → 二级选项列表
        self._dungeon_options = dungeon_options or []  # 一级副本列表

        self.setFrameShape(QFrame.NoFrame)
        self.setObjectName("ScriptItem")
        self.setStyleSheet("""
            QFrame#ScriptItem {
                background-color: transparent;
                border: none;
                border-bottom: 1px solid #d0d0d0;
                border-radius: 0px;
            }
            QFrame#ScriptItem:hover {
                background-color: #f0f0f0;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        # 脚本名称
        title_label = QLabel(self.display_name)
        title_label.setFont(QFont("Microsoft YaHei", 10))
        title_label.setStyleSheet("color: #202020;")
        layout.addWidget(title_label, stretch=1)

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

        # 开关按钮（Fluent Switch 风格）
        self.toggle_btn = QPushButton()
        self.toggle_btn.setFixedSize(44, 22)
        self.toggle_btn.setCursor(Qt.PointingHandCursor)
        self.toggle_btn.clicked.connect(self._toggle)
        self._update_switch_style()
        layout.addWidget(self.toggle_btn)

        # 配置按钮（最右边）
        self.config_btn = QPushButton("⚙")
        self.config_btn.setFixedSize(28, 28)
        self.config_btn.setCursor(Qt.PointingHandCursor)
        self.config_btn.setStyleSheet("""
            QPushButton {
                border: none;
                border-radius: 4px;
                background: #f5f5f5;
                font-size: 14px;
                color: #606060;
            }
            QPushButton:hover { background-color: #e0e0e0; }
            QPushButton:pressed { background-color: #d0d0d0; }
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

    def _update_switch_style(self):
        if self.enabled:
            self.toggle_btn.setText("●")
            self.toggle_btn.setStyleSheet("""
                QPushButton {
                    background-color: #0078D4;
                    color: white;
                    border: none;
                    border-radius: 11px;
                    font-size: 10px;
                    text-align: right;
                    padding-right: 5px;
                    padding-bottom: 2px;
                }
            """)
        else:
            self.toggle_btn.setText("●")
            self.toggle_btn.setStyleSheet("""
                QPushButton {
                    background-color: #c0c0c0;
                    color: white;
                    border: none;
                    border-radius: 11px;
                    font-size: 10px;
                    text-align: left;
                    padding-left: 5px;
                    padding-bottom: 2px;
                }
                QPushButton:hover { background-color: #a8a8a8; }
            """)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("OneDragon 脚本启动器")
        self.setMinimumSize(480, 560)

        self.script_items = []
        self.all_config_data = None
        self.runner = None
        self._ui_state = _load_ui_state()

        self._init_ui()
        self._load_scripts()

    def _init_ui(self):
        central = QWidget()
        central.setStyleSheet("background-color: #f3f3f3;")
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        # 脚本列表
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("""
            QScrollArea {
                background-color: #f3f3f3;
                border: none;
            }
            QScrollBar:vertical {
                width: 8px;
                background: transparent;
            }
            QScrollBar::handle:vertical {
                background: #c0c0c0;
                border-radius: 4px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover { background: #a0a0a0; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)

        self.scroll_content = QWidget()
        self.scroll_content.setStyleSheet("background-color: #f3f3f3;")
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.setSpacing(2)
        self.scroll_layout.addStretch()
        scroll.setWidget(self.scroll_content)
        layout.addWidget(scroll, stretch=1)

        # 快捷操作按钮（全选 / 清空）
        action_layout = QHBoxLayout()
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(8)

        self.select_all_btn = QPushButton("一键全选")
        self.select_all_btn.setFixedHeight(28)
        self.select_all_btn.setMinimumWidth(64)
        self.select_all_btn.setStyleSheet("""
            QPushButton {
                border: 1px solid #d0d0d0;
                border-radius: 8px;
                background: white;
                font-size: 11px;
                color: #303030;
            }
            QPushButton:hover { border-color: #a0a0a0; }
        """)
        self.select_all_btn.clicked.connect(self._select_all)
        action_layout.addWidget(self.select_all_btn)

        self.deselect_all_btn = QPushButton("清空选择")
        self.deselect_all_btn.setFixedHeight(28)
        self.deselect_all_btn.setMinimumWidth(64)
        self.deselect_all_btn.setStyleSheet("""
            QPushButton {
                border: 1px solid #d0d0d0;
                border-radius: 8px;
                background: white;
                font-size: 11px;
                color: #303030;
            }
            QPushButton:hover { border-color: #a0a0a0; }
        """)
        self.deselect_all_btn.clicked.connect(self._deselect_all)
        action_layout.addWidget(self.deselect_all_btn)

        action_layout.addStretch()
        layout.addLayout(action_layout)

        # 运行按钮
        self.run_btn = QPushButton("▶ 运行全部开启的脚本")
        self.run_btn.setFixedHeight(40)
        self.run_btn.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))
        self.run_btn.setStyleSheet("""
            QPushButton {
                background-color: #0078D4;
                color: white;
                border: none;
                border-radius: 6px;
            }
            QPushButton:hover { background-color: #106EBE; }
            QPushButton:pressed { background-color: #005A9E; }
            QPushButton:disabled { background-color: #B0B0B0; }
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
                              show_sequence=show_seq, saved_state=saved)
            item.set_state_callback(self._persist_ui_state)
            self.scroll_layout.insertWidget(len(self.script_items), item)
            self.script_items.append(item)


    def _persist_ui_state(self):
        """收集所有脚本的 UI 状态并保存"""
        state = {}
        for item in self.script_items:
            state[item.display_name] = item.get_state()
        _save_ui_state(state)

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


def main():
    if need_config_workflow():
        config_workflow()
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
