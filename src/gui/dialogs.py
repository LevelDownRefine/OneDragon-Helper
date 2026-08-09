"""弹窗：单脚本配置（路径 + 每周超时）与添加脚本。"""

import os

from PySide6.QtCore import Qt, Signal
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
from src.config.subscript import default_script_entry
from src.gui.utils import _styled_msg_box, make_secondary_button, safe_startfile
from src.service.script_service import ScriptService

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


class _FormDialogBase(QDialog):
    """表单弹窗基类：共享 QSS 样式常量与 label/按钮行构造。"""

    LABEL_WIDTH = 80
    _LINE_EDIT_STYLE = """
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
    _PRIMARY_BTN_STYLE = """
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
    _SECONDARY_BTN_STYLE = """
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
    _DANGER_BTN_STYLE = """
        QPushButton {
            border: 1px solid #f0b4b4;
            border-radius: 6px;
            background: white;
            font-size: 10px;
            color: #d14343;
            padding: 0 24px;
        }
        QPushButton:hover { border-color: #d14343; color: #d14343; }
        QPushButton:disabled { color: #c0c4cc; border-color: #e6e6e6; }
    """

    def _make_label(self, text) -> QLabel:
        """构造固定宽度的表单字段标签。"""
        label = QLabel(text)
        label.setFont(QFont("Microsoft YaHei", 10))
        label.setFixedWidth(self.LABEL_WIDTH)
        label.setStyleSheet("color: #303030;")
        return label

    def _make_buttons(self, primary_text, primary_slot) -> QHBoxLayout:
        """构造表单底部「取消 + 主操作」按钮行。"""
        btn_layout = QHBoxLayout()
        primary_btn = QPushButton(primary_text)
        primary_btn.setFixedHeight(32)
        primary_btn.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        primary_btn.setStyleSheet(self._PRIMARY_BTN_STYLE)
        primary_btn.clicked.connect(primary_slot)
        cancel_btn = QPushButton("取消")
        cancel_btn.setFixedHeight(32)
        cancel_btn.setFont(QFont("Microsoft YaHei", 10))
        cancel_btn.setStyleSheet(self._SECONDARY_BTN_STYLE)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(primary_btn)
        return btn_layout

    def browse_file(self):
        """弹出文件选择对话框，选中后写入 self.path_input。"""
        _browse_script_file(self, self.path_input)


class SingleScriptConfigDialog(_FormDialogBase):
    """单个脚本的配置弹窗（路径选择 + 每周超时时间 + 配置文件 / 删除脚本）"""

    delete_requested = Signal(str)

    def __init__(
        self,
        display_name,
        script_path="",
        parent=None,
        script_service=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(f"配置 {display_name}")
        self.resize(720, 500)
        self.setStyleSheet("background-color: #f7f8fa;")

        self.display_name = display_name
        self.script_path = script_path
        self.saved_display_name = display_name  # 保存后最终生效的名称（可能被改名）
        self._script_data = {}  # 从 config.yml 读到的本脚本完整数据
        self._script_service = script_service or ScriptService()
        self.pending_changes = None  # accept() 后供调用方取表单字段与 weekly

        self.init_ui()
        self.load_data()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # ---- 脚本名称 ----
        row_name = QHBoxLayout()
        row_name.setSpacing(8)
        name_label = self._make_label("脚本名称:")
        self.name_input = QLineEdit(self)
        self.name_input.setFont(QFont("Microsoft YaHei", 10))
        self.name_input.setPlaceholderText("脚本显示名称，例如：1999")
        self.name_input.setStyleSheet(self._LINE_EDIT_STYLE)
        row_name.addWidget(name_label)
        row_name.addWidget(self.name_input, 1)
        layout.addLayout(row_name)

        # ---- 脚本路径 ----
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        label = self._make_label("脚本路径:")
        self.path_input = QLineEdit(self)
        self.path_input.setFont(QFont("Microsoft YaHei", 10))
        self.path_input.setText(self.script_path)
        self.path_input.setStyleSheet(self._LINE_EDIT_STYLE)
        self.browse_btn = make_secondary_button("选择")
        self.browse_btn.clicked.connect(self.browse_file)
        row1.addWidget(label)
        row1.addWidget(self.path_input)
        row1.addWidget(self.browse_btn)
        layout.addLayout(row1)

        # ---- 脚本类型 + 启动参数 ----
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        type_label = self._make_label("脚本类型:")
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
        self.args_input.setStyleSheet(self._LINE_EDIT_STYLE)
        row2.addWidget(args_label)
        row2.addWidget(self.args_input, 1)
        layout.addLayout(row2)

        # ---- 完成检测方式 ----
        row3 = QHBoxLayout()
        row3.setSpacing(8)
        check_label = self._make_label("完成检测:")
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
        row4.addWidget(self.block_cb)
        row4.addStretch()
        layout.addLayout(row4)

        # ---- 游戏进程名称 ----
        row5 = QHBoxLayout()
        row5.setSpacing(8)
        game_label = self._make_label("游戏进程:")
        self.game_process_input = QLineEdit(self)
        self.game_process_input.setFont(QFont("Microsoft YaHei", 10))
        self.game_process_input.setPlaceholderText("关闭游戏时必填，例如 YuanShen.exe")
        self.game_process_input.setStyleSheet(self._LINE_EDIT_STYLE)
        self.game_process_input.setEnabled(False)
        row5.addWidget(game_label)
        row5.addWidget(self.game_process_input)
        layout.addLayout(row5)

        # ---- 每周超时 ----
        row6 = QHBoxLayout()
        row6.setSpacing(8)
        timeout_label = self._make_label("每周超时:")
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

        # ---- 其它操作：配置文件 / 删除脚本 ----
        row_ops = QHBoxLayout()
        row_ops.setSpacing(8)
        open_cfg_btn = QPushButton("配置文件")
        open_cfg_btn.setFixedHeight(32)
        open_cfg_btn.setFont(QFont("Microsoft YaHei", 10))
        open_cfg_btn.setStyleSheet(self._SECONDARY_BTN_STYLE)
        open_cfg_btn.clicked.connect(self._open_config_file)
        row_ops.addWidget(open_cfg_btn)

        delete_btn = QPushButton("删除脚本")
        delete_btn.setFixedHeight(32)
        delete_btn.setFont(QFont("Microsoft YaHei", 10))
        delete_btn.setStyleSheet(self._DANGER_BTN_STYLE)
        delete_btn.clicked.connect(self._on_delete_clicked)
        row_ops.addWidget(delete_btn)
        row_ops.addStretch()
        layout.addLayout(row_ops)
        self._delete_btn = delete_btn

        # ---- 按钮 ----
        layout.addLayout(self._make_buttons("保存", self.save_data))

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

    def _on_kill_game_changed(self, state):
        self.game_process_input.setEnabled(state == Qt.Checked)

    def _find_script_data(self) -> dict:
        """从 config.yml 读取本脚本的完整数据字典。

        config.yml 缺失属内部错误（对话框只在 config.yml 已加载的前提下打开），
        必须存在，故用 assert 表达不该发生；脚本不在表中才返回空 dict。
        """
        script = self._script_service.get_script(self.display_name)
        return script if script is not None else {}

    def load_data(self):
        self._script_data = self._find_script_data()

        # 脚本名称
        self.name_input.setText(self.display_name)
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
        timeouts = self._script_service.weekly_inputs(self.display_name)
        for idx, le in enumerate(self.timeout_inputs):
            le.setText(str(timeouts[idx]))

    def save_data(self):
        """收集表单数据存入 self.pending_changes 后 accept()；写盘由调用方完成。

        不再直接调 ScriptService.update_script() 写 config.yml——config.yml
        的写入权归 MainWindow/ChainService。weekly_timeouts 也由调用方
        决定是否持久化（通常紧跟 config 写盘后通过 ScriptService 保存）。
        """
        path_val = self.path_input.text().strip()
        if not path_val:
            QMessageBox.warning(self, "警告", "脚本路径为空，可能会导致运行问题！")
            return

        new_display_name = self.name_input.text().strip()
        if not new_display_name:
            QMessageBox.warning(self, "警告", "脚本名称不能为空！")
            return
        existing = self._script_service.get_script(new_display_name)
        if existing is not None and new_display_name != self.display_name:
            QMessageBox.warning(
                self, "警告", f"已存在同名脚本「{new_display_name}」，请换一个名称。"
            )
            return

        if self.kill_game_cb.isChecked() and not self.game_process_input.text().strip():
            QMessageBox.warning(
                self,
                "提示",
                "未填写游戏进程名，保存后「运行结束后关闭游戏」将自动关闭。",
            )

        timeouts = []
        for le in self.timeout_inputs:
            text = le.text().strip()
            timeouts.append(int(text) if text else None)

        self.saved_display_name = new_display_name
        self.pending_changes = {
            "old_display_name": self.display_name,
            "new_display_name": new_display_name,
            "config_patch": {
                "script_path": path_val,
                "script_type": self.type_combo.currentText(),
                "script_arguments": self.args_input.text().strip(),
                "check_done": self.check_done_combo.currentText(),
                "kill_script_after_done": self.kill_script_cb.isChecked(),
                "kill_game_after_done": self.kill_game_cb.isChecked(),
                "game_process_name": self.game_process_input.text().strip(),
                "block": self.block_cb.isChecked(),
            },
            "weekly_timeouts": timeouts,
        }
        self.accept()

    def _open_config_file(self):
        """打开本脚本的配置文件：路径计算委托 ScriptService，GUI 只负责打开或提示。"""
        path, error = self._script_service.config_file_path(self.display_name)
        if error is not None:
            _styled_msg_box(self, QMessageBox.Warning, "提示", error).exec()
            return
        safe_startfile(self, path, "无法打开配置文件")

    def _on_delete_clicked(self):
        """删除本脚本：二次确认后通知外部并关闭弹窗。"""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("删除脚本")
        box.setText(f"确定删除「{self.display_name}」？此操作不可撤销。")
        box.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        box.setDefaultButton(QMessageBox.Cancel)
        if box.exec() != QMessageBox.Ok:
            return
        self.delete_requested.emit(self.display_name)
        self.close()


class AddScriptDialog(_FormDialogBase):
    """新增脚本弹窗：收集核心字段（名称、类型、路径、超时），其余字段用默认值补全。"""

    def __init__(self, existing_names=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加脚本")
        self.resize(560, 250)
        self.setStyleSheet("background-color: #f7f8fa;")
        self._existing_names = set(existing_names or [])
        self.script_entry = None
        self.init_ui()

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
        self.name_input.setStyleSheet(self._LINE_EDIT_STYLE)
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
        self.type_combo.setStyleSheet(self._COMBO_STYLE)
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
        self.path_input.setStyleSheet(self._LINE_EDIT_STYLE)
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
        self.args_input.setStyleSheet(self._LINE_EDIT_STYLE)
        args_row.addWidget(self._make_label("启动参数:"))
        args_row.addWidget(self.args_input)
        layout.addLayout(args_row)

        # 按钮
        layout.addLayout(self._make_buttons("添加", self.save_data))

    def save_data(self):
        display_name = self.name_input.text().strip()
        if not display_name:
            QMessageBox.warning(self, "警告", "脚本名称不能为空！")
            return
        if display_name in self._existing_names:
            QMessageBox.warning(
                self, "警告", f"已存在同名脚本「{display_name}」，请换一个名称。"
            )
            return
        path_val = self.path_input.text().strip()
        if not path_val:
            QMessageBox.warning(self, "警告", "脚本路径不能为空！")
            return

        self.script_entry = default_script_entry(
            display_name=display_name,
            script_type=self.type_combo.currentText(),
            script_path=path_val,
            script_arguments=self.args_input.text().strip(),
        )
        self.accept()
