"""单脚本配置弹窗（SingleScriptConfigDialog）。

自包含模块：样式常量（原 src/gui/theme.py 子集）与工具函数（styled_msg_box /
safe_startfile，原 src/gui/utils.py）已并入本文件（2026-08-16），src/gui 其余
模块随之删除。依赖仅剩 config/service 业务层与 PySide6。

对外接口：
- ``SingleScriptConfigDialog``：单脚本配置弹窗（名称/路径/类型/参数/完成检测/
  关闭脚本/关闭游戏/阻塞/游戏进程/每周超时），保存后经 ``pending_changes`` 返回，
  写盘由调用方委托 ``ChainService.update_script``。脚本删除改由左侧列表交互完成。
- 「启动全部」前的运行确认弹窗已独立为 ``src/gui/run_confirm_dialog.py``
  （单一职责：仅承载运行前确认交互，复用本模块的基类与主题常量）。
"""

import os
import warnings

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIntValidator
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

from src.config.set_config import (
    supports_weekly,
)
from src.config.subscript import get_script_name
from src.service.app_service import AppService

# ═══════════════════════ 弹窗样式（原 src/gui/theme.py 子集，2026-08-16 并入）═══════
DARK_BLUE = "#333957"  # 深空蓝
BLUE = "#5D74A2"  # 钢蓝
SKY_BLUE = "#C4D8F2"  # 雾蓝

TEXT = DARK_BLUE  # 正文
TEXT_MUTED = DARK_BLUE  # 次要文字
TEXT_FAINT = DARK_BLUE  # 弱文字 / 占位
BG_CARD = "#FFFFFF"  # 卡片底
BG_HOVER = SKY_BLUE  # 悬停底
BORDER = SKY_BLUE  # 中性边框
DISABLED = SKY_BLUE  # 禁用底色
BORDER_WIDTH = "1px"  # 统一边框宽度（QSS 模板引用）

FONT_FAMILY = '"Microsoft YaHei", "Segoe UI", sans-serif'

FONT_SIZE_BODY = 11  # 正文：输入框 / 下拉框 / 表单标签
FONT_SIZE_BTN = 12  # 按钮：主 / 次级 / 危险

LABEL_WIDTH = 64  # 表单标签固定宽


def make_font(*, size: int = FONT_SIZE_BODY, bold: bool = False) -> QFont:
    """统一构造像素字号的 QFont（避免 point size 与 QSS px 差异 + 字体名硬编码）。"""
    font = QFont("Microsoft YaHei")
    font.setPixelSize(size)
    if bold:
        font.setBold(True)
    return font


def primary_button_qss(*, radius: int = 10, font_size: int = FONT_SIZE_BTN) -> str:
    """主按钮：钢蓝纯色底 + 白字（平面风格，无渐变）。"""
    return f"""
        QPushButton {{
            background: {BLUE};
            color: white;
            border: none;
            border-radius: {radius}px;
            font-size: {font_size}px;
        }}
        QPushButton:hover {{ background: {DARK_BLUE}; }}
        QPushButton:pressed {{ background: {DARK_BLUE}; }}
        QPushButton:disabled {{ background: {DISABLED}; color: #F0F3F8; }}
    """


def outlined_qss(
    *,
    selector: str = "QPushButton",
    accent: str = BLUE,
    radius: int = 8,
    font_size: int = FONT_SIZE_BODY,
    color: str = DARK_BLUE,
    border: str = BORDER,
    padding: str = "4px 10px",
) -> str:
    """轮廓控件模板（次级按钮 / 危险按钮共用）：透明底 + 圆角边框，hover 变色。"""
    return f"""
        {selector} {{
            border: {BORDER_WIDTH} solid {border};
            border-radius: {radius}px;
            background: transparent;
            font-family: {FONT_FAMILY};
            font-size: {font_size}px;
            color: {color};
            padding: {padding};
        }}
        {selector}:hover {{ border-color: {accent}; color: {accent}; }}
        {selector}:disabled {{ color: {TEXT_FAINT}; border-color: {DISABLED}; }}
    """


def line_edit_qss(
    *,
    radius: int = 8,
    font_size: int = FONT_SIZE_BODY,
    padding: str = "6px 12px",
) -> str:
    """文本输入框：白底灰边，focus 钢蓝边框。"""
    return f"""
        QLineEdit {{
            border: {BORDER_WIDTH} solid {BORDER};
            border-radius: {radius}px;
            padding: {padding};
            background: white;
            font-size: {font_size}px;
            color: {TEXT};
        }}
        QLineEdit:focus {{ border-color: {BLUE}; outline: none; }}
    """


