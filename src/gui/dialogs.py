"""弹窗：单脚本配置（路径 + 每周超时）与添加脚本。"""

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from src.config.set_config import ScriptConfig
from src.config.subscript import default_script_entry
from src.gui import theme
from src.gui.utils import _styled_msg_box, make_secondary_button, safe_startfile
from src.service.script_service import ScriptService

# 脚本文件选择过滤器（两个弹窗共用）
SCRIPT_FILE_FILTER = (
    "可执行文件 Executable files (*.exe *.bat *.py);;所有文件 All files (*.*)"
)

# 表单输入控件宽度上下限（限制 input 不拉满整个弹窗，保留右侧空白感）
INPUT_MAX_W = 320
INPUT_FIXED_W = 320


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
    """表单弹窗基类：共享样式常量（来自 theme）与 label/按钮行构造。"""

    LABEL_WIDTH = theme.LABEL_WIDTH
    _LINE_EDIT_STYLE = theme.line_edit_qss()
    _COMBO_STYLE = theme.combo_box_qss()
    _CHECK_STYLE = theme.check_box_qss()
    _PRIMARY_BTN_STYLE = theme.primary_button_qss(
        radius=6, font_size=theme.FONT_SIZE_BODY
    )
    _SECONDARY_BTN_STYLE = theme.secondary_button_qss(font_size=theme.FONT_SIZE_BODY)
    _DANGER_BTN_STYLE = theme.danger_button_qss(font_size=theme.FONT_SIZE_BODY)

    def _make_label(self, text) -> QLabel:
        """构造固定宽度的表单字段标签（无边框透明背景）。"""
        label = QLabel(text)
        font = theme.make_font(size=theme.FONT_SIZE_BODY)
        label.setFont(font)
        label.setFixedWidth(self.LABEL_WIDTH)
        label.setStyleSheet(
            f"color: {theme.TEXT}; border: none; background: transparent;"
        )
        return label

    def _make_footer(
        self,
        primary_text: str,
        primary_slot,
        *,
        left_widgets: tuple = (),
    ) -> QHBoxLayout:
        """构造底部按钮行：``[left_widgets...] -- stretch -- [取消] [primary]``。"""
        footer = QHBoxLayout()
        footer.setSpacing(8)
        for w in left_widgets:
            footer.addWidget(w)

        cancel_btn = QPushButton("取消")
        cancel_btn.setFixedHeight(28)
        cancel_btn.setMinimumWidth(80)
        font = theme.make_font(size=theme.FONT_SIZE_BODY)
        cancel_btn.setFont(font)
        cancel_btn.setStyleSheet(self._SECONDARY_BTN_STYLE)
        cancel_btn.clicked.connect(self.reject)

        primary_btn = QPushButton(primary_text)
        primary_btn.setFixedHeight(28)
        primary_btn.setMinimumWidth(80)
        font = theme.make_font(size=theme.FONT_SIZE_BTN, bold=True)
        primary_btn.setFont(font)
        primary_btn.setStyleSheet(self._PRIMARY_BTN_STYLE)
        primary_btn.clicked.connect(primary_slot)

        footer.addStretch()
        footer.addWidget(cancel_btn)
        footer.addWidget(primary_btn)
        return footer

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
        self.setStyleSheet(f"background-color: {theme.BG_HOVER};")

        self.display_name = display_name
        self.script_path = script_path
        self.saved_display_name = display_name  # 保存后最终生效的名称（可能被改名）
        self._script_data = {}  # 从 config.yml 读到的本脚本完整数据
        self._script_service = script_service or ScriptService()
        self.pending_changes = None  # accept() 后供调用方取表单字段与 weekly

        self.init_ui()
        self.load_data()

    def init_ui(self):
        """用 QGridLayout：所有 label 在 col 0、input 在 col 1（stretch=1），自动等宽对齐。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 0)

        # 行 0：脚本名称 + name_input
        name_label = self._make_label("脚本名称:")
        self.name_input = QLineEdit(self)
        font = theme.make_font(size=theme.FONT_SIZE_BODY)
        self.name_input.setFont(font)
        self.name_input.setPlaceholderText("脚本显示名称，例如：1999")
        self.name_input.setFixedWidth(INPUT_FIXED_W)
        self.name_input.setFixedHeight(30)
        self.name_input.setStyleSheet(self._LINE_EDIT_STYLE)
        grid.addWidget(name_label, 0, 0)
        grid.addWidget(self.name_input, 0, 1)

        # 行 1：脚本路径 + path_input + browse_btn
        path_label = self._make_label("脚本路径:")
        self.path_input = QLineEdit(self)
        font = theme.make_font(size=theme.FONT_SIZE_BODY)
        self.path_input.setFont(font)
        self.path_input.setText(self.script_path)
        self.path_input.setReadOnly(True)  # 只显示路径，编辑通过重新选择完成
        self.path_input.setFixedWidth(INPUT_FIXED_W)
        self.path_input.setFixedHeight(30)
        self.path_input.setStyleSheet(self._LINE_EDIT_STYLE)
        # 点击 input 触发文件选择（替代外部"选择"按钮）
        path_orig_press = self.path_input.mousePressEvent

        def _path_press(event):
            if event.button() == Qt.LeftButton:
                self.browse_file()
            path_orig_press(event)

        self.path_input.mousePressEvent = _path_press
        grid.addWidget(path_label, 1, 0)
        grid.addWidget(self.path_input, 1, 1)

        # 行 2：脚本类型 + type_combo
        type_label = self._make_label("脚本类型:")
        self.type_combo = QComboBox(self)
        self.type_combo.addItems(["external", "python"])
        font = theme.make_font(size=theme.FONT_SIZE_BODY)
        self.type_combo.setFont(font)
        self.type_combo.setFixedWidth(INPUT_FIXED_W)
        self.type_combo.setFixedHeight(30)
        self.type_combo.setStyleSheet(self._COMBO_STYLE)
        grid.addWidget(type_label, 2, 0)
        grid.addWidget(self.type_combo, 2, 1)

        # 行 3：启动参数 + args_input（横跨 col 1-2）
        args_label = QLabel("启动参数:")
        font = theme.make_font(size=theme.FONT_SIZE_BODY)
        args_label.setFont(font)
        args_label.setStyleSheet(
            f"color: {theme.TEXT}; border: none; background: transparent;"
        )
        self.args_input = QLineEdit(self)
        font = theme.make_font(size=theme.FONT_SIZE_BODY)
        self.args_input.setFont(font)
        self.args_input.setPlaceholderText("可选，传给脚本的命令行参数")
        self.args_input.setFixedWidth(INPUT_FIXED_W)
        self.args_input.setFixedHeight(30)
        self.args_input.setStyleSheet(self._LINE_EDIT_STYLE)
        grid.addWidget(args_label, 3, 0)
        grid.addWidget(self.args_input, 3, 1, 1, 2)

        # 行 4：完成检测 + check_done_combo（横跨 col 1-2）
        check_label = self._make_label("完成检测:")
        self.check_done_combo = QComboBox(self)
        self.check_done_combo.addItems(
            [
                "game_or_script_closed",
                "script_closed",
                "game_closed",
            ]
        )
        font = theme.make_font(size=theme.FONT_SIZE_BODY)
        self.check_done_combo.setFont(font)
        self.check_done_combo.setFixedWidth(INPUT_FIXED_W)
        self.check_done_combo.setFixedHeight(30)
        self.check_done_combo.setStyleSheet(self._COMBO_STYLE)
        grid.addWidget(check_label, 4, 0)
        grid.addWidget(self.check_done_combo, 4, 1, 1, 2)

        # 行 5：复选框行（横跨 col 1-2）
        checkbox_row = QHBoxLayout()
        checkbox_row.setSpacing(12)
        self.kill_script_cb = QCheckBox("结束后关闭脚本", self)
        font = theme.make_font(size=theme.FONT_SIZE_BODY)
        self.kill_script_cb.setFont(font)
        self.kill_script_cb.setStyleSheet(self._CHECK_STYLE)
        self.kill_game_cb = QCheckBox("结束后关闭游戏", self)
        font = theme.make_font(size=theme.FONT_SIZE_BODY)
        self.kill_game_cb.setFont(font)
        self.kill_game_cb.setStyleSheet(self._CHECK_STYLE)
        self.kill_game_cb.stateChanged.connect(self._on_kill_game_changed)
        self.block_cb = QCheckBox("阻塞运行", self)
        font = theme.make_font(size=theme.FONT_SIZE_BODY)
        self.block_cb.setFont(font)
        self.block_cb.setStyleSheet(self._CHECK_STYLE)
        checkbox_row.addWidget(self.kill_script_cb)
        checkbox_row.addWidget(self.kill_game_cb)
        checkbox_row.addWidget(self.block_cb)
        checkbox_row.addStretch()
        grid.addLayout(checkbox_row, 5, 1, 1, 2)

        # 行 6：游戏进程 + game_process_input（横跨 col 1-2）
        game_label = self._make_label("游戏进程:")
        self.game_process_input = QLineEdit(self)
        font = theme.make_font(size=theme.FONT_SIZE_BODY)
        self.game_process_input.setFont(font)
        self.game_process_input.setPlaceholderText(
            "关闭游戏时必填，例如 YuanShen.exe"
        )
        self.game_process_input.setFixedWidth(INPUT_FIXED_W)
        self.game_process_input.setFixedHeight(30)
        self.game_process_input.setStyleSheet(self._LINE_EDIT_STYLE)
        self.game_process_input.setEnabled(False)
        grid.addWidget(game_label, 6, 0)
        grid.addWidget(self.game_process_input, 6, 1, 1, 2)

        # 行 7：每周超时（4×2 Grid 让同列等宽，数字右对齐）
        timeout_label = self._make_label("每周超时:")
        timeout_grid = QGridLayout()
        timeout_grid.setHorizontalSpacing(4)
        timeout_grid.setVerticalSpacing(2)
        day_names = ["一", "二", "三", "四", "五", "六", "日"]
        self.timeout_inputs = []
        for day_idx, day_name in enumerate(day_names):
            row = day_idx // 4
            col = (day_idx % 4) * 2
            day_label = QLabel(f"周{day_name}")
            day_label.setFont(theme.make_font(size=theme.FONT_SIZE_BODY))
            day_label.setStyleSheet(
                f"color: {theme.TEXT_MUTED}; border: none; background: transparent;"
            )
            day_label.setFixedWidth(22)
            lineedit = QLineEdit(self)
            lineedit.setFont(theme.make_font(size=theme.FONT_SIZE_BODY))
            lineedit.setValidator(QIntValidator(10, 86400, self))
            lineedit.setAlignment(Qt.AlignRight)  # 数字右对齐
            lineedit.setFixedWidth(50)
            lineedit.setMinimumWidth(50)
            lineedit.setStyleSheet(self._TIMEOUT_INPUT_STYLE)
            timeout_grid.addWidget(day_label, row, col)
            timeout_grid.addWidget(lineedit, row, col + 1)
            self.timeout_inputs.append(lineedit)
        grid.addWidget(timeout_label, 7, 0)
        grid.addLayout(timeout_grid, 7, 1, 1, 2)

        # 底部按钮行：左次要（配置文件 / 删除脚本）+ 右主操作（取消 / 保存）
        open_cfg_btn = QPushButton("配置文件")
        open_cfg_btn.setFixedHeight(28)
        open_cfg_btn.setMinimumWidth(90)
        font = theme.make_font(size=theme.FONT_SIZE_BODY)
        open_cfg_btn.setFont(font)
        open_cfg_btn.setStyleSheet(self._SECONDARY_BTN_STYLE)
        open_cfg_btn.clicked.connect(self._open_config_file)

        delete_btn = QPushButton("删除脚本")
        delete_btn.setFixedHeight(28)
        delete_btn.setMinimumWidth(90)
        font = theme.make_font(size=theme.FONT_SIZE_BODY)
        delete_btn.setFont(font)
        delete_btn.setStyleSheet(self._DANGER_BTN_STYLE)
        delete_btn.clicked.connect(self._on_delete_clicked)
        self._delete_btn = delete_btn

        footer = self._make_footer(
            "保存", self.save_data, left_widgets=(open_cfg_btn, delete_btn)
        )

        layout.addLayout(grid)
        layout.addLayout(footer)

    _TIMEOUT_INPUT_STYLE = theme.small_line_edit_qss(text_align="right")

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
                "未填写游戏进程名，保存后「结束后关闭游戏」将自动关闭。",
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
        self.setStyleSheet(f"background-color: {theme.BG_HOVER};")
        self._existing_names = set(existing_names or [])
        self.script_entry = None
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # 名称
        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        self.name_input = QLineEdit(self)
        font = theme.make_font(size=theme.FONT_SIZE_BODY)
        self.name_input.setFont(font)
        self.name_input.setPlaceholderText("脚本显示名称，例如：1999")
        self.name_input.setFixedWidth(INPUT_FIXED_W)
        self.name_input.setFixedHeight(30)
        self.name_input.setStyleSheet(self._LINE_EDIT_STYLE)
        name_row.addWidget(self._make_label("脚本名称:"))
        name_row.addWidget(self.name_input)
        layout.addLayout(name_row)

        # 类型
        type_row = QHBoxLayout()
        type_row.setSpacing(8)
        self.type_combo = QComboBox(self)
        self.type_combo.addItems(["external", "python"])
        font = theme.make_font(size=theme.FONT_SIZE_BODY)
        self.type_combo.setFont(font)
        self.type_combo.setFixedHeight(30)
        self.type_combo.setFixedWidth(INPUT_FIXED_W)
        self.type_combo.setStyleSheet(self._COMBO_STYLE)
        type_row.addWidget(self._make_label("脚本类型:"))
        type_row.addWidget(self.type_combo)
        type_row.addStretch()
        layout.addLayout(type_row)

        # 路径 + 浏览
        path_row = QHBoxLayout()
        path_row.setSpacing(8)
        self.path_input = QLineEdit(self)
        font = theme.make_font(size=theme.FONT_SIZE_BODY)
        self.path_input.setFont(font)
        self.path_input.setPlaceholderText("脚本/程序的完整路径")
        self.path_input.setFixedWidth(INPUT_FIXED_W)
        self.path_input.setFixedHeight(30)
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
        font = theme.make_font(size=theme.FONT_SIZE_BODY)
        self.args_input.setFont(font)
        self.args_input.setPlaceholderText("可选，传给脚本的命令行参数")
        self.args_input.setFixedWidth(INPUT_FIXED_W)
        self.args_input.setFixedHeight(30)
        self.args_input.setStyleSheet(self._LINE_EDIT_STYLE)
        args_row.addWidget(self._make_label("启动参数:"))
        args_row.addWidget(self.args_input)
        layout.addLayout(args_row)

        # 按钮
        layout.addLayout(self._make_footer("添加", self.save_data))

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
