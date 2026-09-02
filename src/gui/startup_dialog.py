"""GUI 打开时启动全部脚本的倒计时确认窗（StartupConfirmDialog）。

弹窗 UX 与 :mod:`src.gui.shutdown_dialog` 对齐：倒计时归零或点「立即启动」→ accept
（按上次配置启动全部脚本）；取消/关窗 → reject（无事发生）。倒计时由 ``QTimer`` 每秒
递减，归零即 accept。是否真启动由调用方据 ``exec()`` 结果决定。

仅 GUI 层使用：启动确认由 ``QmlBridge.maybe_auto_launch`` 在窗口打开后触发，弹窗经
**延迟 import** 引入，避免底层反向依赖上层（参见 ``shutdown_dialog`` 注释）。
"""

import logging
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QVBoxLayout

from src.gui.dialogs import (
    BG_CARD,
    FONT_SIZE_BODY,
    TEXT,
    FormDialogBase,
    make_font,
)

logger = logging.getLogger(__name__)


def confirm_startup(countdown: int) -> bool:
    """弹启动倒计时确认窗并等待用户选择（GUI 打开后的启动确认入口）。

    Args:
        countdown: 倒计时秒数。

    Returns:
        确认（归零/立即启动）返回 True；取消/关窗/弹窗失败返回 False。
    """
    try:
        if QApplication.instance() is None:
            QApplication(sys.argv)
        return StartupConfirmDialog(countdown).exec() == QDialog.DialogCode.Accepted
    except Exception as e:  # 无桌面等环境下 Qt 初始化会失败，属可预见
        logger.error("启动确认窗初始化失败 %s(%s)，按取消处理", type(e).__name__, e)
        return False


class StartupConfirmDialog(FormDialogBase):
    """GUI 打开时的启动倒计时确认窗。

    倒计时归零或点「立即启动」→ accept（按上次配置启动全部）；取消/关窗 → reject。
    复用 ``FormDialogBase`` 的样式与底部按钮行（取消 / 立即启动）；倒计时由 ``QTimer``
    每秒递减，归零即 accept。是否真启动由调用方据 ``exec()`` 结果决定。

    Args:
        countdown: 倒计时秒数，须大于 0。
        parent: 父窗口；启动窗由主窗口打开，通常无父窗口。
    """

    def __init__(self, countdown: int, parent=None):
        super().__init__(parent)
        # 调用方仅在 countdown>0 时弹窗，0/负数是编程错误。
        assert countdown > 0
        self._remain = countdown

        self.setWindowTitle("即将启动全部脚本")
        self.setWindowFlag(Qt.WindowStaysOnTopHint)
        self.setStyleSheet(f"background-color: {BG_CARD};")
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        self._label = QLabel(self)
        self._label.setFont(make_font(size=FONT_SIZE_BODY))
        self._label.setStyleSheet(f"color: {TEXT}; background: transparent;")
        layout.addWidget(self._label)

        layout.addLayout(self._make_footer("立即启动", self.accept))

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._show_remain()

    def _show_remain(self) -> None:
        """按剩余秒数刷新文案。"""
        self._label.setText(f"将在 {self._remain} 秒后按上次配置启动全部脚本")

    def _tick(self) -> None:
        """每秒递减一秒；归零停表并接受（启动全部）。"""
        self._remain -= 1
        self._show_remain()
        if self._remain <= 0:
            self._timer.stop()
            self.accept()

    def showEvent(self, event) -> None:
        """显示即起倒计时（``exec()`` 为模态，显示后才计时才不会提前流逝）。"""
        super().showEvent(event)
        self._timer.start()

    def hideEvent(self, event) -> None:
        """关闭即停表（accept/reject 都会走到），避免挂窗后定时器空转。"""
        self._timer.stop()
        super().hideEvent(event)
