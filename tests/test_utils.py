import os
import tempfile
import unittest
from unittest.mock import patch

import utils


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
        with patch('utils.join_dir_path_with_mk') as mock_join:
            mock_join.return_value = "mock_path"
            res = utils.get_path_under_root("sub1", "sub2")
            self.assertEqual(res, "mock_path")
            mock_join.assert_called_once_with(utils.get_root_dir(), "sub1", "sub2")

    def test_get_path_under_onedragon(self):
        with patch('utils.join_dir_path_with_mk') as mock_join:
            mock_join.return_value = "mock_path"
            res = utils.get_path_under_onedragon("sub1")
            self.assertEqual(res, "mock_path")
            mock_join.assert_called_once_with(utils.get_root_dir(), "OneDragon-ScriptChainer", "sub1")

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

if __name__ == "__main__":
    unittest.main()
