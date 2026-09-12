"""sync_okww_tasks 的单测：聚焦最前插入模型的重排逻辑（不触网）。

模块位于 tools/ 下、非 src 包，故手动将项目根加入 sys.path 后按命名空间包导入。
"""

import os
import sys
import tempfile
import unittest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from ruamel.yaml import YAML  # noqa: E402

import tools.sync_okww_tasks as m  # noqa: E402

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

    def test_rebase_preserves_display_alias(self):
        option = {"display_name": "A", "physical_name": 1}
        self.assertEqual(
            m._rebase_sequences([option], 1)[1], {**option, "physical_name": 2}
        )
        self.assertEqual(option["physical_name"], 1)

    def test_delta_1_shifts_existing_and_prepends_placeholder(self):
        seqs = [
            {"display_name": "梦州-迅刀", "physical_name": 1},
            {"display_name": "梦州-音感仪", "physical_name": 2},
        ]
        out = m._rebase_sequences(seqs, 1)
        self.assertEqual(
            out,
            [
                {"display_name": "1", "physical_name": 1},
                {"display_name": "梦州-迅刀", "physical_name": 2},
                {"display_name": "梦州-音感仪", "physical_name": 3},
            ],
        )

    def test_delta_2_shifts_all_and_prepends_two(self):
        seqs = [
            {"display_name": "A", "physical_name": 1},
            {"display_name": "B", "physical_name": 2},
        ]
        out = m._rebase_sequences(seqs, 2)
        self.assertEqual(
            out,
            [
                {"display_name": "1", "physical_name": 1},
                {"display_name": "2", "physical_name": 2},
                {"display_name": "A", "physical_name": 3},
                {"display_name": "B", "physical_name": 4},
            ],
        )

    def test_result_sorted_ascending(self):
        seqs = [
            {"display_name": "X", "physical_name": 5},
            {"display_name": "Y", "physical_name": 3},
        ]
        out = m._rebase_sequences(seqs, 2)
        vals = [s["physical_name"] for s in out]
        self.assertEqual(vals, sorted(vals))


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
        try:
            m._DUNGEON_PATH = path
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
        finally:
            os.unlink(path)

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
        try:
            m._DUNGEON_PATH = path
            upstream = {"凝素领域": 1}  # 无增长
            current = m._load_okww()
            with open(path, encoding="utf-8") as f:
                before = f.read()
            m._apply_new(upstream, current)
            with open(path, encoding="utf-8") as f:
                after = f.read()
            self.assertEqual(before, after)  # 不变
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
