"""sync_okww_dungeons 的单测：聚焦最前插入模型的重排逻辑（不触网）。

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

import tools.sync_okww_dungeons as m  # noqa: E402

_YAML = YAML()


class TestRebaseSequences(unittest.TestCase):
    def test_delta_1_shifts_existing_and_prepends_placeholder(self):
        seqs = [
            {"display": "梦州-迅刀", "value": 1},
            {"display": "梦州-音感仪", "value": 2},
        ]
        out = m._rebase_sequences(seqs, 1)
        self.assertEqual(
            out,
            [
                {"display": "1", "value": 1},
                {"display": "梦州-迅刀", "value": 2},
                {"display": "梦州-音感仪", "value": 3},
            ],
        )

    def test_delta_2_shifts_all_and_prepends_two(self):
        seqs = [{"display": "A", "value": 1}, {"display": "B", "value": 2}]
        out = m._rebase_sequences(seqs, 2)
        self.assertEqual(
            out,
            [
                {"display": "1", "value": 1},
                {"display": "2", "value": 2},
                {"display": "A", "value": 3},
                {"display": "B", "value": 4},
            ],
        )

    def test_result_sorted_ascending(self):
        seqs = [{"display": "X", "value": 5}, {"display": "Y", "value": 3}]
        out = m._rebase_sequences(seqs, 2)
        vals = [s["value"] for s in out]
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
            "ok-ww": {
                "dungeons": [
                    {
                        "name": "凝素领域",
                        "sequences": [
                            {"display": "梦州-迅刀", "value": 1},
                            {"display": "梦州-音感仪", "value": 2},
                        ],
                    },
                    {
                        "name": "模拟领域",
                        "sequences": [
                            {"display": "共鸣者经验", "value": "共鸣者经验"}
                        ],
                    },
                ]
            }
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
            dungeons = {d["name"]: d for d in after["ok-ww"]["dungeons"]}

            seq = dungeons["凝素领域"]["sequences"]
            self.assertEqual(len(seq), 3)
            self.assertEqual(seq[0], {"display": "1", "value": 1})  # 新副本占位在最前
            self.assertEqual(
                [s["value"] for s in seq if s["display"] == "梦州-迅刀"], [2]
            )  # 别名跟随后移
            self.assertEqual(
                [s["value"] for s in seq if s["display"] == "梦州-音感仪"], [3]
            )

            # 模拟领域（value 为字符串）不在 upstream，应完全不动
            self.assertEqual(
                dungeons["模拟领域"]["sequences"],
                [{"display": "共鸣者经验", "value": "共鸣者经验"}],
            )
        finally:
            os.unlink(path)

    def test_apply_skips_when_no_growth(self):
        data = {
            "ok-ww": {
                "dungeons": [
                    {"name": "凝素领域", "sequences": [{"display": "A", "value": 1}]}
                ]
            }
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