def small_line_edit_qss(
    *, radius: int = 6, font_size: int = FONT_SIZE_BODY, text_align: str = "center"
) -> str:
    """紧凑文本输入框（每周超时数字框）：居中或右对齐显示。"""
    return f"""
        QLineEdit {{
            border: {BORDER_WIDTH} solid {BORDER};
            border-radius: {radius}px;
            padding: 4px 8px;
            background: white;
            font-size: {font_size}px;
            text-align: {text_align};
            color: {TEXT};
        }}
        QLineEdit:focus {{ border-color: {BLUE}; outline: none; }}
    """


def combo_box_qss(*, radius: int = 8, font_size: int = FONT_SIZE_BODY) -> str:
    """下拉框：白底灰边，drop-down 无独立边框。"""
    return f"""
        QComboBox {{
            border: {BORDER_WIDTH} solid {BORDER};
            border-radius: {radius}px;
            padding: 4px 12px;
            background: white;
            font-size: {font_size}px;
            color: {TEXT};
        }}
        QComboBox:hover {{ border-color: {BLUE}; }}
        QComboBox::drop-down {{ border: none; width: 20px; }}
    """


def check_box_qss(*, size: int = 16) -> str:
    """复选框：只定制文字颜色，indicator 完全走平台原生。"""
    return f"""
        QCheckBox {{
            color: {TEXT};
        }}
        QCheckBox:disabled {{ color: {TEXT_FAINT}; }}
    """


def message_box_qss() -> str:
    """消息框：白底深字 + 中性按钮。"""
    return f"""
        QMessageBox {{ background-color: white; color: {TEXT}; }}
        QMessageBox QLabel {{ color: {TEXT}; background-color: transparent; }}
        QMessageBox QPushButton {{
            background-color: #F1F5F9; color: {TEXT};
            border: {BORDER_WIDTH} solid {BORDER}; border-radius: 6px; padding: 6px 16px;
        }}
        QMessageBox QPushButton:hover {{ background-color: {BG_HOVER}; }}
    """


# ═══════════════════════ 弹窗工具（原 src/gui/utils.py，2026-08-16 并入）════════
def styled_msg_box(parent, icon, title, text):
    """构造一个样式固定的消息框（白底深字，带图标），直接 .exec() 即可。"""
    box = QMessageBox(parent)
    box.setIcon(icon)
    box.setWindowTitle(title)
    box.setText(text)
    box.setTextFormat(Qt.PlainText)
    box.setStyleSheet(message_box_qss())
    return box


def safe_startfile(parent, path, fail_text):
    """用系统默认程序打开 path；任何异常都转成清晰可读的提示，不让 GUI 崩溃。"""
    try:
        os.startfile(path)
    except (OSError, AttributeError) as e:
        warnings.warn(f"{fail_text}: {e}", RuntimeWarning, stacklevel=2)
        styled_msg_box(
            parent, QMessageBox.Warning, "提示", f"{fail_text}：\n{e}"
        ).exec()


# ═══════════════════════ 弹窗逻辑 ═══════════════════════════════════════════
# 脚本文件选择过滤器（路径选择弹窗用）
SCRIPT_FILE_FILTER = (
    "可执行文件 Executable files (*.exe *.bat *.py);;所有文件 All files (*.*)"
)

# 表单输入控件默认尺寸（限制 input 不拉满整个弹窗，保留右侧空白感）
INPUT_FIXED_W = 320
INPUT_FIXED_H = 30

# 下拉框选项
SCRIPT_TYPES = ["external", "python"]
CHECK_DONE_OPTIONS = ["game_or_script_closed", "script_closed", "game_closed"]

# 每周超时：周一到周日 7 个数字框，秒数上限 24h
WEEKDAY_SHORT_NAMES = ["一", "二", "三", "四", "五", "六", "日"]
MAX_DAILY_TIMEOUT_SECONDS = 86400


def _browse_script_file(parent, target_edit):
    """弹出文件选择对话框，选中后规范化为系统路径写入 target_edit"""
    file_path, _ = QFileDialog.getOpenFileName(
        parent, "选择脚本文件", "", SCRIPT_FILE_FILTER
    )
    if file_path:
        target_edit.setText(os.path.normpath(file_path))


