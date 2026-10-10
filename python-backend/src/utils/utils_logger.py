"""统一日志配置：控制台 + 文件（按日分文件）+ 进程级异常钩子。

入口（launcher / headless）在启动时调用 setup_logging()，
使 src/ 全链路的 logging 同时输出到控制台与 logs/ 下的当日文件。
GUI 侧（含其 serve 子进程）与计划/运行侧分文件落盘：两侧会同时持有
各自的日志文件，若按 rename 轮转，Windows 上会被另一个持有者拒绝
（WinError 32）并让该进程后续日志全部丢失。
vendored 的 runner 运行器有独立的日志系统（.log/），不在此处理。
"""

import logging
import os
import re
import sys
import threading
import time
from contextlib import suppress
from datetime import date, timedelta

from src.utils import get_root_dir, safe_path_join

# 进程角色 → 日志文件名前缀。同一角色同一时刻只有一个目标写者。
_LOG_PREFIXES = {"gui": "onedragon_helper", "plan": "onedragon_helper.plan"}
_BACKUP_DAYS = 14
_configured = False


def today() -> str:
    """当前本地日期（YYYY-MM-DD），日志文件名与跨日判定共用。"""
    return time.strftime("%Y-%m-%d")


class _DailyFileHandler(logging.FileHandler):
    """按本地日期分文件的日志 handler。

    跨日时只关掉旧文件、改用当天文件，不做 rename：同一日志文件可能被多个
    进程同时持有，而 rename 需要独占删除权，必然失败。
    """

    def __init__(self, directory: str, prefix: str) -> None:
        self._directory = directory
        self._prefix = prefix
        self._day = today()
        super().__init__(self._path_for(self._day), encoding="utf-8", delay=True)

    def _path_for(self, day: str) -> str:
        return safe_path_join(self._directory, f"{self._prefix}-{day}.log")

    def emit(self, record: logging.LogRecord) -> None:
        day = today()
        if day != self._day:
            self._rotate(day)
        super().emit(record)

    def _rotate(self, day: str) -> None:
        """关掉旧文件并切到当天文件（写入时惰性打开新文件）。"""
        self.close()
        self._day = day
        self.baseFilename = os.path.abspath(self._path_for(day))


def purge_expired_logs(directory: str, prefix: str) -> None:
    """删除同前缀中日期超过保留期的日志文件；被占用或不可删则跳过。"""
    pattern = re.compile(rf"^{re.escape(prefix)}-(\d{{4}}-\d{{2}}-\d{{2}})\.log$")
    deadline = date.today() - timedelta(days=_BACKUP_DAYS)
    for entry in os.scandir(directory):
        if not entry.is_file():
            continue
        matched = pattern.match(entry.name)
        if matched is None:
            continue
        try:
            day = date.fromisoformat(matched.group(1))
        except ValueError:
            continue
        if day >= deadline:
            continue
        with suppress(OSError):
            os.remove(entry.path)


def setup_logging(level: int = logging.INFO, *, role: str = "gui") -> None:
    """配置 root logger：控制台 + logs/ 下当日文件（按日保留 14 天）。

    幂等：重复调用不会重复添加 handler。所有 getLogger(__name__) 子 logger
    会继承 root 的 handler，无需各自配置。

    Args:
        level: root logger 级别。
        role: 进程角色；``gui``（含 GUI 子进程）与 ``plan``（计划/运行）分文件。
    """
    global _configured
    if _configured:
        return
    assert role in _LOG_PREFIXES, role

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
    prefix = _LOG_PREFIXES[role]
    purge_expired_logs(log_dir, prefix)
    file_handler = _DailyFileHandler(log_dir, prefix)
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
