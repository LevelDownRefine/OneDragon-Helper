"""统一日志配置：控制台 + 文件（每日轮转）+ 进程级异常钩子。

入口（launcher / bgi）在启动时调用 setup_logging()，
使 src/ 全链路的 logging 同时输出到控制台与 logs/onedragon_helper.log。
vendored 的 src/runner 运行器有独立的日志系统（.log/），不在此处理。
"""

import logging
import os
import sys
import threading
from logging.handlers import TimedRotatingFileHandler

from src.utils import get_root_dir, safe_path_join

_LOG_FILE = "onedragon_helper.log"
_configured = False


def setup_logging(level: int = logging.INFO) -> None:
    """配置 root logger：控制台 + logs/onedragon_helper.log（每日轮转，保留 14 天）。

    幂等：重复调用不会重复添加 handler。所有 getLogger(__name__) 子 logger
    会继承 root 的 handler，无需各自配置。
    """
    global _configured
    if _configured:
        return

    root = logging.getLogger()
    root.setLevel(level)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    log_dir = safe_path_join(get_root_dir(), "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = safe_path_join(log_dir, _LOG_FILE)
    file_handler = TimedRotatingFileHandler(
        log_path, when="midnight", backupCount=14, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    _configured = True


def install_crash_hooks() -> None:
    """安装进程级异常钩子：主线程/子线程未捕获异常记入日志，不静默消失。

    GUI（windowed exe）无控制台，逃逸到顶层的异常默认只落 stderr 即消失，
    事后无从排查；钩子先记日志再委托原钩子，不改变退出行为（幂等可重复装）。
    """
    log = logging.getLogger(__name__)

    def _sys_hook(exc_type, exc, tb):
        log.critical("未捕获异常", exc_info=(exc_type, exc, tb))
        sys.__excepthook__(exc_type, exc, tb)

    def _thread_hook(args):
        log.critical(
            "子线程未捕获异常(%s)",
            args.exc_type.__name__,
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )
        threading.__excepthook__(args)

    sys.excepthook = _sys_hook
    threading.excepthook = _thread_hook