class FormDialogBase(QDialog):
    """表单弹窗基类：共享样式常量与控件/label/按钮行构造。"""

    _LINE_EDIT_STYLE = line_edit_qss()
    _COMBO_STYLE = combo_box_qss()
    _CHECK_STYLE = check_box_qss()
    _PRIMARY_BTN_STYLE = primary_button_qss(radius=6, font_size=FONT_SIZE_BODY)
    _SECONDARY_BTN_STYLE = outlined_qss(
        selector="QPushButton",
        radius=10,
        font_size=FONT_SIZE_BODY,
        color=TEXT,
        padding="0 16px",
    )

    def _make_label(self, text) -> QLabel:
        """构造固定宽度的表单字段标签（无边框透明背景）。"""
        label = QLabel(text)
        label.setFont(make_font(size=FONT_SIZE_BODY))
        label.setFixedWidth(LABEL_WIDTH)
        label.setStyleSheet(f"color: {TEXT}; border: none; background: transparent;")
        return label

    def _make_line_edit(
        self,
        *,
        placeholder: str = "",
        read_only: bool = False,
        width: int = INPUT_FIXED_W,
        height: int = INPUT_FIXED_H,
        style: str | None = None,
    ) -> QLineEdit:
        """构造统一样式的文本输入框（字体/尺寸/QSS 一次配齐）。"""
        edit = QLineEdit(self)
        edit.setFont(make_font(size=FONT_SIZE_BODY))
        if placeholder:
            edit.setPlaceholderText(placeholder)
        if read_only:
            edit.setReadOnly(True)
        edit.setFixedWidth(width)
        edit.setFixedHeight(height)
        edit.setStyleSheet(style or self._LINE_EDIT_STYLE)
        return edit

    def _make_combo(self, items: list[str]) -> QComboBox:
        """构造统一样式的下拉框（选项/字体/尺寸/QSS 一次配齐）。"""
        combo = QComboBox(self)
        combo.addItems(items)
        combo.setFont(make_font(size=FONT_SIZE_BODY))
        combo.setFixedWidth(INPUT_FIXED_W)
        combo.setFixedHeight(INPUT_FIXED_H)
        combo.setStyleSheet(self._COMBO_STYLE)
        return combo

    def _make_checkbox(self, text: str) -> QCheckBox:
        """构造统一样式的复选框（字体/QSS 一次配齐）。"""
        cb = QCheckBox(text, self)
        cb.setFont(make_font(size=FONT_SIZE_BODY))
        cb.setStyleSheet(self._CHECK_STYLE)
        return cb

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
        cancel_btn.setFont(make_font(size=FONT_SIZE_BODY))
        cancel_btn.setStyleSheet(self._SECONDARY_BTN_STYLE)
        cancel_btn.clicked.connect(self.reject)

        primary_btn = QPushButton(primary_text)
        primary_btn.setFixedHeight(28)
        primary_btn.setMinimumWidth(80)
        primary_btn.setFont(make_font(size=FONT_SIZE_BTN, bold=True))
        primary_btn.setStyleSheet(self._PRIMARY_BTN_STYLE)
        primary_btn.clicked.connect(primary_slot)

        footer.addStretch()
        footer.addWidget(cancel_btn)
        footer.addWidget(primary_btn)
        return footer

    def browse_file(self):
        """弹出文件选择对话框，选中后写入 self.path_input。"""
        _browse_script_file(self, self.path_input)


