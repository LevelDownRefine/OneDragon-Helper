import sys
import os
import copy
import json
import subprocess
import yaml
import warnings
from datetime import datetime
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QScrollArea, QFrame, QMessageBox, QStatusBar,
    QComboBox, QMenu
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont

from utils import (
    get_config_yml_path_under_root,
    get_weekly_timeouts_yml_path_under_root,
    get_path_under_onedragon,
    get_root_dir,
)
from dungeon_adapter import set_config


# ---- UI 状态持久化 ----
_STATE_FILE = os.path.join(get_root_dir(), "gui_state.json")


def _load_ui_state() -> dict:
    """读取上次保存的 UI 状态"""
    if os.path.exists(_STATE_FILE):
        try:
            with open(_STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            warnings.warn(f"读取 UI 状态文件失败: {e}")
    return {}


def _save_ui_state(state: dict):
    """保存 UI 状态"""
    try:
        with open(_STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except OSError as e:
        warnings.warn(f"保存 UI 状态文件失败: {e}")


def get_week_num() -> int:
    """返回星期数字：0周一 ~ 6周日"""
    return datetime.now().weekday()


class ScriptChainRunner(QThread):
    """后台运行 ScriptChainer"""
    finished_signal = Signal(int)

    def __init__(self, chain_name="01"):
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


class ScriptItem(QFrame):
    """单个脚本项（Fluent 风格卡片）"""

    def __init__(self, script_data, dungeon_options=None, sequence_options_map=None,
                 show_sequence=False, saved_state=None):
        super().__init__()
        self.display_name = script_data.get('display_name', '未命名')
        self.script_type = script_data.get('script_type', 'external')
        self.dungeon_btn = None
        self._selected_dungeon = None   # 一级副本名（None 表示未选择）
        self._selected_sequence = None  # 二级序列名
        self.enabled = script_data.get('enabled', True)
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
        layout.setSpacing(12)

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
            self.dungeon_btn.setMinimumWidth(120)
            self.dungeon_btn.setCursor(Qt.PointingHandCursor)
            self.dungeon_btn.setStyleSheet("""
                QPushButton {
                    border: 1px solid #d0d0d0;
                    border-radius: 4px;
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
            if saved_state and saved_state.get('dungeon') and saved_state['dungeon'] in self._dungeon_options:
                self._selected_dungeon = saved_state['dungeon']
                if saved_state.get('sequence'):
                    self._selected_sequence = saved_state['sequence']
                    seq_str = str(self._selected_sequence)
                    if seq_str.isdigit():
                        self.dungeon_btn.setText(f"{self._selected_dungeon} > {seq_str}")
                    else:
                        self.dungeon_btn.setText(seq_str)
                else:
                    self.dungeon_btn.setText(self._selected_dungeon)

        # 开关按钮（Fluent Switch 风格）
        self.toggle_btn = QPushButton()
        self.toggle_btn.setFixedSize(44, 22)
        self.toggle_btn.setCursor(Qt.PointingHandCursor)
        self.toggle_btn.clicked.connect(self._toggle)
        self._update_switch_style()
        layout.addWidget(self.toggle_btn)

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

            seq_options = self._sequence_options_map.get(dungeon_name, [])
            if seq_options:
                # 有二级选项 → 子菜单（从右侧弹出）
                submenu = menu.addMenu(dungeon_name)
                for seq in seq_options:
                    sub_action = submenu.addAction(str(seq))
                    sub_action.triggered.connect(
                        lambda checked, dn=dungeon_name, sq=str(seq): self._on_dungeon_selected(dn, sq)
                    )
            else:
                # 无二级选项 → 直接选择
                action = menu.addAction(dungeon_name)
                action.triggered.connect(lambda checked, dn=dungeon_name: self._on_dungeon_selected(dn))

        # 在按钮下方弹出
        menu.exec(self.dungeon_btn.mapToGlobal(self.dungeon_btn.rect().bottomLeft()))

    def _on_dungeon_selected(self, dungeon_name, sequence=None):
        """选择副本后的回调"""
        if dungeon_name == "未选择":
            self._selected_dungeon = None
            self._selected_sequence = None
            self.dungeon_btn.setText("选择副本")
        else:
            self._selected_dungeon = dungeon_name
            self._selected_sequence = sequence
            if sequence:
                seq_str = str(sequence)
                if seq_str.isdigit():
                    self.dungeon_btn.setText(f"{dungeon_name} > {seq_str}")
                else:
                    self.dungeon_btn.setText(seq_str)
            else:
                self.dungeon_btn.setText(dungeon_name)
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

        # 状态栏
        self.status_bar = QStatusBar()
        self.status_bar.setStyleSheet("background-color: #f3f3f3; color: #606060;")
        self.setStatusBar(self.status_bar)

    def _load_scripts(self):
        with open(get_config_yml_path_under_root(), 'r', encoding='utf-8') as f:
            self.all_config_data = yaml.safe_load(f)

        # 读取副本列表配置
        self.dungeon_map = {}
        dungeon_file = os.path.join(os.path.dirname(get_config_yml_path_under_root()), "dungeon_list.yml")
        if os.path.exists(dungeon_file):
            with open(dungeon_file, 'r', encoding='utf-8') as f:
                self.dungeon_map = yaml.safe_load(f) or {}

        script_list = self.all_config_data.get('script_list', [])

        for item in self.script_items:
            item.deleteLater()
        self.script_items.clear()

        for data in script_list:
            name = data.get('display_name', '')
            dungeon_cfg = self.dungeon_map.get(name)

            # 解析副本列表：支持平铺列表 和 带二级目录的嵌套列表
            options = []
            seq_map = {}  # 副本名 → 二级选项列表
            show_seq = False
            if isinstance(dungeon_cfg, list):
                for item in dungeon_cfg:
                    if isinstance(item, dict):
                        # 字典项：key 为副本名，value 为二级选项列表
                        for dungeon_name, seq_list in item.items():
                            options.append(dungeon_name)
                            seq_map[dungeon_name] = seq_list or []
                        show_seq = True
                    else:
                        # 普通字符串项
                        options.append(str(item))

            saved = self._ui_state.get(name)
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

    def _generate_config(self, chain_name="01"):
        """生成 ScriptChainer 配置文件（仅含启用的脚本）"""
        # 每周超时
        weekly_timeouts = {}
        weekly_path = get_weekly_timeouts_yml_path_under_root()
        if os.path.exists(weekly_path):
            with open(weekly_path, 'r', encoding='utf-8') as f:
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
        for script in data.get('script_list', []):
            name = script.get('display_name', '')
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
        output_file = os.path.join(output_dir, f"{chain_name}.yml")
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

        try:
            count = self._generate_config("01")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"生成配置失败:\n{str(e)}")
            return

        self.run_btn.setEnabled(False)
        self.run_btn.setText("运行中...")
        self.status_bar.showMessage(f"正在运行 {count} 个脚本...")

        self.runner = ScriptChainRunner("01")
        self.runner.finished_signal.connect(self._on_finished)
        self.runner.start()

    def _on_finished(self, return_code):
        self.run_btn.setEnabled(True)
        self.run_btn.setText("▶ 运行全部开启的脚本")

        if return_code == 0:
            self.status_bar.showMessage("运行完成 ✓")
            QMessageBox.information(self, "完成", "所有脚本运行完成！")
        else:
            self.status_bar.showMessage(f"运行结束 (退出码: {return_code})")
            QMessageBox.warning(self, "提示", f"脚本运行结束，退出码: {return_code}")


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
