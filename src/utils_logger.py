"""统一日志配置：控制台 + 文件（每日轮转）。

入口（launcher / bgi）在启动时调用 setup_logging()，
使 src/ 全链路的 logging 同时输出到控制台与 logs/onedragon_helper.log。
vendored 的 src/runner 运行器有独立的日志系统（.log/），不在此处理。
"""
import logging
import os
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
