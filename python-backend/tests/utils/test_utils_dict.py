"""字典字段更新与模板涵盖判据：变更、幂等、缺键与类型约束。"""

import unittest

from src.utils.utils_dict import covers, safe_update


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


class TestCovers(unittest.TestCase):
    """covers：模板对齐判据 —— dict 递归、list 按索引（可更长），多出的字段不算差异。"""

    def test_alignment_cases(self):
        cases = (
            (
                "完全一致",
                {"plan_list": [{"tab_name": "A", "category_name": "x"}]},
                {"plan_list": [{"tab_name": "A", "category_name": "x"}]},
                True,
            ),
            (
                "多出字段",
                {"plan_list": [{"tab_name": "A", "category_name": "x", "extra": 1}]},
                {"plan_list": [{"tab_name": "A", "category_name": "x"}]},
                True,
            ),
            (
                "多出列表项",
                {
                    "plan_list": [
                        {"tab_name": "A", "category_name": "x"},
                        {"tab_name": "B", "category_name": "y"},
                    ]
                },
                {"plan_list": [{"tab_name": "A", "category_name": "x"}]},
                True,
            ),
            (
                "顺序不符",
                {
                    "plan_list": [
                        {"tab_name": "B", "category_name": "y"},
                        {"tab_name": "A", "category_name": "x"},
                    ]
                },
                {
                    "plan_list": [
                        {"tab_name": "A", "category_name": "x"},
                        {"tab_name": "B", "category_name": "y"},
                    ]
                },
                False,
            ),
            (
                "取值不符",
                {"plan_list": [{"tab_name": "A", "category_name": "z"}]},
                {"plan_list": [{"tab_name": "A", "category_name": "x"}]},
                False,
            ),
            (
                "缺字段",
                {"plan_list": [{"tab_name": "A"}]},
                {"plan_list": [{"tab_name": "A", "category_name": "x"}]},
                False,
            ),
            (
                "列表更短",
                {"plan_list": [{"tab_name": "A", "category_name": "x"}]},
                {
                    "plan_list": [
                        {"tab_name": "A", "category_name": "x"},
                        {"tab_name": "B", "category_name": "y"},
                    ]
                },
                False,
            ),
            ("缺顶层键", {}, {"double_reward": False}, False),
            ("顶层取值不符", {"double_reward": True}, {"double_reward": False}, False),
        )
        for label, container, template, expected in cases:
            with self.subTest(case=label):
                self.assertIs(covers(container, template), expected)


if __name__ == "__main__":
    unittest.main()
