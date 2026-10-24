"""测试 src.errors 异常家族约定：用户可恢复错误共享 UserError 基类。

RPC 边界（headless.rpc_methods）按该基类统一映射 -32602；新增域异常必须
继承 UserError 才能获得正确映射，本测试守住该契约。
"""

import unittest

from src.errors import UserError
from src.headless import InvalidParams
from src.service.chain_service import InvalidRunRequest
from src.service.script_service import DuplicateScript, InvalidScript
from src.service.task_service import InvalidTaskSelection
from src.utils.utils_job import InvalidJob
from src.utils.utils_sub_config import ScriptConfigUnavailable
from src.utils.utils_wallpaper import InvalidWallpaper

USER_ERRORS = (
    InvalidParams,
    InvalidRunRequest,
    InvalidScript,
    DuplicateScript,
    InvalidTaskSelection,
    InvalidJob,
    InvalidWallpaper,
    ScriptConfigUnavailable,
)


class UserErrorFamilyTests(unittest.TestCase):
    """用户可恢复错误必须挂在 UserError 家族下，消息经 RPC 直接展示。"""

    def test_all_domain_errors_share_base(self):
        for cls in USER_ERRORS:
            with self.subTest(cls=cls.__name__):
                self.assertTrue(issubclass(cls, UserError))

    def test_user_error_is_value_error(self):
        """既有 except ValueError 与测试兼容：基类必须是 ValueError 子类。"""
        self.assertTrue(issubclass(UserError, ValueError))


if __name__ == "__main__":
    unittest.main()
