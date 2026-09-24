"""sync_okww_tasks 的单测：聚焦最前插入模型的重排逻辑（不触网）。"""

import os
import tempfile
import unittest
from unittest.mock import patch

from ruamel.yaml import YAML

import tools.sync_okww_tasks as m

_YAML = YAML()


class TestRebaseSequences(unittest.TestCase):
    def test_repeated_growth_renumbers_placeholders_and_preserves_friendly_names(self):
        from src.config.task_config import validate_options

        options = [{"display_name": "梦州-迅刀", "physical_name": 1}]
        for delta in (2, 1, 2):
            options = m._rebase_sequences(options, delta)
            validate_options(options, "连续同步")
        self.assertEqual(
            options,
            [
                *[{"display_name": str(v), "physical_name": v} for v in range(1, 6)],
                {"display_name": "梦州-迅刀", "physical_name": 6},
            ],
        )

    def test_rebase_preserves_input_and_names_with_sorted_new_placeholders(self):
        for name, delta, before, after in (
            (
                "one",
                1,
                [("梦州-迅刀", 1), ("梦州-音感仪", 2)],
                [("1", 1), ("梦州-迅刀", 2), ("梦州-音感仪", 3)],
            ),
            ("two", 2, [("A", 1), ("B", 2)], [("1", 1), ("2", 2), ("A", 3), ("B", 4)]),
            (
                "unordered",
                2,
                [("X", 5), ("Y", 3)],
                [("1", 1), ("2", 2), ("Y", 5), ("X", 7)],
            ),
        ):
            with self.subTest(name=name):
                original = [
                    {"display_name": label, "physical_name": value}
                    for label, value in before
                ]
                options = [dict(item) for item in original]
                result = m._rebase_sequences(options, delta)
                self.assertEqual(
                    result,
                    [
                        {"display_name": label, "physical_name": value}
                        for label, value in after
                    ],
                )
                self.assertEqual(options, original)


class TestApplyNewFrontInsert(unittest.TestCase):
    def _write_tmp(self, data: dict) -> str:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".yml", delete=False, encoding="utf-8"
        ) as tmp:
            _YAML.dump(data, tmp)
            return tmp.name

    def test_apply_rebases_numeric_category_only(self):
        data = {
            "ok-ww": [
                {
                    "display_name": "每日任务",
                    "options": {
                        "key": "Which to Farm",
                        "values": [
                            {
                                "display_name": "凝素领域",
                                "physical_name": "Forgery Challenge",
                                "options": {
                                    "key": "Which Forgery Challenge to Farm",
                                    "values": [
                                        {
                                            "display_name": "梦州-迅刀",
                                            "physical_name": 1,
                                        },
                                        {
                                            "display_name": "梦州-音感仪",
                                            "physical_name": 2,
                                        },
                                    ],
                                },
                            },
                            {
                                "display_name": "模拟领域",
                                "physical_name": "Simulation Challenge",
                                "options": {
                                    "key": "Material Selection",
                                    "values": [
                                        {
                                            "display_name": "共鸣者经验",
                                            "physical_name": "Resonator EXP",
                                        }
                                    ],
                                },
                            },
                        ],
                    },
                },
                {
                    "display_name": "另一个日常",
                    "options": {"values": [{"display_name": "保留"}]},
                },
            ]
        }
        path = self._write_tmp(data)
        self.addCleanup(os.unlink, path)
        with patch.object(m, "_DUNGEON_PATH", path):
            # 生产里 upstream 只含数字分类（凝素领域/无音区），不含模拟领域
            upstream = {"凝素领域": 3}
            current = m._load_okww()
            m._apply_new(upstream, current)

            with open(path, encoding="utf-8") as f:
                after = _YAML.load(f)
            self.assertEqual(after["ok-ww"][0]["options"]["key"], "Which to Farm")
            self.assertEqual(after["ok-ww"][1], data["ok-ww"][1])
            options = {
                d["display_name"]: d for d in after["ok-ww"][0]["options"]["values"]
            }
            self.assertEqual(options["凝素领域"]["physical_name"], "Forgery Challenge")
            self.assertEqual(
                options["凝素领域"]["options"]["key"],
                "Which Forgery Challenge to Farm",
            )

            seq = options["凝素领域"]["options"]["values"]
            self.assertEqual(len(seq), 3)
            self.assertEqual(
                seq[0], {"display_name": "1", "physical_name": 1}
            )  # 新副本占位在最前
            self.assertEqual(
                [s["physical_name"] for s in seq if s["display_name"] == "梦州-迅刀"],
                [2],
            )  # 别名跟随后移
            self.assertEqual(
                [s["physical_name"] for s in seq if s["display_name"] == "梦州-音感仪"],
                [3],
            )

            # 模拟领域（value 为字符串）不在 upstream，应完全不动
            self.assertEqual(
                options["模拟领域"]["options"]["values"],
                [{"display_name": "共鸣者经验", "physical_name": "Resonator EXP"}],
            )

    def test_apply_skips_when_no_growth(self):
        data = {
            "ok-ww": [
                {
                    "display_name": "每日任务",
                    "options": {
                        "values": [
                            {
                                "display_name": "凝素领域",
                                "options": {
                                    "values": [
                                        {"display_name": "A", "physical_name": 1}
                                    ]
                                },
                            }
                        ]
                    },
                }
            ]
        }
        path = self._write_tmp(data)
        self.addCleanup(os.unlink, path)
        with patch.object(m, "_DUNGEON_PATH", path):
            upstream = {"凝素领域": 1}  # 无增长
            current = m._load_okww()
            with open(path, encoding="utf-8") as f:
                before = f.read()
            m._apply_new(upstream, current)
            with open(path, encoding="utf-8") as f:
                after = f.read()
            self.assertEqual(before, after)  # 不变


if __name__ == "__main__":
    unittest.main()
