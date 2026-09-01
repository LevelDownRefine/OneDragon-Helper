"""关机倒计时确认窗（GUI 层）。

确认窗是 PySide6 实现，样式复用 ``src.gui.dialogs`` 的主题常量与弹窗基类（单一来源）。
``utils_shutdown`` 只保留「确认后执行 shutdown 命令」的纯逻辑，弹窗经**延迟 import**
引入本模块，避免底层反向依赖上层（否则 ``schedule → utils_shutdown →
gui.dialogs → app_service → chain_service → schedule`` 成环）。
"""

import logging
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QVBoxLayout,
)

from src.gui.dialogs import (
    BG_CARD,
    FONT_SIZE_BODY,
    TEXT,
    FormDialogBase,
    make_font,
)

logger = logging.getLogger(__name__)


def confirm_shutdown(countdown: int) -> bool:
    """弹倒计时确认窗并等待用户选择（关机流程的 GUI 侧入口）。

    Args:
        countdown: 倒计时秒数。

    Returns:
        确认返回 True；取消/关窗/弹窗失败返回 False。
    """
    try:
        if QApplication.instance() is None:
            QApplication(sys.argv)
        return ShutdownConfirmDialog(countdown).exec() == QDialog.DialogCode.Accepted
    except Exception as e:  # 无桌面等环境下 Qt 初始化会失败，属可预见
        logger.error("关机确认窗初始化失败 %s(%s)，按取消处理", type(e).__name__, e)
        return False


class ShutdownConfirmDialog(FormDialogBase):
    """关机倒计时确认窗：倒计时归零或点「立即关机」→ accept；取消/关窗 → reject。

    复用 ``FormDialogBase`` 的样式与底部按钮行（取消 / 立即关机）；倒计时由
    ``QTimer`` 每秒递减，归零即 accept。是否真关机由调用方据 ``exec()`` 结果决定。

    Args:
        countdown: 倒计时秒数，须大于 0。
        parent: 父窗口；关机窗由独立控制台进程弹出，通常无父窗口。
    """

    def __init__(self, countdown: int, parent=None):
        super().__init__(parent)
        # 调用方（build_post_run_pipeline）仅在 delay>0 时挂关机步骤，0/负数是编程错误。
        assert countdown > 0
        self._remain = countdown

        self.setWindowTitle("即将关机")
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

        layout.addLayout(self._make_footer("立即关机", self.accept))

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._show_remain()

    def _show_remain(self) -> None:
        """按剩余秒数刷新文案。"""
        self._label.setText(f"系统将在 {self._remain} 秒后关机")

    def _tick(self) -> None:
        """每秒递减一秒；归零停表并接受（关机）。"""
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
