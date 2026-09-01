"""自动关机：运行全部结束后由 service 作为 post_run 最后一项触发。

迁自 runner 的 ``script_chainer.utils.cmd_utils.shutdown_sys``：关机必须由主仓库
编排（在所有运行含重跑结束之后），不能再交给 runner 子进程的 ``--shutdown``，否则
首次运行结束即拉起关机倒计时，会抢在重跑前关掉机器。

确认窗是 PySide6 实现，已归位到 GUI 层（``src.gui.shutdown_dialog``）——放在本模块会
让底层反向依赖上层，并经由 ``gui.dialogs → service.app_service`` 回到 service 层成环
（详见该模块 docstring）。本模块只保留「确认后执行 shutdown 命令」的纯逻辑，弹窗经
**延迟 import** 引入。

仅 Windows 下真正关机；非 Windows（CI/Linux/macOS）仅记日志跳过关机。
"""

import logging
import subprocess
import sys

logger = logging.getLogger(__name__)

# CREATE_NO_WINDOW 仅在 Windows 平台存在；非 Windows 用 0 表示无特殊创建标志，
# 保证同一份代码在 Linux/macOS CI 上也能正常执行（不创建隐藏窗口）。
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


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
    """弹关机确认窗并等待用户选择（GUI 实现见 :mod:`src.gui.shutdown_dialog`）。

    延迟 import：GUI 层会经 ``gui.dialogs`` 反向依赖 service 层，模块级 import 成环；
    且只有真要弹窗时才需要 GUI（非 Windows 平台根本走不到）。

    Args:
        countdown: 倒计时秒数。

    Returns:
        确认返回 True；取消/关窗/弹窗失败返回 False。
    """
    from src.gui.shutdown_dialog import confirm_shutdown

    return confirm_shutdown(countdown)


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
