import os
import shutil
import yaml

from PySide6.QtWidgets import (
    QHBoxLayout, QFileDialog, QVBoxLayout, QDialog,
    QLabel, QLineEdit, QPushButton, QMessageBox
)
from PySide6.QtGui import QIntValidator, QFont

from src.utils import (
    get_path_under_root,
    get_path_under_onedragon,
    get_config_yml_path_under_root,
    get_weekly_timeouts_yml_path_under_root,
)
from src.config.bgi import copy_BGI_User


def copy_python_scripts():
    py_script_dir = get_path_under_root("src", "python_script")
    file_names = [f for f in os.listdir(py_script_dir) if f.endswith(".py")]
    for file_name in file_names:
        input_path = os.path.join(py_script_dir, file_name)
        output_path = get_path_under_onedragon("config", "script_chain", "scripts")
        if not os.path.exists(os.path.join(output_path, file_name)):
            shutil.copy(input_path, output_path)
            print(f"已复制Python脚本{file_name}到: {output_path}")
        else:
            print(f"[OneDragonHelper] Python脚本{file_name}已存在，跳过复制")


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
            with open(weekly_timeouts_path, 'r', encoding='utf-8') as f:
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
        with open(config_path, 'r', encoding='utf-8') as f:
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
            with open(weekly_timeouts_path, 'r', encoding='utf-8') as f:
                weekly_timeouts_map = yaml.safe_load(f) or {}
        weekly_timeouts_map[self.script_name] = timeouts

        with open(weekly_timeouts_path, 'w', encoding='utf-8') as f:
            yaml.dump(weekly_timeouts_map, f, allow_unicode=True, sort_keys=False)

        QMessageBox.information(self, "成功", "配置已保存！")
        self.accept()


def need_config_workflow() -> bool:
    """判断是否需要先执行 config_workflow（首次运行时 config.yml 不存在）"""
    return not os.path.exists(get_config_yml_path_under_root())


def config_workflow():
    # 复制 BetterGI 用户配置
    copy_BGI_User()
    # 复制 src/python_scripts 到 OneDragon-ScriptChainer/config/script_chain/scripts
    copy_python_scripts()
    # 从模板生成 config.yml（如果不存在）
    config_path = get_config_yml_path_under_root()
    if not os.path.exists(config_path):
        example_path = os.path.join(os.path.dirname(config_path), "config.example.yml")
        shutil.copy(example_path, config_path)


if __name__ == "__main__":
    config_workflow()
