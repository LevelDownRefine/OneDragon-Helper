"""每日计划表单：时间、脚本与开关统一编辑，保存由控制器处理。"""

from PySide6.QtCore import Qt, QTime, Signal
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QScrollArea,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from gui.dialogs import (
    BG_CARD,
    BG_HOVER,
    BG_INPUT,
    BLUE,
    BORDER,
    DARK_BLUE,
    TEXT,
    TEXT_MUTED,
    FormDialogBase,
    make_font,
    spin_box_qss,
)
from gui.run_options_editor import RunOptionsEditor
from src.service.daily_plan import DailyPlanOptions, DailyTaskState

_SCROLLBAR_STYLE = f"""
    QScrollBar:vertical {{ background: {BG_CARD}; width: 8px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {BORDER}; min-height: 24px; border-radius: 4px; }}
    QScrollBar::handle:vertical:hover {{ background: {TEXT_MUTED}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
"""


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
        name=None,
        scripts=None,
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
        hint = QLabel("选择本计划运行的脚本，脚本设置与其他计划共用。")
        hint.setWordWrap(True)
        hint.setFont(make_font(size=12))
        hint.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        layout.addWidget(hint)
        self.name_edit = None
        if name is not None:
            self.name_edit = QLineEdit(name, self)
            self.name_edit.setPlaceholderText("计划名称")
            self.name_edit.setAccessibleName("计划名称")
            self.name_edit.setStyleSheet(self._LINE_EDIT_STYLE)
            layout.addWidget(self.name_edit)
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
        self.all_scripts_cb = self._make_checkbox("运行全部脚本（含以后新增的脚本）")
        self.all_scripts_cb.setChecked(plan.selected_scripts is None)
        layout.addWidget(self.all_scripts_cb)
        self.script_checks = {}
        selected = plan.selected_scripts
        available = list(scripts or [])
        known = {item["id"] for item in available}
        if selected is not None:
            available.extend(
                {"id": ident, "display_name": f"未找到：{ident}"}
                for ident in selected
                if ident not in known
            )
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(105)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: {BG_INPUT}; border: 1px solid {BORDER}; border-radius: 8px; }}"
            + _SCROLLBAR_STYLE
        )
        contents = QWidget()
        contents.setStyleSheet("background: transparent;")
        checks_layout = QVBoxLayout(contents)
        checks_layout.setContentsMargins(10, 6, 10, 6)
        for script in available:
            ident = script["id"]
            checkbox = self._make_checkbox(script["display_name"])
            checkbox.setChecked(selected is None or ident in selected)
            checkbox.setEnabled(selected is not None)
            self.script_checks[ident] = checkbox
            checks_layout.addWidget(checkbox)
        checks_layout.addStretch()
        scroll.setWidget(contents)
        layout.addWidget(scroll)
        self.all_scripts_cb.toggled.connect(self._set_all_scripts)
        note = QLabel(
            "运行选项仅对每日计划生效。暂停后保留设置。\n"
            "关闭助手后仍有效；需电脑开机并登录，错过时间不补跑。"
        )
        note.setWordWrap(True)
        note.setFont(make_font(size=11))
        note.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        layout.addWidget(note)
        self.editor = RunOptionsEditor(plan.run_options)
        layout.addWidget(self.editor)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #F5A7A7; background: transparent;")
        self.error_label.hide()
        layout.addWidget(self.error_label)
        # 小屏幕下运行选项较多，正文滚动，保存按钮始终可见。
        body = QWidget(self)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(16)
        while layout.count():
            item = layout.takeAt(0)
            if item.widget() is not None:
                body_layout.addWidget(item.widget())
            elif item.layout() is not None:
                body_layout.addLayout(item.layout())
            else:
                body_layout.addItem(item)
        body_scroll = QScrollArea(self)
        body_scroll.setWidgetResizable(True)
        body_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }" + _SCROLLBAR_STYLE
        )
        body.setStyleSheet("background: transparent;")
        body_scroll.setWidget(body)
        screen = QApplication.primaryScreen()
        if screen is not None:
            available_height = max(300, screen.availableGeometry().height() - 150)
            body_scroll.setFixedHeight(
                min(body.sizeHint().height() + 2, available_height)
            )
        layout.addWidget(body_scroll)
        layout.addLayout(self._make_footer("保存", self.saveRequested.emit))

    @property
    def daily_plan(self) -> DailyPlanOptions:
        self.time_edit.interpretText()
        return DailyPlanOptions(
            self.enabled_cb.isChecked(),
            self.time_edit.time().toString("HH:mm"),
            self.editor.run_options,
            None
            if self.all_scripts_cb.isChecked()
            else [
                *(
                    ident
                    for ident, box in self.script_checks.items()
                    if box.isChecked()
                ),
            ],
        )

    def show_error(self, message: str) -> None:
        """保存失败时保留输入，允许继续修改或取消。"""
        self.error_label.setText(message)
        self.error_label.show()

    def _set_all_scripts(self, checked):
        for box in self.script_checks.values():
            box.setEnabled(not checked)


