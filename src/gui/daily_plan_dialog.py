"""每日计划表单：时间、脚本与开关统一编辑，保存由控制器处理。"""

from PySide6.QtCore import Qt, QTime, Signal
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from src.gui.dialogs import (
    BORDER,
    TEXT,
    TEXT_MUTED,
    FormDialogBase,
    make_font,
    spin_box_qss,
)
from src.service.daily_plan import DailyPlanOptions


class DailyPlanDialog(FormDialogBase):
    saveRequested = Signal()

    def __init__(
        self, plan: DailyPlanOptions, scripts: list[tuple[str, str]], parent=None
    ):
        super().__init__(parent)
        self.setWindowTitle("每日计划")
        self.setFixedWidth(460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(16)
        title = QLabel("每日计划")
        title.setFont(make_font(size=20, bold=True))
        title.setStyleSheet(f"color: {TEXT}; background: transparent;")
        layout.addWidget(title)
        hint = QLabel("选择每天运行的脚本。手动运行时的勾选不会改变此计划。")
        hint.setWordWrap(True)
        hint.setFont(make_font(size=12))
        hint.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        layout.addWidget(hint)
        row = QHBoxLayout()
        self.enabled_cb = self._make_checkbox("启用每日计划")
        self.enabled_cb.setChecked(plan.enabled)
        row.addWidget(self.enabled_cb)
        row.addStretch()
        daily_label = self._make_label("每天")
        daily_label.setFixedWidth(32)
        row.addWidget(daily_label)
        self.time_edit = QTimeEdit(QTime.fromString(plan.target_time, "HH:mm"), self)
        self.time_edit.setDisplayFormat("HH:mm")
        self.time_edit.setAccessibleName("每日运行时间")
        self.time_edit.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.time_edit.setFixedSize(84, 32)
        self.time_edit.setFont(make_font(size=13))
        self.time_edit.setStyleSheet(spin_box_qss())
        row.addWidget(self.time_edit)
        layout.addLayout(row)
        label = self._make_label("参加计划的脚本")
        label.setFixedWidth(250)
        layout.addWidget(label)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: transparent; border: 1px solid {BORDER}; "
            "border-radius: 8px; }"
        )
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        checks_layout = QVBoxLayout(content)
        checks_layout.setContentsMargins(12, 10, 12, 10)
        checks_layout.setSpacing(10)
        choices = list(scripts)
        available = {name for name, _label in scripts}
        choices.extend(
            (name, f"{name}（已移除，请取消勾选）")
            for name in plan.script_names
            if name not in available
        )
        self.script_checks = {}
        for name, display_name in choices:
            check = self._make_checkbox(display_name)
            check.setToolTip(display_name)
            check.setChecked(name in plan.script_names)
            self.script_checks[name] = check
            checks_layout.addWidget(check)
        if not choices:
            empty = QLabel("还没有脚本，请先在主界面添加。")
            empty.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
            checks_layout.addWidget(empty)
        checks_layout.addStretch()
        scroll.setWidget(content)
        scroll.setFixedHeight(min(220, max(76, len(choices) * 34 + 20)))
        layout.addWidget(scroll)
        note = QLabel(
            "副本和运行选项使用最新配置。暂停会保留时间与脚本。\n"
            "关闭助手后仍有效；需电脑开机并登录，错过时间不补跑。"
        )
        note.setWordWrap(True)
        note.setFont(make_font(size=11))
        note.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        layout.addWidget(note)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #F5A7A7; background: transparent;")
        self.error_label.hide()
        layout.addWidget(self.error_label)
        layout.addLayout(self._make_footer("保存", self.saveRequested.emit))

    @property
    def daily_plan(self) -> DailyPlanOptions:
        self.time_edit.interpretText()
        return DailyPlanOptions(
            self.enabled_cb.isChecked(),
            self.time_edit.time().toString("HH:mm"),
            tuple(
                name for name, check in self.script_checks.items() if check.isChecked()
            ),
        )

    def show_error(self, message: str) -> None:
        """保存失败时保留输入，允许继续修改或取消。"""
        self.error_label.setText(message)
        self.error_label.show()
