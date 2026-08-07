"""弹窗：单脚本配置（路径 + 每周超时）与添加脚本。"""

import os

import yaml
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIntValidator
from PySide6.QtWidgets import (
    QCheckBox,
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

from src.config.set_config import ScriptConfig
from src.gui.controls import make_secondary_button
from src.gui.utils import DEFAULT_RUN_TIMEOUT
from src.utils import (
    get_weekly_timeouts_yml_path_under_root,
    require_config_yml_path,
)

# 脚本文件选择过滤器（两个弹窗共用）
SCRIPT_FILE_FILTER = (
    "可执行文件 Executable files (*.exe *.bat *.py);;所有文件 All files (*.*)"
)


def confirm_config_update(display_name: str) -> bool:
    """GUI 确认回调：config 与模板不一致时，询问用户是否更新并保存。"""
    box = QMessageBox()
    box.setIcon(QMessageBox.Question)
    box.setWindowTitle("更新配置")
    box.setText(f"「{display_name}」的配置文件与模板不一致，是否更新并保存？")
    box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    box.setDefaultButton(QMessageBox.No)
    box.exec()
    return box.result() == QMessageBox.Yes


def inject_config_confirm() -> None:
    """把 GUI 确认弹窗注入 config 层的保存前回调（无头 CLI 不注入）。"""
    ScriptConfig.confirm_before_save = confirm_config_update


def _browse_script_file(parent, line_edit):
    """弹出文件选择对话框，选中后规范化为系统路径写入 line_edit"""
    file_path, _ = QFileDialog.getOpenFileName(
        parent, "选择脚本文件", "", SCRIPT_FILE_FILTER
    )
    if file_path:
        line_edit.setText(os.path.normpath(file_path))


def default_script_entry(display_name, script_type, script_path, script_arguments=""):
    """构造一个 config.yml script_list 条目：核心字段由参数指定，其余用默认值补全。"""
    return {
        "display_name": display_name,
        "game_label": "",
        "script_type": script_type,
        "script_path": script_path,
        "script_process_name": [],
        "game_process_name": "",
        "launcher_mode": False,
        "check_done": "script_closed",
        "kill_script_after_done": True,
        "kill_game_after_done": False,
        "script_arguments": script_arguments,
        "notify_start": False,
        "notify_done": False,
        "notify_log_interval": 0,
        "attach_direction": "",
        "no_log_timeout_seconds": 0,
        "no_log_max_retries": 3,
        "block": True,
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
        self.resize(720, 420)
        self.setStyleSheet("background-color: #f7f8fa;")

        self.script_name = script_name
        self.script_path = script_path
        self.saved_display_name = script_name  # 保存后最终生效的名称（可能被改名）
        self._script_data = {}  # 从 config.yml 读到的本脚本完整数据

        self.init_ui()
        self.load_data()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # ---- 脚本名称 ----
        row_name = QHBoxLayout()
        row_name.setSpacing(8)
        name_label = QLabel("脚本名称:")
        name_label.setFont(QFont("Microsoft YaHei", 10))
        name_label.setFixedWidth(self.LABEL_WIDTH)
        name_label.setStyleSheet("color: #303030;")
        self.name_input = QLineEdit(self)
        self.name_input.setFont(QFont("Microsoft YaHei", 10))
        self.name_input.setPlaceholderText("脚本显示名称，例如：1999")
        self.name_input.setStyleSheet(self._LINEEDIT_STYLE)
        row_name.addWidget(name_label)
        row_name.addWidget(self.name_input, 1)
        layout.addLayout(row_name)

        # ---- 脚本路径 ----
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        label = QLabel("脚本路径:")
        label.setFont(QFont("Microsoft YaHei", 10))
        label.setFixedWidth(self.LABEL_WIDTH)
        label.setStyleSheet("color: #303030;")
        self.path_input = QLineEdit(self)
        self.path_input.setFont(QFont("Microsoft YaHei", 10))
        self.path_input.setText(self.script_path)
        self.path_input.setStyleSheet(self._LINEEDIT_STYLE)
        self.browse_btn = make_secondary_button("选择")
        self.browse_btn.clicked.connect(self.browse_file)
        row1.addWidget(label)
        row1.addWidget(self.path_input)
        row1.addWidget(self.browse_btn)
        layout.addLayout(row1)

        # ---- 脚本类型 + 启动参数 ----
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        type_label = QLabel("脚本类型:")
        type_label.setFont(QFont("Microsoft YaHei", 10))
        type_label.setFixedWidth(self.LABEL_WIDTH)
        type_label.setStyleSheet("color: #303030;")
        self.type_combo = QComboBox(self)
        self.type_combo.addItems(["external", "python"])
        self.type_combo.setFont(QFont("Microsoft YaHei", 10))
        self.type_combo.setFixedWidth(120)
        self.type_combo.setStyleSheet(self._COMBO_STYLE)
        row2.addWidget(type_label)
        row2.addWidget(self.type_combo)

        args_label = QLabel("启动参数:")
        args_label.setFont(QFont("Microsoft YaHei", 10))
        args_label.setStyleSheet("color: #303030;")
        self.args_input = QLineEdit(self)
        self.args_input.setFont(QFont("Microsoft YaHei", 10))
        self.args_input.setPlaceholderText("可选，传给脚本的命令行参数")
        self.args_input.setStyleSheet(self._LINEEDIT_STYLE)
        row2.addWidget(args_label)
        row2.addWidget(self.args_input, 1)
        layout.addLayout(row2)

        # ---- 完成检测方式 ----
        row3 = QHBoxLayout()
        row3.setSpacing(8)
        check_label = QLabel("完成检测:")
        check_label.setFont(QFont("Microsoft YaHei", 10))
        check_label.setFixedWidth(self.LABEL_WIDTH)
        check_label.setStyleSheet("color: #303030;")
        self.check_done_combo = QComboBox(self)
        self.check_done_combo.addItems(
            [
                "game_or_script_closed",
                "script_closed",
                "game_closed",
            ]
        )
        self.check_done_combo.setFont(QFont("Microsoft YaHei", 10))
        self.check_done_combo.setFixedWidth(220)
        self.check_done_combo.setStyleSheet(self._COMBO_STYLE)
        row3.addWidget(check_label)
        row3.addWidget(self.check_done_combo)
        row3.addStretch()
        layout.addLayout(row3)

        # ---- 复选框行 ----
        row4 = QHBoxLayout()
        row4.setSpacing(24)
        self.kill_script_cb = QCheckBox("运行结束后关闭脚本", self)
        self.kill_script_cb.setFont(QFont("Microsoft YaHei", 10))
        self.kill_script_cb.setStyleSheet("color: #303030;")
        self.kill_game_cb = QCheckBox("运行结束后关闭游戏", self)
        self.kill_game_cb.setFont(QFont("Microsoft YaHei", 10))
        self.kill_game_cb.setStyleSheet("color: #303030;")
        self.kill_game_cb.stateChanged.connect(self._on_kill_game_changed)
        row4.addWidget(self.kill_script_cb)
        row4.addWidget(self.kill_game_cb)
        self.block_cb = QCheckBox("阻塞运行", self)
        self.block_cb.setFont(QFont("Microsoft YaHei", 10))
        self.block_cb.setStyleSheet("color: #303030;")
        self.block_cb.setToolTip(
            "勾选后该脚本以阻塞方式启动，运行按钮会等待其结束；不勾选则后台非阻塞运行"
        )
        row4.addWidget(self.block_cb)
        row4.addStretch()
        layout.addLayout(row4)

        # ---- 游戏进程名称 ----
        row5 = QHBoxLayout()
        row5.setSpacing(8)
        game_label = QLabel("游戏进程:")
        game_label.setFont(QFont("Microsoft YaHei", 10))
        game_label.setFixedWidth(self.LABEL_WIDTH)
        game_label.setStyleSheet("color: #303030;")
        self.game_process_input = QLineEdit(self)
        self.game_process_input.setFont(QFont("Microsoft YaHei", 10))
        self.game_process_input.setPlaceholderText("关闭游戏时必填，例如 YuanShen.exe")
        self.game_process_input.setStyleSheet(self._LINEEDIT_STYLE)
        self.game_process_input.setEnabled(False)
        row5.addWidget(game_label)
        row5.addWidget(self.game_process_input)
        layout.addLayout(row5)

        # ---- 每周超时 ----
        row6 = QHBoxLayout()
        row6.setSpacing(8)
        timeout_label = QLabel("每周超时:")
        timeout_label.setFont(QFont("Microsoft YaHei", 10))
        timeout_label.setFixedWidth(self.LABEL_WIDTH)
        timeout_label.setStyleSheet("color: #303030;")
        row6.addWidget(timeout_label)
        day_names = ["一", "二", "三", "四", "五", "六", "日"]
        self.timeout_inputs = []
        for day_idx in range(7):
            day_label = QLabel(f"周{day_names[day_idx]}")
            day_label.setFont(QFont("Microsoft YaHei", 9))
            day_label.setStyleSheet("color: #606060;")
            day_label.setFixedWidth(30)
            lineedit = QLineEdit(self)
            lineedit.setFont(QFont("Microsoft YaHei", 10))
            lineedit.setValidator(QIntValidator(10, 86400, self))
            lineedit.setFixedWidth(60)
            lineedit.setStyleSheet(self._TIMEOUT_INPUT_STYLE)
            row6.addWidget(day_label)
            row6.addWidget(lineedit)
            self.timeout_inputs.append(lineedit)
        row6.addStretch()
        layout.addLayout(row6)

        # ---- 按钮 ----
        btn_layout = QHBoxLayout()
        self.save_btn = QPushButton("保存")
        self.save_btn.setFixedHeight(32)
        self.save_btn.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        self.save_btn.setStyleSheet(self._SAVE_BTN_STYLE)
        self.save_btn.clicked.connect(self.save_data)
        cancel_btn = QPushButton("取消")
        cancel_btn.setFixedHeight(32)
        cancel_btn.setFont(QFont("Microsoft YaHei", 10))
        cancel_btn.setStyleSheet(self._CANCEL_BTN_STYLE)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(self.save_btn)
        layout.addLayout(btn_layout)

    _LINEEDIT_STYLE = """
        QLineEdit {
            border: 1px solid #d0d0d0;
            border-radius: 6px;
            padding: 4px 8px;
            background: white;
            font-size: 10px;
        }
        QLineEdit:focus { border-color: #0078D4; outline: none; }
    """
    _COMBO_STYLE = """
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
    """
    _TIMEOUT_INPUT_STYLE = """
        QLineEdit {
            border: 1px solid #d0d0d0;
            border-radius: 4px;
            padding: 3px 6px;
            background: white;
            font-size: 9px;
            text-align: center;
        }
        QLineEdit:focus { border-color: #0078D4; outline: none; }
    """
    _SAVE_BTN_STYLE = """
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
    """
    _CANCEL_BTN_STYLE = """
        QPushButton {
            border: 1px solid #d0d0d0;
            border-radius: 6px;
            background: white;
            font-size: 10px;
            color: #303030;
            padding: 0 24px;
        }
        QPushButton:hover { border-color: #3b82f6; color: #3b82f6; }
    """

    def _on_kill_game_changed(self, state):
        self.game_process_input.setEnabled(state == Qt.Checked)

    def _find_script_data(self) -> dict:
        """从 config.yml 读取本脚本的完整数据字典。

        config.yml 缺失属内部错误（对话框只在 config.yml 已加载的前提下打开），
        必须存在，故用 assert 表达不该发生；脚本不在表中才返回空 dict。
        """
        config_path = require_config_yml_path()
        with open(config_path, encoding="utf-8") as f:
            config_data = yaml.safe_load(f) or {}
        for script in config_data.get("script_list", []):
            if script.get("display_name") == self.script_name:
                return script
        return {}

    def load_data(self):
        self._script_data = self._find_script_data()

        # 脚本名称
        self.name_input.setText(self.script_name)
        # 脚本类型
        self.type_combo.setCurrentText(self._script_data.get("script_type", "external"))
        # 启动参数
        self.args_input.setText(self._script_data.get("script_arguments", ""))
        # 完成检测
        self.check_done_combo.setCurrentText(
            self._script_data.get("check_done", "script_closed")
        )
        # 关闭脚本 / 关闭游戏
        self.kill_script_cb.setChecked(
            self._script_data.get("kill_script_after_done", True)
        )
        self.kill_game_cb.setChecked(
            self._script_data.get("kill_game_after_done", False)
        )
        self.game_process_input.setText(self._script_data.get("game_process_name", ""))
        self.game_process_input.setEnabled(self.kill_game_cb.isChecked())
        # 阻塞运行：缺字段视为 True（默认阻塞）
        self.block_cb.setChecked(self._script_data.get("block", True))

        # 每周超时
        weekly_timeouts_path = get_weekly_timeouts_yml_path_under_root()
        weekly_timeouts_map = {}
        if os.path.exists(weekly_timeouts_path):
            with open(weekly_timeouts_path, encoding="utf-8") as f:
                weekly_timeouts_map = yaml.safe_load(f) or {}
        timeouts = compute_weekly_timeout_inputs(
            self.script_name, weekly_timeouts_map, DEFAULT_RUN_TIMEOUT
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

        config_path = require_config_yml_path()
        with open(config_path, encoding="utf-8") as f:
            config_data = yaml.safe_load(f) or {}

        # 脚本名称：非空 + 不与其它脚本重名（允许与自身相同，即不改名）
        new_name = self.name_input.text().strip()
        if not new_name:
            QMessageBox.warning(self, "警告", "脚本名称不能为空！")
            return
        for s in config_data.get("script_list", []):
            if s.get("display_name") == new_name and new_name != self.script_name:
                QMessageBox.warning(
                    self, "警告", f"已存在同名脚本「{new_name}」，请换一个名称。"
                )
                return

        # 若勾选了关闭游戏但未填写进程名，给出提示但不阻断（与 ScriptChainer 行为一致）
        if self.kill_game_cb.isChecked() and not self.game_process_input.text().strip():
            QMessageBox.warning(
                self,
                "警告",
                "勾选了「运行结束后关闭游戏」但未填写游戏进程名，\nScriptChainer 运行时会报「游戏进程名称为空」而跳过该脚本。",
            )

        timeouts = []
        for le in self.timeout_inputs:
            text = le.text().strip()
            val = int(text) if text else DEFAULT_RUN_TIMEOUT
            timeouts.append(max(val, 10))

        renamed = new_name != self.script_name
        for script in config_data.get("script_list", []):
            if script.get("display_name") == self.script_name:
                script["script_path"] = path_val
                script["script_type"] = self.type_combo.currentText()
                script["script_arguments"] = self.args_input.text().strip()
                script["check_done"] = self.check_done_combo.currentText()
                script["kill_script_after_done"] = self.kill_script_cb.isChecked()
                script["kill_game_after_done"] = self.kill_game_cb.isChecked()
                script["game_process_name"] = self.game_process_input.text().strip()
                script["block"] = self.block_cb.isChecked()
                if renamed:
                    script["display_name"] = new_name
                break

        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f, allow_unicode=True, sort_keys=False)

        weekly_timeouts_path = get_weekly_timeouts_yml_path_under_root()
        weekly_timeouts_map = {}
        if os.path.exists(weekly_timeouts_path):
            with open(weekly_timeouts_path, encoding="utf-8") as f:
                weekly_timeouts_map = yaml.safe_load(f) or {}
        # 改名时把每周超时配置从旧名 key 迁移到新名，避免旧 key 残留、新名找不到
        if renamed:
            old_val = weekly_timeouts_map.pop(self.script_name, None)
            if old_val is not None:
                weekly_timeouts_map[new_name] = old_val
        weekly_timeouts_map[new_name] = timeouts

        with open(weekly_timeouts_path, "w", encoding="utf-8") as f:
            yaml.dump(weekly_timeouts_map, f, allow_unicode=True, sort_keys=False)

        self.saved_display_name = new_name
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
            QMessageBox.warning(
                self, "警告", f"已存在同名脚本「{name}」，请换一个名称。"
            )
            return
        path_val = self.path_input.text().strip()
        if not path_val:
            QMessageBox.warning(self, "警告", "脚本路径不能为空！")
            return

        self.result_data = default_script_entry(
            display_name=name,
            script_type=self.type_combo.currentText(),
            script_path=path_val,
            script_arguments=self.args_input.text().strip(),
        )
        self.accept()
