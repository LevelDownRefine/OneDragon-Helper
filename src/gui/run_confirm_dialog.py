"""「启动全部」前的运行确认弹窗（RunConfirmDialog）。

按生命周期三段组织（单列纵向，与原「运行前动作」一张 group 含多个 checkbox 行的
风格一致）：运行前配置（定时计划 / 关闭残留进程）·运行中配置（静音 / 重跑）·
运行后配置（邮件通知 / 自动关机）。样式与控件构造复用 ``src.gui.dialogs`` 的
基类与主题常量（单一来源，不在本文件重复定义）。

对外接口：
- ``RunConfirmDialog``：运行确认弹窗，构造签名含 enabled_count 与勾选初始值，
  ``result`` 返回 dict（shutdown_enabled / shutdown_delay / timed_enabled /
  timed_target / mute_enabled / close_running_enabled / rerun_enabled /
  notify_enabled）；取消（reject）不返回、不落盘。
"""

from PySide6.QtCore import QTime
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from src.gui.dialogs import (
    BG_CARD,
    BORDER_WIDTH,
    INPUT_FIXED_H,
    TEXT,
    FormDialogBase,
    make_font,
)
from src.utils_runner import _TIME_RE


class RunConfirmDialog(FormDialogBase):
    """「启动全部」前的确认弹窗，按生命周期三段（运行前/中/后配置）排列六项勾选。

    复用 ``FormDialogBase`` 的样式与控件构造；accept 后经 ``result`` 属性返回
    勾选项，写盘由调用方委托 ``ChainService.save_config``。取消（reject）不返回、不落盘。
    """

    def __init__(
        self,
        enabled_count: int,
        *,
        shutdown_enabled: bool,
        shutdown_delay: int,
        timed_enabled: bool,
        timed_target: str,
        mute_enabled: bool = False,
        close_running_enabled: bool = True,
        rerun_enabled: bool = True,
        notify_enabled: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("确认运行")
        self.setStyleSheet(f"background-color: {BG_CARD};")

        self.enabled_count = enabled_count
        self._result = None  # accept 后供调用方读取勾选项

        self.setMinimumWidth(400)
        self.init_ui(
            shutdown_enabled=shutdown_enabled,
            shutdown_delay=shutdown_delay,
            timed_enabled=timed_enabled,
            timed_target=timed_target,
            mute_enabled=mute_enabled,
            close_running_enabled=close_running_enabled,
            rerun_enabled=rerun_enabled,
            notify_enabled=notify_enabled,
        )

    def init_ui(
        self,
        *,
        shutdown_enabled: bool,
        shutdown_delay: int,
        timed_enabled: bool,
        timed_target: str,
        mute_enabled: bool,
        close_running_enabled: bool,
        rerun_enabled: bool,
        notify_enabled: bool,
    ) -> None:
        """构造布局：确认文案 + 三段生命周期配置（运行前/中/后）+ 底部按钮行。

        单列纵向：每段一张 QGroupBox，框内多行 checkbox（与原「运行前动作」单
        checkbox 行的视觉一致）；带额外控件的行（定时/关机）作为 row widget 嵌入。
        """
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        # 顶部确认文案
        hint = QLabel(f"即将运行 {self.enabled_count} 个脚本，是否继续？")
        hint.setFont(make_font(size=11, bold=True))
        hint.setStyleSheet(f"color: {TEXT}; background: transparent;")
        layout.addWidget(hint)

        layout.addWidget(
            self._make_running_pre_group(
                timed_enabled, timed_target, close_running_enabled
            )
        )
        layout.addWidget(self._make_running_group(mute_enabled, rerun_enabled))
        layout.addWidget(
            self._make_post_run_group(notify_enabled, shutdown_enabled, shutdown_delay)
        )

        layout.addStretch()
        layout.addLayout(
            self._make_footer("确认运行", self._on_accept, left_widgets=())
        )

    def _make_group(self, title: str) -> QGroupBox:
        """统一样式的分组框：钢蓝边框 + 圆角 + 偏左上方的标题。"""
        box = QGroupBox(title)
        box.setFont(make_font(size=11, bold=True))
        box.setStyleSheet(
            f"QGroupBox {{ color: {TEXT}; border: {BORDER_WIDTH} solid #C4D8F2; "
            f"border-radius: 8px; margin-top: 12px; }} "
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 6px; }}"
        )
        return box

    def _make_running_pre_group(
        self,
        timed_enabled: bool,
        timed_target: str,
        close_running_enabled: bool,
    ) -> QGroupBox:
        """运行前配置：定时计划（启用定时 + 目标时刻）· 关闭残留进程。"""
        box = self._make_group("运行前配置")
        col = QVBoxLayout(box)
        col.setContentsMargins(14, 20, 14, 14)
        col.setSpacing(10)

        col.addWidget(self._make_timed_row(timed_enabled, timed_target))

        self.close_running_cb = self._make_checkbox("运行前关闭残留进程")
        self.close_running_cb.setChecked(close_running_enabled)
        col.addWidget(self.close_running_cb)
        return box

    def _make_running_group(self, mute_enabled: bool, rerun_enabled: bool) -> QGroupBox:
        """运行中配置：静音 · 重跑失败脚本。"""
        box = self._make_group("运行中配置")
        col = QVBoxLayout(box)
        col.setContentsMargins(14, 20, 14, 14)
        col.setSpacing(10)

        self.mute_cb = self._make_checkbox("运行中静音（运行前静音，运行后恢复）")
        self.mute_cb.setChecked(mute_enabled)
        col.addWidget(self.mute_cb)

        self.rerun_cb = self._make_checkbox("运行后重跑失败脚本")
        self.rerun_cb.setChecked(rerun_enabled)
        col.addWidget(self.rerun_cb)
        return box

    def _make_post_run_group(
        self,
        notify_enabled: bool,
        shutdown_enabled: bool,
        shutdown_delay: int,
    ) -> QGroupBox:
        """运行后配置：邮件通知 · 自动关机（运行后关机 + 延迟秒数）。"""
        box = self._make_group("运行后配置")
        col = QVBoxLayout(box)
        col.setContentsMargins(14, 20, 14, 14)
        col.setSpacing(10)

        self.notify_cb = self._make_checkbox("运行后发送邮件通知")
        self.notify_cb.setChecked(notify_enabled)
        col.addWidget(self.notify_cb)

        col.addWidget(self._make_shutdown_row(shutdown_enabled, shutdown_delay))
        return box

    def _make_timed_row(self, enabled: bool, target: str) -> QWidget:
        """运行前配置第一行：启用定时复选框 + 目标时刻时间框（启用联动输入框禁用）。"""
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        self.timed_cb = self._make_checkbox("启用定时")
        self.timed_cb.setChecked(enabled)
        h.addWidget(self.timed_cb)

        target_label = QLabel("目标时刻")
        target_label.setFont(make_font(size=11))
        target_label.setFixedWidth(56)
        target_label.setStyleSheet(f"color: {TEXT}; background: transparent;")
        h.addWidget(target_label)

        self.timed_time = QTimeEdit(row)
        self.timed_time.setFont(make_font(size=11))
        self.timed_time.setDisplayFormat("HH:mm")
        self.timed_time.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.timed_time.setFixedWidth(90)
        self.timed_time.setFixedHeight(INPUT_FIXED_H)
        if target and _TIME_RE.match(target):
            hour, minute = (int(x) for x in target.split(":"))
            self.timed_time.setTime(QTime(hour, minute))
        else:
            self.timed_time.setTime(QTime(4, 10))
        self.timed_time.setEnabled(enabled)
        self.timed_cb.toggled.connect(self.timed_time.setEnabled)
        h.addWidget(self.timed_time)
        h.addStretch()
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
        self.shutdown_delay_spin.setEnabled(enabled)
        self.shutdown_cb.toggled.connect(self.shutdown_delay_spin.setEnabled)
        h.addWidget(self.shutdown_delay_spin)
        h.addStretch()
        return row

    @property
    def result(self) -> dict | None:
        """accept 后的勾选项；取消时返回 None。

        Returns:
            含 shutdown_enabled / shutdown_delay / timed_enabled / timed_target /
            mute_enabled / close_running_enabled / rerun_enabled / notify_enabled 的 dict。
        """
        return self._result

    def _on_accept(self) -> None:
        """确认运行：收集勾选项并 accept。"""
        t = self.timed_time.time()
        self._result = {
            "shutdown_enabled": self.shutdown_cb.isChecked(),
            "shutdown_delay": self.shutdown_delay_spin.value(),
            "timed_enabled": self.timed_cb.isChecked(),
            "timed_target": f"{t.hour():02d}:{t.minute():02d}",
            "mute_enabled": self.mute_cb.isChecked(),
            "close_running_enabled": self.close_running_cb.isChecked(),
            "rerun_enabled": self.rerun_cb.isChecked(),
            "notify_enabled": self.notify_cb.isChecked(),
        }
        self.accept()
