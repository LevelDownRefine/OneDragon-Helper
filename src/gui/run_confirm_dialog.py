"""「启动全部」前的运行确认弹窗（RunConfirmDialog）。

单一职责：仅承载「启动全部」运行前的确认交互（自动关机 / 定时计划 / 运行中静音
三项勾选），accept 后经 ``result`` 属性返回勾选项，写盘由调用方委托
``ChainService.save_config``。样式与控件构造复用 ``src.gui.dialogs`` 的基类与
主题常量（单一来源，不在本文件重复定义）。

对外接口：
- ``RunConfirmDialog``：运行确认弹窗，构造签名含 enabled_count 与三项勾选的初始值，
  ``result`` 返回 dict（shutdown_enabled / shutdown_delay / timed_enabled /
  timed_target / mute_enabled）；取消（reject）不返回、不落盘。
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
)

from src.gui.dialogs import (
    BG_CARD,
    BORDER_WIDTH,
    INPUT_FIXED_H,
    TEXT,
    _FormDialogBase,
    make_font,
)
from src.utils_runner import _TIME_RE


class RunConfirmDialog(_FormDialogBase):
    """「启动全部」前的确认弹窗，内嵌自动关机与定时计划配置。

    复用 ``_FormDialogBase`` 的样式与控件构造；accept 后经 ``result`` 属性返回
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
        )

    def init_ui(
        self,
        *,
        shutdown_enabled: bool,
        shutdown_delay: int,
        timed_enabled: bool,
        timed_target: str,
        mute_enabled: bool,
    ) -> None:
        """构造布局：确认文案 + 自动关机区 + 定时计划区 + 运行中静音区 + 底部按钮行。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        # 顶部确认文案
        hint = QLabel(f"即将运行 {self.enabled_count} 个脚本，是否继续？")
        hint.setFont(make_font(size=11, bold=True))
        hint.setStyleSheet(f"color: {TEXT}; background: transparent;")
        layout.addWidget(hint)

        layout.addWidget(self._make_shutdown_group(shutdown_enabled, shutdown_delay))
        layout.addWidget(self._make_timed_group(timed_enabled, timed_target))
        layout.addWidget(self._make_mute_group(mute_enabled))

        layout.addStretch()
        layout.addLayout(
            self._make_footer("确认运行", self._on_accept, left_widgets=())
        )

    def _make_shutdown_group(self, enabled: bool, delay: int) -> QGroupBox:
        """自动关机分组：复选框 + 延迟秒数数字框（延时框禁用随复选框联动）。"""
        box = QGroupBox("自动关机")
        box.setFont(make_font(size=11, bold=True))
        box.setStyleSheet(
            f"QGroupBox {{ color: {TEXT}; border: {BORDER_WIDTH} solid #C4D8F2; "
            f"border-radius: 8px; margin-top: 12px; }} "
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 6px; }}"
        )
        row = QHBoxLayout(box)
        row.setContentsMargins(14, 20, 14, 14)
        row.setSpacing(12)

        self.shutdown_cb = self._make_checkbox("运行后关机")
        self.shutdown_cb.setChecked(enabled)
        row.addWidget(self.shutdown_cb)

        delay_label = QLabel("延迟秒数")
        delay_label.setFont(make_font(size=11))
        delay_label.setFixedWidth(56)
        delay_label.setStyleSheet(f"color: {TEXT}; background: transparent;")
        row.addWidget(delay_label)

        self.shutdown_delay_spin = QSpinBox(self)
        self.shutdown_delay_spin.setFont(make_font(size=11))
        self.shutdown_delay_spin.setRange(0, 86400)
        self.shutdown_delay_spin.setValue(delay if delay and delay > 0 else 0)
        self.shutdown_delay_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.shutdown_delay_spin.setFixedWidth(90)
        self.shutdown_delay_spin.setFixedHeight(INPUT_FIXED_H)
        self.shutdown_delay_spin.setEnabled(enabled)
        self.shutdown_cb.toggled.connect(self.shutdown_delay_spin.setEnabled)
        row.addWidget(self.shutdown_delay_spin)

        row.addStretch()
        return box

    def _make_timed_group(self, enabled: bool, target: str) -> QGroupBox:
        """定时计划分组：复选框 + 目标时刻时间框（时间框禁用随复选框联动）。"""
        box = QGroupBox("定时计划")
        box.setFont(make_font(size=11, bold=True))
        box.setStyleSheet(
            f"QGroupBox {{ color: {TEXT}; border: {BORDER_WIDTH} solid #C4D8F2; "
            f"border-radius: 8px; margin-top: 12px; }} "
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 6px; }}"
        )
        row = QHBoxLayout(box)
        row.setContentsMargins(14, 20, 14, 14)
        row.setSpacing(12)

        self.timed_cb = self._make_checkbox("启用定时")
        self.timed_cb.setChecked(enabled)
        row.addWidget(self.timed_cb)

        target_label = QLabel("目标时刻")
        target_label.setFont(make_font(size=11))
        target_label.setFixedWidth(56)
        target_label.setStyleSheet(f"color: {TEXT}; background: transparent;")
        row.addWidget(target_label)

        self.timed_time = QTimeEdit(self)
        self.timed_time.setFont(make_font(size=11))
        self.timed_time.setDisplayFormat("HH:mm")
        self.timed_time.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.timed_time.setFixedWidth(90)
        self.timed_time.setFixedHeight(INPUT_FIXED_H)
        if target and _TIME_RE.match(target):
            h, m = (int(x) for x in target.split(":"))
            self.timed_time.setTime(QTime(h, m))
        else:
            self.timed_time.setTime(QTime(4, 10))
        self.timed_time.setEnabled(enabled)
        self.timed_cb.toggled.connect(self.timed_time.setEnabled)
        row.addWidget(self.timed_time)

        row.addStretch()
        return box

    def _make_mute_group(self, enabled: bool) -> QGroupBox:
        """运行中静音分组：单个复选框（运行前静音、运行后恢复，由 runner 执行）。"""
        box = QGroupBox("运行中静音")
        box.setFont(make_font(size=11, bold=True))
        box.setStyleSheet(
            f"QGroupBox {{ color: {TEXT}; border: {BORDER_WIDTH} solid #C4D8F2; "
            f"border-radius: 8px; margin-top: 12px; }} "
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 6px; }}"
        )
        row = QHBoxLayout(box)
        row.setContentsMargins(14, 20, 14, 14)
        row.setSpacing(12)

        self.mute_cb = self._make_checkbox("运行中静音（运行前静音，运行后恢复）")
        self.mute_cb.setChecked(enabled)
        row.addWidget(self.mute_cb)

        row.addStretch()
        return box

    @property
    def result(self) -> dict | None:
        """accept 后的勾选项；取消时返回 None。

        Returns:
            含 shutdown_enabled / shutdown_delay / timed_enabled / timed_target /
            mute_enabled 的 dict。
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
        }
        self.accept()
