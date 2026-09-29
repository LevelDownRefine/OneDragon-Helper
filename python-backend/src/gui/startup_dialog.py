"""GUI 打开时启动全部脚本的倒计时确认窗（StartupConfirmDialog）。

弹窗 UX 与 :mod:`src.gui.shutdown_dialog` 对齐：倒计时归零或点「立即启动」→ accept
（按上次配置启动全部脚本）；取消/关窗 → reject（无事发生）。倒计时生命周期共用
``CountdownConfirmDialogBase``（见 ``shutdown_dialog`` 注释）。

仅 GUI 层使用：启动确认由 ``QmlBridge.maybe_auto_launch`` 在窗口打开后触发，弹窗经
**延迟 import** 引入，避免底层反向依赖上层（参见 ``shutdown_dialog`` 注释）。
"""

import logging
import sys

from PySide6.QtWidgets import QApplication, QDialog

from src.gui.dialogs import CountdownConfirmDialogBase

logger = logging.getLogger(__name__)


class StartupConfirmDialog(CountdownConfirmDialogBase):
    """GUI 打开时的启动倒计时确认窗。

    倒计时归零或点「立即启动」→ accept（按上次配置启动全部）；取消/关窗 → reject。
    是否真启动由调用方据 ``exec()`` 结果决定。
    """

    _TITLE = "即将启动全部脚本"
    _ACTION_TEXT = "立即启动"
    _HINT_TEMPLATE = "将在 {remain} 秒后按上次配置启动全部脚本"


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
