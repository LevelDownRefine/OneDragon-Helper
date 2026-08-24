"""自动关机：运行全部结束后由 service 作为 post_run 最后一项触发。

迁自 runner 的 ``script_chainer.utils.cmd_utils.shutdown_sys``：关机必须由主仓库
编排（在所有运行含重跑结束之后），不能再交给 runner 子进程的 ``--shutdown``，否则
首次运行结束即拉起关机倒计时，会抢在重跑前关掉机器。

仅 Windows 下真正关机；非 Windows（CI/Linux/macOS）仅记日志跳过关机。
"""

import logging
import os
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
        os.system("shutdown /s /f /t 0")
    else:
        logger.info("已取消关机")


def _run_shutdown_confirm(countdown: int) -> bool:
    """拉起独立确认窗子进程，确认返回 True、取消/超时返回 False。

    Args:
        countdown: 倒计时秒数。

    Returns:
        确认返回 True，取消/超时返回 False。
    """
    confirm_script = os.path.join(
        os.path.dirname(__file__), "win_exe", "shutdown_confirm.py"
    )
    if not os.path.isfile(confirm_script):
        logger.error("关机确认窗脚本缺失 %s，降级直接关机", confirm_script)
        return True
    try:
        proc = subprocess.run(
            [sys.executable, confirm_script, str(countdown)],
            creationflags=_CREATE_NO_WINDOW,
            capture_output=True,
            text=True,
            timeout=countdown + 30,
        )
        out = (proc.stdout or "").strip()
        if out:
            for line in out.splitlines():
                logger.info("[关机确认窗] %s", line)
        logger.info("关机确认窗退出码=%d", proc.returncode)
        return proc.returncode == 0
    except subprocess.TimeoutExpired as e:
        proc = getattr(e, "subprocess", None)
        if proc is not None:
            proc.kill()
        logger.error("关机确认窗超时未响应，视为取消")
        return False
    except OSError as e:
        logger.error("启动关机确认窗失败 %s，降级直接关机", e)
        return True


def cancel_shutdown_sys() -> None:
    """取消计划的自动关机（shutdown /a）。"""
    os.system("shutdown /a")
