"""字典字段更新：变更、幂等、缺键与类型约束。"""

import unittest

from src.utils.utils_dict import safe_update


class TestSafeUpdate(unittest.TestCase):
    """测试 safe_update"""

    def test_update_changes_value(self):
        """值不同时更新并返回 True"""
        config = {"key": "old"}
        result = safe_update(config, "key", "new", "test")
        self.assertTrue(result)
        self.assertEqual(config["key"], "new")

    def test_no_change_when_same_value(self):
        """值相同时不更新并返回 False"""
        config = {"key": "same"}
        result = safe_update(config, "key", "same", "test")
        self.assertFalse(result)
        self.assertEqual(config["key"], "same")

    def test_key_not_exists_raises(self):
        """key 不存在时 assert（默认）"""
        config = {}
        with self.assertRaises(AssertionError):
            safe_update(config, "missing", "value", "test")

    def test_key_not_exists_adds_with_flag(self):
        """assert_key_exists=False 时允许添加新 key"""
        config = {"a": 1}
        result = safe_update(config, "b", "new", "test", assert_key_exists=False)
        self.assertTrue(result)
        self.assertEqual(config, {"a": 1, "b": "new"})

    def test_type_mismatch_raises(self):
        """类型不一致时 assert"""
        config = {"a": 1}
        with self.assertRaises(AssertionError):
            safe_update(config, "a", "string", "test")


if __name__ == "__main__":
    unittest.main()
