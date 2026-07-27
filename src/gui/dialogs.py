"""弹窗：单脚本配置（路径 + 每周超时）与添加脚本。"""
import os

import yaml
from PySide6.QtGui import QFont, QIntValidator
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from src.gui.controls import make_secondary_button
from src.utils import (
    get_config_yml_path_under_root,
    get_weekly_timeouts_yml_path_under_root,
)

# 脚本文件选择过滤器（两个弹窗共用）
SCRIPT_FILE_FILTER = "可执行文件 Executable files (*.exe *.bat *.py);;所有文件 All files (*.*)"


def _browse_script_file(parent, line_edit):
    """弹出文件选择对话框，选中后规范化为系统路径写入 line_edit"""
    file_path, _ = QFileDialog.getOpenFileName(parent, "选择脚本文件", "", SCRIPT_FILE_FILTER)
    if file_path:
        line_edit.setText(os.path.normpath(file_path))


def default_script_entry(display_name, script_type, script_path, run_timeout_seconds,
                         script_arguments=""):
    """构造一个 config.yml script_list 条目：核心字段由参数指定，其余用默认值补全。"""
    return {
        "display_name": display_name,
        "game_label": "",
        "script_type": script_type,
        "script_path": script_path,
        "script_process_name": [],
        "game_process_name": "",
        "launcher_mode": False,
        "run_timeout_seconds": run_timeout_seconds,
        "check_done": "",
        "kill_script_after_done": True,
        "kill_game_after_done": True,
        "script_arguments": script_arguments,
        "notify_start": False,
        "notify_done": False,
        "notify_log_interval": 0,
        "attach_direction": "",
        "no_log_timeout_seconds": 0,
        "no_log_max_retries": 3,
    }


def compute_weekly_timeout_inputs(
    script_name: str, weekly_timeouts_map: dict, default_timeout: int
) -> list[int]:
    """计算周超时弹窗 7 个输入框的初始值（纯函数，便于测试）。

    - weekly_timeouts.yml 中已有该脚本条目：用其 7 个值（不足 7 格用 default_timeout 补齐）。
    - 无条目：用 default_timeout 填满 7 格。default_timeout 一般取 config.yml 中该脚本的
      run_timeout_seconds，避免首次打开弹窗时 7 格全 0、保存后把 weekly_timeouts 污染成全 0
      （该问题曾多次出现）。
    """
    entry = weekly_timeouts_map.get(script_name)
    timeouts = list(entry) if entry else [default_timeout] * 7
    if len(timeouts) < 7:
        timeouts.extend([default_timeout] * (7 - len(timeouts)))
    return timeouts[:7]


class SingleScriptConfigDialog(QDialog):
    """单个脚本的配置弹窗（路径选择 + 每周超时时间）"""
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

        self.browse_btn = make_secondary_button("选择")
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

    def _default_timeout(self) -> int:
        """从 config.yml 读取本脚本的 run_timeout_seconds，作为周超时未配置时的默认填充值。"""
        config_path = get_config_yml_path_under_root()
        if not os.path.exists(config_path):
            return 0
        with open(config_path, encoding='utf-8') as f:
            config_data = yaml.safe_load(f) or {}
        for script in config_data.get('script_list', []):
            if script.get('display_name') == self.script_name:
                return int(script.get('run_timeout_seconds', 0))
        return 0

    def load_data(self):
        weekly_timeouts_path = get_weekly_timeouts_yml_path_under_root()
        weekly_timeouts_map = {}
        if os.path.exists(weekly_timeouts_path):
            with open(weekly_timeouts_path, encoding='utf-8') as f:
                weekly_timeouts_map = yaml.safe_load(f) or {}

        timeouts = compute_weekly_timeout_inputs(
            self.script_name, weekly_timeouts_map, self._default_timeout()
        )

        for idx, le in enumerate(self.timeout_inputs):
            le.setText(str(timeouts[idx]))

    def browse_file(self):
        _browse_script_file(self, self.path_input)

    def save_data(self):
        path_val = self.path_input.text().strip()
        if not path_val:
            QMessageBox.warning(self, "警告", "脚本路径为空，可能会导致运行问题！")
            return

        timeouts = []
        for le in self.timeout_inputs:
            text = le.text().strip()
            timeouts.append(int(text) if text else 0)

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


