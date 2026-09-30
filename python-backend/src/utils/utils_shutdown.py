"""自动关机：运行全部结束后由 service 作为 post_run 最后一项触发。

关机必须由主仓库编排（在所有运行含重跑结束之后），不能再交给 runner 子进程的
``--shutdown``，否则首次运行结束即拉起关机倒计时，会抢在重跑前关掉机器。

确认 UI 由前端提供：Rust 前端通过环境变量声明确认程序，Python GUI 在启动时注册
确认函数。本模块只保留「确认后执行 shutdown 命令」的纯逻辑，不导入任何 GUI。

仅 Windows 下真正关机；非 Windows（CI/Linux/macOS）仅记日志跳过关机。
"""

import logging
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)

# CREATE_NO_WINDOW 仅在 Windows 平台存在；非 Windows 用 0 表示无特殊创建标志，
# 保证同一份代码在 Linux/macOS CI 上也能正常执行（不创建隐藏窗口）。
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

RUST_CONFIRM_ENV = "ODH_SHUTDOWN_UI"
RUST_CONFIRM_EXIT = 42
_python_confirmation: Callable[[int], bool] | None = None


def set_shutdown_confirmation(callback: Callable[[int], bool] | None) -> None:
    """注册当前 Python 前端的关机确认函数；None 用于测试或前端退出时清理。"""
    global _python_confirmation
    _python_confirmation = callback


def rust_shutdown_supported() -> bool:
    """只有显式指定的 Windows Rust 前端可承接无 Qt 确认。"""
    if sys.platform != "win32" or RUST_CONFIRM_ENV not in os.environ:
        return False
    path = Path(os.environ[RUST_CONFIRM_ENV])
    return path.is_absolute() and path.is_file()


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
    """请求当前前端确认关机。

    Args:
        countdown: 倒计时秒数。

    Returns:
        确认返回 True；取消/关窗/弹窗失败返回 False。
    """
    if RUST_CONFIRM_ENV in os.environ:
        if not rust_shutdown_supported():
            logger.error("Rust 关机确认入口不可用，按取消处理")
            return False
        try:
            result = subprocess.run(
                [os.environ[RUST_CONFIRM_ENV], "--shutdown-confirm", str(countdown)],
                creationflags=_CREATE_NO_WINDOW,
                capture_output=True,
                timeout=max(0, countdown) + 120,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.error(
                "Rust 关机确认失败 %s(%s)，按取消处理", type(exc).__name__, exc
            )
            return False
        if result.returncode not in (0, RUST_CONFIRM_EXIT):
            logger.error("Rust 关机确认异常退出（%d），按取消处理", result.returncode)
        return result.returncode == RUST_CONFIRM_EXIT

    if _python_confirmation is None:
        logger.error("未注册关机确认前端，按取消处理")
        return False
    return _python_confirmation(countdown)


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
