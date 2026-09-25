"""每日计划表单：时间与开关统一编辑，保存由控制器处理。"""

from PySide6.QtCore import QTime, Signal
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QHBoxLayout,
    QLabel,
    QTimeEdit,
    QVBoxLayout,
)

from src.gui.dialogs import (
    TEXT,
    TEXT_MUTED,
    FormDialogBase,
    make_font,
    spin_box_qss,
)
from src.service.daily_plan import DailyPlanOptions, DailyTaskState


def _task_state_text(state: DailyTaskState) -> str:
    """把回读到的系统任务状态写成一行描述（与表单里正在编辑的内容无关）。"""
    if not state.exists:
        return "系统任务：未注册"
    status = "已启用" if state.enabled else "已禁用"
    if not state.target_time:
        return f"系统任务：{status}"
    return f"系统任务：{status}，每天 {state.target_time}"


class DailyPlanDialog(FormDialogBase):
    saveRequested = Signal()

    def __init__(
        self,
        plan: DailyPlanOptions,
        state: DailyTaskState,
        parent=None,
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
        hint = QLabel("每日计划对所有脚本生效。")
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
        self.state_label = QLabel(_task_state_text(state))
        self.state_label.setWordWrap(True)
        self.state_label.setFont(make_font(size=12))
        self.state_label.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        layout.addWidget(self.state_label)
        note = QLabel(
            "暂停后保留设置。\n关闭助手后仍有效；需电脑开机并登录，错过时间不补跑。"
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
        )

    def show_error(self, message: str) -> None:
        """保存失败时保留输入，允许继续修改或取消。"""
        self.error_label.setText(message)
        self.error_label.show()
