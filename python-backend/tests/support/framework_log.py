"""框架日志 fixture：把日志根指向临时目录并复位幂等标志。"""

import logging
import tempfile
from contextlib import contextmanager

import src.utils.utils_logger as utils_logger


@contextmanager
def temp_framework_root():
    """让 setup_logging 落盘到临时根，退出时复位日志根与新增的 handler。

    Yields:
        临时根目录路径。
    """
    with tempfile.TemporaryDirectory() as tmp:
        root_logger = logging.getLogger()
        before = {id(handler) for handler in root_logger.handlers}
        original_root = utils_logger.get_root_dir
        original_role = utils_logger._configured_role
        utils_logger.get_root_dir = lambda: tmp
        utils_logger._configured_role = None
        try:
            yield tmp
        finally:
            utils_logger.get_root_dir = original_root
            utils_logger._configured_role = original_role
            for handler in list(root_logger.handlers):
                if id(handler) not in before:
                    root_logger.removeHandler(handler)
                    handler.close()
