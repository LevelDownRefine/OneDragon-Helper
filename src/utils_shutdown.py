"""自动关机：运行全部结束后由 service 作为 post_run 最后一项触发。

迁自 runner 的 ``script_chainer.utils.cmd_utils.shutdown_sys``：关机必须由主仓库
编排（在所有运行含重跑结束之后），不能再交给 runner 子进程的 ``--shutdown``，否则
首次运行结束即拉起关机倒计时，会抢在重跑前关掉机器。

仅 Windows 下真正关机；非 Windows（CI/Linux/macOS）仅记日志跳过关机。
"""

import logging
import subprocess
import sys

# CREATE_NO_WINDOW 仅在 Windows 平台存在；非 Windows 用 0 表示无特殊创建标志，
# 保证同一份代码在 Linux/macOS CI 上也能正常执行（不创建隐藏窗口）。
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

logger = logging.getLogger(__name__)


def shutdown_sys(seconds: int) -> None:
    """关机：先弹倒计时确认窗，确认才关机；关窗/取消/超时则不关。

    Args:
        seconds: 倒计时秒数。
    """
    if sys.platform != "win32":
        logger.warning("非 Windows 平台不支持关机确认窗，跳过关机")
        return
    if _run_shutdown_confirm(seconds):
        logger.info("准备关机")
        subprocess.run(
            ["shutdown", "/s", "/f", "/t", "0"],
            creationflags=_CREATE_NO_WINDOW,
        )
    else:
        logger.info("已取消关机")


def _run_shutdown_confirm(countdown: int) -> bool:
    """在当前进程内弹出 PySide6 倒计时确认窗。

    本函数在子进程（CREATE_NEW_CONSOLE）中运行，须自行创建 QApplication。
    对话框模态阻塞，用户确认/取消/超时后返回。

    Args:
        countdown: 倒计时秒数。

    Returns:
        确认返回 True，取消/超时返回 False。
    """
    try:
        from PySide6.QtCore import QTimer  # noqa: F811
        from PySide6.QtWidgets import (  # noqa: F811
            QApplication,
            QDialog,
            QHBoxLayout,
            QLabel,
            QPushButton,
            QVBoxLayout,
        )
    except ImportError:
        logger.warning("PySide6 不可用，降级直接关机")
        return True

    class _ShutdownConfirmDialog(QDialog):
        """关机确认窗：倒计时归零自动确认，点「立即关机」立即确认，关窗/取消则取消。"""

        def __init__(self, countdown: int) -> None:
            super().__init__()
            self.confirmed = False
            self._remain = countdown
            self.setWindowTitle("即将关机")
            self.setWindowFlags(
                self.windowFlags() | 0x00000008  # WindowStaysOnTopHint
            )
            self.setFixedSize(380, 170)

            layout = QVBoxLayout(self)
            layout.setContentsMargins(18, 18, 18, 18)
            layout.setSpacing(14)

            self._label = QLabel(f"系统将在 {countdown} 秒后关机")
            self._label.setStyleSheet("font-size: 13px;")
            layout.addWidget(self._label, alignment=0x0004)  # AlignCenter

            btn_layout = QHBoxLayout()
            btn_layout.setSpacing(10)
            shutdown_btn = QPushButton("立即关机")
            shutdown_btn.setFixedWidth(120)
            shutdown_btn.clicked.connect(self._on_shutdown)
            btn_layout.addWidget(shutdown_btn)
            cancel_btn = QPushButton("取消")
            cancel_btn.setFixedWidth(120)
            cancel_btn.clicked.connect(self._on_cancel)
            btn_layout.addWidget(cancel_btn)
            layout.addLayout(btn_layout)

            self._timer = QTimer(self)
            self._timer.timeout.connect(self._tick)
            self._timer.start(1000)

        def _tick(self) -> None:
            self._remain -= 1
            if self._remain <= 0:
                self._timer.stop()
                self.confirmed = True
                self.accept()
                return
            self._label.setText(f"系统将在 {self._remain} 秒后关机")

        def _on_shutdown(self) -> None:
            self.confirmed = True
            self.accept()

        def _on_cancel(self) -> None:
            self.confirmed = False
            self.reject()

        def closeEvent(self, event) -> None:
            self.confirmed = False
            event.accept()

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    dialog = _ShutdownConfirmDialog(countdown)
    dialog.show()
    app.exec()
    return dialog.confirmed


def cancel_shutdown_sys() -> None:
    """取消计划的自动关机（shutdown /a）。"""
    subprocess.run(
        ["shutdown", "/a"],
        creationflags=_CREATE_NO_WINDOW,
    )
