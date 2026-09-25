"""运行选项编辑器：静音/关机/重跑/邮件通知/关闭残留/开声音的统一控件。

RunConfirmDialog（手动运行确认）的组合控件。本控件只负责「展示 RunOptions +
收集 RunOptions」，不含标题/底部按钮（由宿主弹窗提供）。控件构造与样式复用
``src.gui.dialogs`` 的基类与主题常量（单一来源，不在本文件重复定义）。
"""

from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.gui.dialogs import (
    BORDER,
    BORDER_WIDTH,
    INPUT_FIXED_H,
    TEXT,
    check_box_qss,
    line_edit_qss,
    make_font,
    spin_box_qss,
)
from src.service.schedule import RunOptions

# SMTP 回显默认（schedule 缺省时的预填值；与 schedule.example.yml 默认一致）。
# 发送时的缺省主机/端口由 send_mail 自身兜底，此处仅影响弹窗展示。
SMTP_HOST_DEFAULT = "smtp.qq.com"
SMTP_PORT_DEFAULT = "465"


class RunOptionsEditor(QWidget):
    """运行选项编辑器：按生命周期三段（运行前/中/后）排列七项勾选 + 邮件配置。

    复用 ``src.gui.dialogs`` 的样式与控件构造；``run_options`` 属性回显勾选项，
    写盘由调用方经 ``AppService`` 委托 ``src.service.schedule.save_schedule``。
    """

    def __init__(self, options: RunOptions, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(
            self._make_running_pre_group(
                options.close_running_enabled, options.mute_enabled
            )
        )
        layout.addWidget(self._make_running_group(options.rerun_enabled))
        layout.addWidget(
            self._make_post_run_group(
                options.unmute_enabled,
                options.notify_enabled,
                options.shutdown_enabled,
                options.shutdown_delay,
                options.email,
                options.smtp_host or SMTP_HOST_DEFAULT,
                options.smtp_port or SMTP_PORT_DEFAULT,
            )
        )

    def _make_group(self, title: str) -> QGroupBox:
        """统一样式的分组框：钢蓝边框 + 圆角 + 偏左上方的标题。"""
        box = QGroupBox(title)
        box.setFont(make_font(size=11, bold=True))
        box.setStyleSheet(
            f"QGroupBox {{ color: {TEXT}; border: {BORDER_WIDTH} solid {BORDER}; "
            f"border-radius: 8px; margin-top: 12px; }} "
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 6px; }}"
        )
        return box

    def _make_checkbox(self, text: str) -> QCheckBox:
        """构造统一样式的复选框（字体/QSS 一次配齐）。"""
        cb = QCheckBox(text, self)
        cb.setFont(make_font(size=11))
        cb.setStyleSheet(check_box_qss())
        return cb

    def _make_running_pre_group(
        self, close_running_enabled: bool, mute_enabled: bool
    ) -> QGroupBox:
        """运行前配置：关闭残留进程 · 静音。"""
        box = self._make_group("运行前配置")
        col = QVBoxLayout(box)
        col.setContentsMargins(14, 20, 14, 14)
        col.setSpacing(10)

        self.close_running_cb = self._make_checkbox("运行前关闭残留进程")
        self.close_running_cb.setChecked(close_running_enabled)
        col.addWidget(self.close_running_cb)

        self.mute_cb = self._make_checkbox("运行前静音")
        self.mute_cb.setChecked(mute_enabled)
        col.addWidget(self.mute_cb)
        return box

    def _make_running_group(self, rerun_enabled: bool) -> QGroupBox:
        """运行中配置：重跑失败脚本。"""
        box = self._make_group("运行中配置")
        col = QVBoxLayout(box)
        col.setContentsMargins(14, 20, 14, 14)
        col.setSpacing(10)

        self.rerun_cb = self._make_checkbox("运行后重跑失败脚本")
        self.rerun_cb.setChecked(rerun_enabled)
        col.addWidget(self.rerun_cb)
        return box

    def _make_post_run_group(
        self,
        unmute_enabled: bool,
        notify_enabled: bool,
        shutdown_enabled: bool,
        shutdown_delay: int,
        email: str,
        smtp_host: str,
        smtp_port: str,
    ) -> QGroupBox:
        """运行后配置：邮件通知（含邮箱/授权码/SMTP 配置）· 开启声音 · 自动关机（运行后关机 + 延迟秒数）。"""
        box = self._make_group("运行后配置")
        col = QVBoxLayout(box)
        col.setContentsMargins(14, 20, 14, 14)
        col.setSpacing(10)

        self.notify_cb = self._make_checkbox("运行后发送邮件通知")
        self.notify_cb.setChecked(notify_enabled)
        col.addWidget(self.notify_cb)
        # 邮件配置：发件人邮箱（落 schedule.yml）+ 授权码（落系统凭据管理器，不落盘明文）
        # + SMTP 主机/端口（落 schedule.yml，默认 QQ）。仅在勾选通知时可用（与关机联动一致）。
        self.email_edit = self._make_line_edit(
            email, placeholder="发件人邮箱（如 123456@qq.com）"
        )
        self.auth_edit = self._make_line_edit(
            "", placeholder="QQ 授权码（16 位，仅首次需填）"
        )
        self.auth_edit.setEchoMode(QLineEdit.Password)
        col.addWidget(self._make_labeled_row("邮箱", self.email_edit))
        col.addWidget(self._make_labeled_row("授权码", self.auth_edit))

        self.smtp_host_edit = self._make_line_edit(
            smtp_host, placeholder="SMTP 主机（如 smtp.qq.com）"
        )
        self.smtp_port_edit = self._make_line_edit(
            smtp_port, placeholder="SMTP 端口（默认 465）"
        )
        col.addWidget(self._make_labeled_row("SMTP主机", self.smtp_host_edit))
        col.addWidget(self._make_labeled_row("SMTP端口", self.smtp_port_edit))

        for w in (
            self.email_edit,
            self.auth_edit,
            self.smtp_host_edit,
            self.smtp_port_edit,
        ):
            w.setEnabled(notify_enabled)
        self.notify_cb.toggled.connect(self._on_notify_toggled)

        self.unmute_cb = self._make_checkbox("运行后开启声音")
        self.unmute_cb.setChecked(unmute_enabled)
        col.addWidget(self.unmute_cb)

        col.addWidget(self._make_shutdown_row(shutdown_enabled, shutdown_delay))
        return box

    def _on_notify_toggled(self, on: bool) -> None:
        """邮件通知开关联动邮箱/授权码/SMTP 输入的可编辑状态。"""
        self.email_edit.setEnabled(on)
        self.auth_edit.setEnabled(on)
        self.smtp_host_edit.setEnabled(on)
        self.smtp_port_edit.setEnabled(on)

    def _make_line_edit(self, text: str, *, placeholder: str = "") -> QLineEdit:
        """统一样式的单行输入框：深底白字 + 占位文案，随标签行拉伸（邮件/授权码/SMTP 输入）。"""
        edit = QLineEdit(text)
        edit.setFont(make_font(size=11))
        edit.setFixedHeight(INPUT_FIXED_H)
        edit.setPlaceholderText(placeholder)
        edit.setStyleSheet(line_edit_qss())
        return edit

    def _make_labeled_row(self, label_text: str, widget: QWidget) -> QWidget:
        """带标签的输入行（标签固定宽 + 输入框拉伸），与关机行视觉一致。"""
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        label = QLabel(label_text)
        label.setFont(make_font(size=11))
        label.setFixedWidth(56)
        label.setStyleSheet(f"color: {TEXT}; background: transparent;")
        h.addWidget(label)
        h.addWidget(widget)
        return row

    def _make_shutdown_row(self, enabled: bool, delay: int) -> QWidget:
        """运行后配置末行：运行后关机复选框 + 延迟秒数数字框（启用联动数字框禁用）。"""
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        self.shutdown_cb = self._make_checkbox("运行后关机")
        self.shutdown_cb.setChecked(enabled)
        h.addWidget(self.shutdown_cb)

        delay_label = QLabel("延迟秒数")
        delay_label.setFont(make_font(size=11))
        delay_label.setFixedWidth(56)
        delay_label.setStyleSheet(f"color: {TEXT}; background: transparent;")
        h.addWidget(delay_label)

        self.shutdown_delay_spin = QSpinBox(row)
        self.shutdown_delay_spin.setFont(make_font(size=11))
        self.shutdown_delay_spin.setRange(0, 86400)
        self.shutdown_delay_spin.setValue(delay if delay and delay > 0 else 0)
        self.shutdown_delay_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.shutdown_delay_spin.setFixedWidth(90)
        self.shutdown_delay_spin.setFixedHeight(INPUT_FIXED_H)
        self.shutdown_delay_spin.setStyleSheet(spin_box_qss())
        self.shutdown_delay_spin.setEnabled(enabled)
        self.shutdown_cb.toggled.connect(self.shutdown_delay_spin.setEnabled)
        h.addWidget(self.shutdown_delay_spin)
        h.addStretch()
        return row

    @property
    def run_options(self) -> RunOptions:
        """当前勾选项（RunOptions）。

        邮件未启用时邮箱/授权码/SMTP 输入被禁用，smtp_host/smtp_port 不收集
        （避免把占位默认值写进关闭的通知块）。
        """
        notify = self.notify_cb.isChecked()
        return RunOptions(
            shutdown_enabled=self.shutdown_cb.isChecked(),
            shutdown_delay=self.shutdown_delay_spin.value(),
            mute_enabled=self.mute_cb.isChecked(),
            unmute_enabled=self.unmute_cb.isChecked(),
            close_running_enabled=self.close_running_cb.isChecked(),
            rerun_enabled=self.rerun_cb.isChecked(),
            notify_enabled=notify,
            email=self.email_edit.text().strip() if notify else "",
            auth_code=self.auth_edit.text().strip() if notify else "",
            smtp_host=self.smtp_host_edit.text().strip() if notify else "",
            smtp_port=self.smtp_port_edit.text().strip() if notify else "",
        )
