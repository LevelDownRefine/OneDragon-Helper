"""配置差异断言必须区分类型变化、缺键与真实的占位字符串。"""

import unittest
from copy import deepcopy

from tests.support.config_diff import diff_paths


class TestConfigDiff(unittest.TestCase):
    def test_equal_nested_values_have_no_diff(self):
        data = {"config": {"items": [True, 1, 1.0, None, "中文"]}}
        self.assertEqual(diff_paths(data, deepcopy(data)), [])

    def test_equal_numeric_values_with_different_types_are_changes(self):
        before = {"config": {"items": [True, 1, False]}}
        after = {"config": {"items": [1, 1.0, 0]}}
        changes = diff_paths(before, after)
        self.assertEqual(
            [path for path, _, _ in changes],
            ["config.items[0]", "config.items[1]", "config.items[2]"],
        )
        self.assertEqual(
            [(type(old), type(new)) for _, old, new in changes],
            [(bool, int), (int, float), (bool, int)],
        )

    def test_missing_marker_is_still_a_real_value(self):
        cases = (
            ({}, {"x": "<MISSING>"}, "x"),
            ({"x": "<MISSING>"}, {}, "x"),
            ({"x": []}, {"x": ["<MISSING>"]}, "x[0]"),
            ({"x": ["<MISSING>"]}, {"x": []}, "x[0]"),
        )
        for before, after, path in cases:
            with self.subTest(before=before, after=after):
                changes = diff_paths(before, after)
                self.assertEqual(len(changes), 1)
                self.assertEqual(changes[0][0], path)

    def test_paths_are_stable_and_inputs_are_unchanged(self):
        before = {"z": [1, 2], "a": {"old": 3}}
        after = {"z": [1], "a": {"new": 4}}
        original = deepcopy((before, after))
        self.assertEqual(
            diff_paths(before, after),
            [
                ("a.new", "<MISSING>", 4),
                ("a.old", 3, "<MISSING>"),
                ("z[1]", 2, "<MISSING>"),
            ],
        )
        self.assertEqual((before, after), original)


if __name__ == "__main__":
    unittest.main()
