"""隔离日常菜单的外部资源，保留机制类和菜单展开的真实实现。"""

from contextlib import ExitStack, contextmanager
from unittest.mock import patch

from src.config.daily import BgiDaily, Daily, MaaActivityDaily


@contextmanager
def patch_daily_sources(reader):
    """替换三种资源读取方法；reader 接收实际日常对象与 source 声明。"""
    with ExitStack() as stack:
        for cls in (Daily, BgiDaily, MaaActivityDaily):
            stack.enter_context(
                patch.object(cls, "get_task_lists", autospec=True, side_effect=reader)
            )
        yield
