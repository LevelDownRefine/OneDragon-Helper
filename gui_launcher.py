import sys
import os
import copy
import subprocess
import yaml
from datetime import datetime
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QScrollArea, QFrame, QMessageBox, QStatusBar,
    QComboBox, QSpinBox
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont

from utils import (
    get_config_yml_path_under_root,
    get_weekly_timeouts_yml_path_under_root,
    get_path_under_onedragon,
)
from dungeon_adapter import set_dungeon, set_sequence


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
    """单个脚本项"""

    def __init__(self, script_data, dungeon_options=None, show_sequence=False):
        super().__init__()
        self.display_name = script_data.get('display_name', '未命名')
        self.enabled = script_data.get('enabled', True)
        self.script_type = script_data.get('script_type', 'external')
        self.dungeon_combo = None  # 副本选择下拉框
        self.sequence_spin = None  # 刷取序列输入框

        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet("""
            QFrame {
                background-color: #f5f5f5;
                border-radius: 8px;
            }
            QFrame:hover {
                background-color: #e8e8e8;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)

        name_label = QLabel(self.display_name)
        name_label.setFont(QFont("Microsoft YaHei", 10))
        layout.addWidget(name_label, stretch=1)

        # 刷取序列（ok 系列脚本）
        if show_sequence:
            seq_label = QLabel("序列:")
            seq_label.setStyleSheet("color: #666; font-size: 9px;")
            layout.addWidget(seq_label)

            self.sequence_spin = QSpinBox()
            self.sequence_spin.setRange(1, 99)
            self.sequence_spin.setValue(1)
            self.sequence_spin.setFixedWidth(55)
            self.sequence_spin.setStyleSheet("""
                QSpinBox {
                    border: 1px solid #ccc;
                    border-radius: 4px;
                    background: white;
                    font-size: 9px;
                }
            """)
            layout.addWidget(self.sequence_spin)

        # 非 python 脚本显示副本选择
        if self.script_type != 'python' and dungeon_options:
            self.dungeon_combo = QComboBox()
            self.dungeon_combo.addItems(dungeon_options)
            self.dungeon_combo.setFixedHeight(26)
            self.dungeon_combo.setStyleSheet("""
                QComboBox {
                    border: 1px solid #ccc;
                    border-radius: 4px;
                    padding: 0 8px;
                    background: white;
                    font-size: 9px;
                    min-width: 90px;
                }
            """)
            layout.addWidget(self.dungeon_combo)

        script_type = script_data.get('script_type', '')
        type_label = QLabel(script_type)
        type_label.setStyleSheet("""
            QLabel {
                color: #888;
                font-size: 9px;
                padding: 2px 8px;
                background-color: #ddd;
                border-radius: 10px;
            }
        """)
        layout.addWidget(type_label)

        self.toggle_btn = QPushButton()
        self.toggle_btn.setFixedSize(60, 28)
        self.toggle_btn.setCursor(Qt.PointingHandCursor)
        self.toggle_btn.clicked.connect(self._toggle)
        self._update_style()
        layout.addWidget(self.toggle_btn)

    def get_selected_dungeon(self):
        """获取选择的副本名，未选择或 python 脚本返回 None"""
        if self.dungeon_combo:
            val = self.dungeon_combo.currentText()
            if val and val != "未选择":
                return val
        return None

    def get_sequence(self):
        """获取刷取序列值，未启用返回 None"""
        if self.sequence_spin:
            return self.sequence_spin.value()
        return None

    def _toggle(self):
        self.enabled = not self.enabled
        self._update_style()

    def _update_style(self):
        if self.enabled:
            self.toggle_btn.setText("开启")
            self.toggle_btn.setStyleSheet("""
                QPushButton {
                    background-color: #4CAF50;
                    color: white;
                    border: none;
                    border-radius: 14px;
                    font-weight: bold;
                }
                QPushButton:hover { background-color: #45a049; }
            """)
        else:
            self.toggle_btn.setText("关闭")
            self.toggle_btn.setStyleSheet("""
                QPushButton {
                    background-color: #9e9e9e;
                    color: white;
                    border: none;
                    border-radius: 14px;
                    font-weight: bold;
                }
                QPushButton:hover { background-color: #757575; }
            """)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("OneDragon 脚本启动器")
        self.setMinimumSize(480, 560)

        self.script_items = []
        self.all_config_data = None
        self.runner = None

        self._init_ui()
        self._load_scripts()

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 标题
        title = QLabel("自动化脚本管理")
        title.setFont(QFont("Microsoft YaHei", 16, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # 提示
        hint = QLabel("点击按钮切换开关，设置完成后运行全部开启的脚本")
        hint.setStyleSheet("color: #666; font-size: 11px;")
        hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(hint)

        # 全选/全不选
        btn_row = QHBoxLayout()
        self.select_all_btn = QPushButton("全部开启")
        self.select_all_btn.setFixedHeight(32)
        self.select_all_btn.clicked.connect(self._select_all)
        btn_row.addWidget(self.select_all_btn)

        self.deselect_all_btn = QPushButton("全部关闭")
        self.deselect_all_btn.setFixedHeight(32)
        self.deselect_all_btn.clicked.connect(self._deselect_all)
        btn_row.addWidget(self.deselect_all_btn)
        layout.addLayout(btn_row)

        # 脚本列表
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea {
                border: 1px solid #ddd;
                border-radius: 8px;
                background-color: white;
            }
        """)

        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(8, 8, 8, 8)
        self.scroll_layout.setSpacing(8)
        self.scroll_layout.addStretch()
        scroll.setWidget(self.scroll_content)
        layout.addWidget(scroll, stretch=1)

        # 运行按钮
        self.run_btn = QPushButton("▶ 运行全部开启的脚本")
        self.run_btn.setFixedHeight(48)
        self.run_btn.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        self.run_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                border-radius: 8px;
            }
            QPushButton:hover { background-color: #1976D2; }
            QPushButton:disabled { background-color: #BDBDBD; }
        """)
        self.run_btn.clicked.connect(self._run_selected)
        layout.addWidget(self.run_btn)

        # 状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self._update_status()

    def _load_scripts(self):
        try:
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
                options = self.dungeon_map.get(name)
                # ok 系列脚本显示刷取序列输入框
                show_seq = name in ("鸣潮", "终末地", "异环")
                item = ScriptItem(data, dungeon_options=options, show_sequence=show_seq)
                self.scroll_layout.insertWidget(len(self.script_items), item)
                self.script_items.append(item)

            self._update_status()
        except Exception as e:
            QMessageBox.critical(self, "加载失败", f"无法读取配置:\n{str(e)}")

    def _select_all(self):
        for item in self.script_items:
            item.enabled = True
            item._update_style()
        self._update_status()

    def _deselect_all(self):
        for item in self.script_items:
            item.enabled = False
            item._update_style()
        self._update_status()

    def _update_status(self):
        enabled = sum(1 for i in self.script_items if i.enabled)
        total = len(self.script_items)
        self.status_bar.showMessage(f"已选择 {enabled} / {total} 个脚本")

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
                if name in enabled_dungeons:
                    set_dungeon(name, enabled_dungeons[name])
                if name in enabled_sequences:
                    set_sequence(name, enabled_sequences[name])

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
