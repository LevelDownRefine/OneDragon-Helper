"""自动关机：运行全部结束后由 service 作为 post_run 最后一项触发。

迁自 runner 的 ``script_chainer.utils.cmd_utils.shutdown_sys``：关机必须由主仓库
编排（在所有运行含重跑结束之后），不能再交给 runner 子进程的 ``--shutdown``，否则
首次运行结束即拉起关机倒计时，会抢在重跑前关掉机器。

确认窗改进程内 PySide6 弹窗（取代原 ``win_exe/shutdown_confirm.py`` 的 tkinter
子进程）：调用方只有 CLI 进程与 ``spawn_schedule_run`` 起的独立控制台进程，二者都
运行在主线程且本无 QApplication，进程内弹窗安全；同时去掉子进程退出码约定与
tkinter 依赖。样式复用 ``src.gui.dialogs`` 的主题常量与弹窗基类（单一来源）。

仅 Windows 下真正关机；非 Windows（CI/Linux/macOS）仅记日志跳过关机。
"""

import logging
import subprocess
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
    _FormDialogBase,
    make_font,
)

# CREATE_NO_WINDOW 仅在 Windows 平台存在；非 Windows 用 0 表示无特殊创建标志，
# 保证同一份代码在 Linux/macOS CI 上也能正常执行（不创建隐藏窗口）。
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

logger = logging.getLogger(__name__)


def shutdown_sys(seconds: int) -> None:
    """关机：先弹倒计时确认窗，确认才关机；关窗/取消则不关。

    Args:
        seconds: 倒计时秒数（>0，调用方已保证）。
    """
    if sys.platform != "win32":
        logger.warning("非 Windows 平台不支持关机，跳过关机")
        return
    if _confirm_shutdown(seconds):
        logger.info("准备关机")
        _run_shutdown_command(["/s", "/f", "/t", "0"])
    else:
        logger.info("已取消关机")


def _confirm_shutdown(countdown: int) -> bool:
    """进程内弹倒计时确认窗并等待用户选择。

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


def _run_shutdown_command(args: list[str]) -> None:
    """执行 Windows 的 ``shutdown`` 命令，非 0 退出码记日志。

    Args:
        args: 传给 ``shutdown`` 的参数列表，不含命令名。
    """
    proc = subprocess.run(
        ["shutdown", *args],
        creationflags=_CREATE_NO_WINDOW,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        logger.error(
            "shutdown %s 失败（退出码=%d）：%s",
            " ".join(args),
            proc.returncode,
            (proc.stderr or "").strip(),
        )


class ShutdownConfirmDialog(_FormDialogBase):
    """关机倒计时确认窗：倒计时归零或点「立即关机」→ accept；取消/关窗 → reject。

    复用 ``_FormDialogBase`` 的样式与底部按钮行（取消 / 立即关机）；倒计时由
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