class SingleScriptConfigDialog(FormDialogBase):
    """单个脚本的配置弹窗（路径选择 + 每周超时时间，删除改由左侧列表交互完成）。"""

    _TIMEOUT_INPUT_STYLE = small_line_edit_qss(text_align="right")

    def __init__(
        self,
        script_name,
        display_name,
        script_path="",
        parent=None,
        app_service=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(f"配置 {display_name}")
        self.setStyleSheet(f"background-color: {BG_CARD};")

        self.script_name = (
            script_name  # 内部标识：exe 用进程名，脚本文件用 display_name
        )
        self.display_name = display_name  # 展示名
        self.script_path = script_path
        self._app_service = app_service or AppService()
        self.pending_changes = None  # accept() 后供调用方取表单字段与 weekly

        self.init_ui()
        self.load_data()

    def init_ui(self):
        """用 QGridLayout：所有 label 在 col 0、input 在 col 1（固定宽），自动等宽对齐。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 0)

        # 行 0：脚本名称 + name_input
        self.name_input = self._make_line_edit(placeholder="脚本显示名称，例如：1999")
        grid.addWidget(self._make_label("脚本名称:"), 0, 0)
        grid.addWidget(self.name_input, 0, 1)

        # 行 1：脚本路径 + path_input（点击触发文件选择）
        self.path_input = self._make_line_edit(read_only=True)
        self.path_input.setText(self.script_path)
        path_orig_press = self.path_input.mousePressEvent

        def _path_press(event):
            if event.button() == Qt.LeftButton:
                self.browse_file()
            path_orig_press(event)

        self.path_input.mousePressEvent = _path_press
        grid.addWidget(self._make_label("脚本路径:"), 1, 0)
        grid.addWidget(self.path_input, 1, 1)

        # 行 2：脚本类型 + type_combo
        self.type_combo = self._make_combo(SCRIPT_TYPES)
        grid.addWidget(self._make_label("脚本类型:"), 2, 0)
        grid.addWidget(self.type_combo, 2, 1)

        # 行 3：启动参数 + args_input（横跨 col 1-2）
        self.args_input = self._make_line_edit(placeholder="可选，传给脚本的命令行参数")
        grid.addWidget(self._make_label("启动参数:"), 3, 0)
        grid.addWidget(self.args_input, 3, 1, 1, 2)

        # 行 4：完成检测 + check_done_combo（横跨 col 1-2）
        self.check_done_combo = self._make_combo(CHECK_DONE_OPTIONS)
        grid.addWidget(self._make_label("完成检测:"), 4, 0)
        grid.addWidget(self.check_done_combo, 4, 1, 1, 2)

        # 行 5：复选框行（横跨 col 1-2）
        checkbox_row = QHBoxLayout()
        checkbox_row.setSpacing(12)
        self.kill_script_cb = self._make_checkbox("结束后关闭脚本")
        self.kill_game_cb = self._make_checkbox("结束后关闭游戏")
        self.kill_game_cb.stateChanged.connect(self._on_kill_game_changed)
        self.block_cb = self._make_checkbox("阻塞运行")
        checkbox_row.addWidget(self.kill_script_cb)
        checkbox_row.addWidget(self.kill_game_cb)
        checkbox_row.addWidget(self.block_cb)
        checkbox_row.addStretch()
        grid.addLayout(checkbox_row, 5, 1, 1, 2)

        # 行 6：游戏进程 + game_process_input（横跨 col 1-2）
        self.game_process_input = self._make_line_edit(
            placeholder="关闭游戏时必填，例如 YuanShen.exe"
        )
        self.game_process_input.setEnabled(False)
        grid.addWidget(self._make_label("游戏进程:"), 6, 0)
        grid.addWidget(self.game_process_input, 6, 1, 1, 2)

        # 周几起：仅支持周常的脚本显示（选择落到 weekly_start.yml）。
        # 不支持时整行不进布局，超时行上移到行 7，避免空行留白。
        self._weekly_start_supported = supports_weekly(self.script_name)
        timeout_row = 8 if self._weekly_start_supported else 7

        # 周几起（行 7）
        self.weekly_start_combo = self._make_combo(
            ["不设置"] + [f"周{WEEKDAY_SHORT_NAMES[i]}起" for i in range(7)]
        )
        self.weekly_start_combo.setStyleSheet(combo_box_qss())
        if self._weekly_start_supported:
            grid.addWidget(self._make_label("周常周几起:"), 7, 0)
            grid.addWidget(self.weekly_start_combo, 7, 1, 1, 2)
        else:
            # _make_combo 以 self 为父：控件已是 dialog 子控件，不进布局也会按默认
            # 位置 (0,0) 绘制并盖住左上角字段，必须显式 hide()。
            self.weekly_start_combo.hide()

        # 每周超时（4×2 Grid 让同列等宽，数字右对齐）
        timeout_grid = QGridLayout()
        timeout_grid.setHorizontalSpacing(4)
        timeout_grid.setVerticalSpacing(2)
        self.timeout_inputs = []
        for day_idx, day_name in enumerate(WEEKDAY_SHORT_NAMES):
            row = day_idx // 4
            col = (day_idx % 4) * 2
            day_label = QLabel(f"周{day_name}")
            day_label.setFont(make_font(size=FONT_SIZE_BODY))
            day_label.setStyleSheet(
                f"color: {TEXT_MUTED}; border: none; background: transparent;"
            )
            day_label.setFixedWidth(22)
            timeout_edit = self._make_line_edit(
                width=50, height=INPUT_FIXED_H, style=self._TIMEOUT_INPUT_STYLE
            )
            timeout_edit.setValidator(QIntValidator(0, MAX_DAILY_TIMEOUT_SECONDS, self))
            timeout_edit.setAlignment(Qt.AlignRight)  # 数字右对齐
            timeout_grid.addWidget(day_label, row, col)
            timeout_grid.addWidget(timeout_edit, row, col + 1)
            self.timeout_inputs.append(timeout_edit)
        grid.addWidget(self._make_label("每周超时:"), timeout_row, 0)
        grid.addLayout(timeout_grid, timeout_row, 1, 1, 2)

        # 底部按钮行：右主操作（取消 / 保存）
        footer = self._make_footer("保存", self.save_data)

        layout.addLayout(grid)
        layout.addLayout(footer)

    def _on_kill_game_changed(self, state):
        self.game_process_input.setEnabled(state == Qt.Checked)

    def _find_script_data(self) -> dict:
        """从 config.yml 读取本脚本的完整数据字典；脚本不在表中返回空 dict。"""
        script = self._app_service.get_script(self.script_name)
        return script if script is not None else {}

    def load_data(self):
        script_data = self._find_script_data()

        # 脚本名称
        self.name_input.setText(self.display_name)
        # 脚本类型
        self.type_combo.setCurrentText(script_data.get("script_type", "external"))
        # 启动参数
        self.args_input.setText(script_data.get("script_arguments", ""))
        # 完成检测
        self.check_done_combo.setCurrentText(
            script_data.get("check_done", "script_closed")
        )
        # 关闭脚本 / 关闭游戏
        self.kill_script_cb.setChecked(script_data.get("kill_script_after_done", True))
        self.kill_game_cb.setChecked(script_data.get("kill_game_after_done", False))
        self.game_process_input.setText(script_data.get("game_process_name", ""))
        self.game_process_input.setEnabled(self.kill_game_cb.isChecked())
        # 阻塞运行：缺字段视为 True（默认阻塞）
        self.block_cb.setChecked(script_data.get("block", True))

        # 周几起（从 weekly_start.yml 读；不支持周常时跳过）
        if self._weekly_start_supported:
            start_day = self._app_service.get_weekly_start(self.script_name)
            self.weekly_start_combo.setCurrentIndex(
                0 if start_day is None else int(start_day)
            )

        # 每周超时
        timeouts = self._app_service.weekly_inputs(self.script_name)
        for idx, timeout_edit in enumerate(self.timeout_inputs):
            timeout_edit.setText(str(timeouts[idx]))

    def save_data(self):
        """收集表单数据存入 self.pending_changes 后 accept()；写盘由调用方完成。

        不再直接调 ScriptService.update_script() 写 config.yml——config.yml
        的写入权归 ChainService。weekly_timeouts 也由调用方决定是否持久化。
        """
        path_val = self.path_input.text().strip()
        if not path_val:
            QMessageBox.warning(self, "警告", "脚本路径为空，可能会导致运行问题！")
            return

        new_display_name = self.name_input.text().strip()
        if not new_display_name:
            QMessageBox.warning(self, "警告", "脚本名称不能为空！")
            return
        new_script_name = get_script_name(
            {"display_name": new_display_name, "script_path": path_val}
        )
        existing = self._app_service.get_script(new_script_name)
        if existing is not None and new_script_name != self.script_name:
            assert "display_name" in existing, (
                "[dialogs] config 脚本数据缺少 display_name"
            )
            QMessageBox.warning(
                self,
                "警告",
                f"已存在同标识脚本「{existing['display_name']}」，请换一个脚本路径或名称。",
            )
            return

        if self.kill_game_cb.isChecked() and not self.game_process_input.text().strip():
            QMessageBox.warning(
                self,
                "提示",
                "未填写游戏进程名，保存后「结束后关闭游戏」将自动关闭。",
            )

        timeouts = []
        for timeout_edit in self.timeout_inputs:
            text = timeout_edit.text().strip()
            timeouts.append(int(text) if text else None)

        # 周几起：权威值持久化到 weekly_start.yml（经 ScriptService）。游戏侧原生 config
        # 起始日的同步不在此处进行——save_data 内 config.yml 的 script_path 尚未落盘，
        # 此时解析目录会拿到旧路径，导致写到错误/失效目录。统一由调用方在
        # ChainService.update_script 落盘新路径后触发（见 game_list.configCurrent）。
        start_day = None
        if self._weekly_start_supported:
            idx = self.weekly_start_combo.currentIndex()
            start_day = None if idx <= 0 else idx
            self._app_service.set_weekly_start(self.script_name, start_day)

        self.pending_changes = {
            "old_script_name": self.script_name,
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
            "weekly_start_day": start_day,
        }
        self.accept()