class AddScriptDialog(QDialog):
    """新增脚本弹窗：收集核心字段（名称、类型、路径、超时），其余字段用默认值补全。"""
    LABEL_WIDTH = 80
    _INPUT_STYLE = """
        QLineEdit {
            border: 1px solid #d0d0d0;
            border-radius: 6px;
            padding: 4px 8px;
            background: white;
            font-size: 10px;
        }
        QLineEdit:focus { border-color: #0078D4; outline: none; }
    """

    def __init__(self, existing_names=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加脚本")
        self.resize(560, 250)
        self.setStyleSheet("background-color: #f7f8fa;")
        self._existing_names = set(existing_names or [])
        self.result_data = None
        self.init_ui()

    def _make_label(self, text):
        label = QLabel(text)
        label.setFont(QFont("Microsoft YaHei", 10))
        label.setFixedWidth(self.LABEL_WIDTH)
        label.setStyleSheet("color: #303030;")
        return label

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # 名称
        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        self.name_input = QLineEdit(self)
        self.name_input.setFont(QFont("Microsoft YaHei", 10))
        self.name_input.setPlaceholderText("脚本显示名称，例如：1999")
        self.name_input.setStyleSheet(self._INPUT_STYLE)
        name_row.addWidget(self._make_label("脚本名称:"))
        name_row.addWidget(self.name_input)
        layout.addLayout(name_row)

        # 类型
        type_row = QHBoxLayout()
        type_row.setSpacing(8)
        self.type_combo = QComboBox(self)
        self.type_combo.addItems(["external", "python"])
        self.type_combo.setFont(QFont("Microsoft YaHei", 10))
        self.type_combo.setFixedHeight(30)
        self.type_combo.setStyleSheet("""
            QComboBox {
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 2px 8px;
                background: white;
                font-size: 10px;
                color: #303030;
            }
            QComboBox:hover { border-color: #a0a0a0; }
            QComboBox::drop-down { border: none; width: 20px; }
        """)
        type_row.addWidget(self._make_label("脚本类型:"))
        type_row.addWidget(self.type_combo)
        type_row.addStretch()
        layout.addLayout(type_row)

        # 路径 + 浏览
        path_row = QHBoxLayout()
        path_row.setSpacing(8)
        self.path_input = QLineEdit(self)
        self.path_input.setFont(QFont("Microsoft YaHei", 10))
        self.path_input.setPlaceholderText("脚本/程序的完整路径")
        self.path_input.setStyleSheet(self._INPUT_STYLE)
        browse_btn = make_secondary_button("选择")
        browse_btn.clicked.connect(self.browse_file)
        path_row.addWidget(self._make_label("脚本路径:"))
        path_row.addWidget(self.path_input)
        path_row.addWidget(browse_btn)
        layout.addLayout(path_row)

        # 超时
        timeout_row = QHBoxLayout()
        timeout_row.setSpacing(8)
        self.timeout_input = QLineEdit(self)
        self.timeout_input.setFont(QFont("Microsoft YaHei", 10))
        self.timeout_input.setValidator(QIntValidator(0, 86400, self))
        self.timeout_input.setText("1800")
        self.timeout_input.setFixedWidth(120)
        self.timeout_input.setStyleSheet(self._INPUT_STYLE)
        timeout_row.addWidget(self._make_label("超时(秒):"))
        timeout_row.addWidget(self.timeout_input)
        timeout_row.addStretch()
        layout.addLayout(timeout_row)

        # 启动参数（可选）
        args_row = QHBoxLayout()
        args_row.setSpacing(8)
        self.args_input = QLineEdit(self)
        self.args_input.setFont(QFont("Microsoft YaHei", 10))
        self.args_input.setPlaceholderText("可选，传给脚本的命令行参数")
        self.args_input.setStyleSheet(self._INPUT_STYLE)
        args_row.addWidget(self._make_label("启动参数:"))
        args_row.addWidget(self.args_input)
        layout.addLayout(args_row)

        # 按钮
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("添加")
        save_btn.setFixedHeight(32)
        save_btn.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        save_btn.setStyleSheet("""
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
        save_btn.clicked.connect(self.save_data)
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
        btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)

    def browse_file(self):
        _browse_script_file(self, self.path_input)

    def save_data(self):
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "警告", "脚本名称不能为空！")
            return
        if name in self._existing_names:
            QMessageBox.warning(self, "警告", f"已存在同名脚本「{name}」，请换一个名称。")
            return
        path_val = self.path_input.text().strip()
        if not path_val:
            QMessageBox.warning(self, "警告", "脚本路径不能为空！")
            return

        timeout_text = self.timeout_input.text().strip()
        timeout = int(timeout_text) if timeout_text else 0

        self.result_data = default_script_entry(
            display_name=name,
            script_type=self.type_combo.currentText(),
            script_path=path_val,
            run_timeout_seconds=timeout,
            script_arguments=self.args_input.text().strip(),
        )
        self.accept()
