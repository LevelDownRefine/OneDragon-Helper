import os
import tempfile
import unittest
from unittest.mock import patch

from src import utils
from src.service.chain_service import _state_file


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


class TestSetRootDir(unittest.TestCase):
    """set_root_dir：测试期把整棵配置树指向临时目录，不污染本机配置。

    配置读写方（config/*.yml、gui_state.json、链输出）全部由 get_root_dir() 派生，
    故改这一个入口即整体改向，无需各模块各自 patch 路径函数。
    """

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(utils.set_root_dir, None)  # 无论如何都还原真实项目根
        self.addCleanup(self.tmp_dir.cleanup)

    def test_override_redirects_every_config_path(self):
        utils.set_root_dir(self.tmp_dir.name)
        root = utils.get_root_dir()
        self.assertEqual(root, os.path.abspath(self.tmp_dir.name))
        for path in (
            utils.get_config_yml_path_under_root(),
            utils.get_schedule_yml_path_under_root(),
            utils.get_weekly_start_yml_path_under_root(),
            utils.get_weekly_timeouts_yml_path_under_root(),
            utils.get_path_under_root("config", "script_chain"),
            _state_file(),
        ):
            self.assertTrue(path.startswith(root + os.sep), path)
            self.assertEqual(os.path.dirname(path), os.path.join(root, "config"))

    def test_none_restores_real_root(self):
        real = utils.get_root_dir()
        utils.set_root_dir(self.tmp_dir.name)
        self.assertNotEqual(utils.get_root_dir(), real)
        utils.set_root_dir(None)
        self.assertEqual(utils.get_root_dir(), real)

    def test_override_wins_over_frozen(self):
        """打包形态下仍以覆盖值为准：注入不因 sys.frozen 失效。"""
        fake_exe = os.path.join(os.sep, "app", "OneDragon-Helper.exe")
        with patch("sys.frozen", True, create=True), patch("sys.executable", fake_exe):
            utils.set_root_dir(self.tmp_dir.name)
            self.assertEqual(utils.get_root_dir(), os.path.abspath(self.tmp_dir.name))


if __name__ == "__main__":
    unittest.main()
