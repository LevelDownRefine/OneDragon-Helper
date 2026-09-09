"""关机倒计时确认窗（GUI 层）。

确认窗是 PySide6 实现，样式复用 ``src.gui.dialogs`` 的主题常量（单一来源；
倒计时生命周期共用 ``CountdownConfirmDialogBase``）。``utils_shutdown`` 只保留
「确认后执行 shutdown 命令」的纯逻辑，弹窗经**延迟 import**引入本模块，
避免底层反向依赖上层（否则 ``schedule → utils_shutdown → gui.dialogs →
app_service → chain_service → schedule`` 成环）。
"""

import logging
import sys

from PySide6.QtWidgets import QApplication, QDialog

from src.gui.dialogs import CountdownConfirmDialogBase

logger = logging.getLogger(__name__)


class ShutdownConfirmDialog(CountdownConfirmDialogBase):
    """关机倒计时确认窗：倒计时归零或点「立即关机」→ accept；取消/关窗 → reject。

    倒计时生命周期（显示即起、归零即 accept、关窗即停表）继承自基类；
    是否真关机由调用方据 ``exec()`` 结果决定。
    """

    _TITLE = "即将关机"
    _ACTION_TEXT = "立即关机"
    _HINT_TEMPLATE = "系统将在 {remain} 秒后关机"


def confirm_shutdown(countdown: int) -> bool:
    """弹关机倒计时确认窗并等待用户选择（关机流程的 GUI 侧入口）。

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