class DailyPlanListDialog(FormDialogBase):
    """展示计划，操作由控制器执行。"""

    addRequested = Signal()
    editRequested = Signal(str)
    copyRequested = Signal(str)
    deleteRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("计划任务")
        self.setFixedWidth(520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(16)
        title = QLabel("计划任务")
        title.setFont(make_font(size=20, bold=True))
        title.setStyleSheet(f"color: {TEXT}; background: transparent;")
        layout.addWidget(title)
        self.list_widget = QListWidget(self)
        self.list_widget.setAccessibleName("计划列表")
        self.list_widget.setFont(make_font(size=12))
        self.list_widget.setMinimumHeight(180)
        self.list_widget.setStyleSheet(
            f"""
            QListWidget {{
                background: {BG_INPUT}; color: {TEXT};
                border: 1px solid {BORDER}; border-radius: 8px;
                padding: 5px; outline: none;
            }}
            QListWidget::item {{ padding: 10px 12px; border-radius: 6px; }}
            QListWidget::item:hover {{ background: {BG_HOVER}; }}
            QListWidget::item:selected {{ background: {DARK_BLUE}; color: {TEXT}; }}
            QListWidget:focus {{ border-color: {BLUE}; }}
            """
        )
        layout.addWidget(self.list_widget)
        self.error_label = QLabel(self)
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #F5A7A7; background: transparent;")
        self.error_label.hide()
        layout.addWidget(self.error_label)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        for text, callback in (
            ("新增", self.addRequested.emit),
            ("编辑", lambda: self._selected(self.editRequested)),
            ("复制", lambda: self._selected(self.copyRequested)),
            ("删除", lambda: self._selected(self.deleteRequested)),
            ("关闭", self.accept),
        ):
            button = QPushButton(text, self)
            button.setFixedHeight(28)
            button.setFont(make_font(size=11, bold=text == "新增"))
            button.setCursor(Qt.PointingHandCursor)
            button.setAutoDefault(False)
            button.setStyleSheet(
                self._PRIMARY_BTN_STYLE if text == "新增" else self._SECONDARY_BTN_STYLE
            )
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self._ids = []

    def set_plans(self, plans):
        self._ids = []
        self.list_widget.clear()
        for item in plans:
            plan = item["plan"]
            status = "启用" if plan["enabled"] else "停用"
            state = item["state"]
            if item["state_error"]:
                task_status = "读取失败"
            elif not plan["enabled"] and state is not None and state["exists"]:
                task_status = "系统任务不一致"
            elif state is None or not state["exists"]:
                task_status = "未注册"
            elif not state["enabled"]:
                task_status = "系统任务已禁用"
            elif (
                not state["entry_matches"]
                or state["target_time"] != plan["target_time"]
            ):
                task_status = "系统任务不一致"
            else:
                task_status = "系统任务正常"
            self._ids.append(item["id"])
            self.list_widget.addItem(
                f"{item['name']}    每天 {plan['target_time']}    {status}    {task_status}"
            )
        if self._ids:
            self.list_widget.setCurrentRow(0)

    def _selected(self, signal):
        row = self.list_widget.currentRow()
        if 0 <= row < len(self._ids):
            signal.emit(self._ids[row])

    def show_error(self, message):
        self.error_label.setText(message)
        self.error_label.setVisible(bool(message))
