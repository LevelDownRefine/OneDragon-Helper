import os
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src import utils
from src.utils.utils_logger import install_crash_hooks


class TestUtils(unittest.TestCase):
    def test_get_root_dir(self):
        root_dir = utils.get_root_dir()
        self.assertTrue(os.path.isabs(root_dir))
        self.assertTrue(os.path.isdir(root_dir))

    def test_get_our_bgi_user_dir(self):
        bgi_user_dir = utils.get_our_bgi_user_dir()
        root_dir = utils.get_root_dir()
        self.assertEqual(bgi_user_dir, os.path.join(root_dir, "config", "BGI_User"))

    def test_get_config_yml_path_under_root(self):
        yml_path = utils.get_config_yml_path_under_root()
        root_dir = utils.get_root_dir()
        self.assertEqual(yml_path, os.path.join(root_dir, "config", "config.yml"))

    def test_get_path_under_root(self):
        # Without subdirs
        path = utils.get_path_under_root()
        self.assertEqual(path, utils.get_root_dir())

        # With subdirs (using mock to avoid actually creating it if it doesn't exist)
        with patch("src.utils.join_dir_path_with_mk") as mock_join:
            mock_join.return_value = "mock_path"
            res = utils.get_path_under_root("sub1", "sub2")
            self.assertEqual(res, "mock_path")
            mock_join.assert_called_once_with(utils.get_root_dir(), "sub1", "sub2")

    def test_safe_path_join_normal(self):
        base = os.path.abspath(os.sep + "base")
        # 单层子路径
        res = utils.safe_path_join(base, "sub")
        self.assertEqual(res, os.path.join(base, "sub"))
        # 多层子路径
        res = utils.safe_path_join(base, "a", "b", "c.json")
        self.assertEqual(res, os.path.join(base, "a", "b", "c.json"))
        # 相对片段中的 . 归一化后仍在 base 内
        res = utils.safe_path_join(base, "a", ".", "b")
        self.assertEqual(res, os.path.join(base, "a", "b"))

    def test_safe_path_join_equals_base(self):
        base = os.path.abspath(os.sep + "base")
        # 空拼接返回 base 本身
        self.assertEqual(utils.safe_path_join(base), base)

    def test_safe_path_join_rejects_parent_traversal(self):
        base = os.path.abspath(os.sep + "base")
        with self.assertRaises(AssertionError):
            utils.safe_path_join(base, "..")
        with self.assertRaises(AssertionError):
            utils.safe_path_join(base, "a", "..", "..", "etc")

    def test_safe_path_join_rejects_absolute_override(self):
        base = os.path.abspath(os.sep + "base")
        # 绝对路径片段会覆盖 base，应被拦截
        with self.assertRaises(AssertionError):
            utils.safe_path_join(base, os.path.abspath(os.sep + "evil"))

    def test_safe_path_join_rejects_sibling_prefix(self):
        # /base2 不应被误判为在 /base 内（防 startswith 前缀漏洞）
        base = os.path.abspath(os.sep + "base")
        with self.assertRaises(AssertionError):
            utils.safe_path_join(base, ".." + os.sep + "base2")

    def test_join_dir_path_with_mk(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            # Let's test joining normal subdirectories
            res = utils.join_dir_path_with_mk(temp_dir, "sub1", "sub2")
            expected = os.path.normpath(os.path.join(temp_dir, "sub1", "sub2"))
            self.assertEqual(os.path.normpath(res), expected)
            self.assertTrue(os.path.isdir(expected))

            # Let's test handling None in subs
            res_none = utils.join_dir_path_with_mk(temp_dir, "sub3", None, "sub4")
            expected_none = os.path.normpath(os.path.join(temp_dir, "sub3", "sub4"))
            self.assertEqual(os.path.normpath(res_none), expected_none)
            self.assertTrue(os.path.isdir(expected_none))


class TestGetRootDirFrozen(unittest.TestCase):
    """验证 PyInstaller 冻结模式下 get_root_dir() 返回 exe 所在目录，而非 __file__ 推导路径。

    这些测试不需要实际的 exe 文件——通过 mock sys.frozen 和 sys.executable 模拟冻结环境。
    """

    def setUp(self):
        # get_root_dir 使用 @lru_cache，测试前必须清缓存，否则会拿到上次（非冻结）的结果
        utils.get_root_dir.cache_clear()

    def tearDown(self):
        # 测试后也要清缓存，避免影响后续测试
        utils.get_root_dir.cache_clear()

    def test_frozen_returns_exe_dir(self):
        fake_exe = os.path.join(os.sep, "app", "OneDragon-Helper.exe")
        with patch("sys.frozen", True, create=True), patch("sys.executable", fake_exe):
            result = utils.get_root_dir()
            self.assertEqual(result, os.path.dirname(fake_exe))

    def test_frozen_not_uses_file(self):
        """冻结模式下不应返回 __file__ 推导的路径（即不应是 src/ 的父目录）。"""
        fake_exe = os.path.join(os.sep, "deploy", "dist", "OneDragon-Helper.exe")
        with patch("sys.frozen", True, create=True), patch("sys.executable", fake_exe):
            result = utils.get_root_dir()
            # 不应包含 src 目录
            self.assertNotIn("src", result)
            self.assertEqual(result, os.path.dirname(fake_exe))

    def test_non_frozen_uses_file(self):
        """非冻结模式下走 __file__ 推导（原始行为不变）。"""
        with patch("sys.frozen", False, create=True):
            utils.get_root_dir.cache_clear()
            result = utils.get_root_dir()
            # 非冻结模式应返回 src/ 的父目录（项目根）
            self.assertTrue(os.path.isdir(result))
            self.assertTrue(os.path.isdir(os.path.join(result, "src")))


class TestCrashHooks(unittest.TestCase):
    """install_crash_hooks：主/子线程未捕获异常先记日志再委托原钩子。"""

    def setUp(self):
        old_sys, old_thread = sys.excepthook, threading.excepthook
        self.addCleanup(setattr, sys, "excepthook", old_sys)
        self.addCleanup(setattr, threading, "excepthook", old_thread)
        install_crash_hooks()

    def test_sys_hook_installed(self):
        self.assertIsNot(sys.excepthook, sys.__excepthook__)

    def test_sys_hook_logs_and_delegates(self):
        with (
            patch("sys.__excepthook__") as delegate,
            self.assertLogs("src.utils.utils_logger", level="CRITICAL") as captured,
        ):
            try:
                raise ValueError("boom")
            except ValueError:
                sys.excepthook(*sys.exc_info())
        delegate.assert_called_once()
        self.assertTrue(any("未捕获异常" in line for line in captured.output))

    def test_thread_hook_logs_and_delegates(self):
        try:
            raise RuntimeError("thread boom")
        except RuntimeError:
            exc = sys.exc_info()
        args = SimpleNamespace(exc_type=exc[0], exc_value=exc[1], exc_traceback=exc[2])
        with (
            patch("threading.__excepthook__") as delegate,
            self.assertLogs("src.utils.utils_logger", level="CRITICAL") as captured,
        ):
            threading.excepthook(args)
        delegate.assert_called_once()
        self.assertTrue(any("子线程" in line for line in captured.output))


if __name__ == "__main__":
    unittest.main()
