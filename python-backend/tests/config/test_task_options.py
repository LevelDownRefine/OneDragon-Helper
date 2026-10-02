"""任务附带选项的声明范围、资源物化与隔离文件往返。"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.config import task_options as mod


class TestTaskOptions(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(
            patch.object(mod, "get_script_root_dir", return_value=str(self.root))
        )
        self.enterContext(
            patch(
                "src.utils.utils_sub_config.get_script_root_dir",
                return_value=str(self.root),
            )
        )
        self.groups = [
            {
                "display_name": "任务",
                "config": "native.json",
                "fields": [
                    {
                        "id": "enabled",
                        "display_name": "子项",
                        "keys": ["nested", "enabled"],
                        "type": "bool",
                    },
                    {
                        "id": "mode",
                        "display_name": "模式",
                        "keys": ["mode"],
                        "type": "choice",
                        "values": ["a", "b"],
                    },
                    {
                        "id": "targets",
                        "display_name": "目标",
                        "keys": ["targets"],
                        "type": "multi",
                        "values": ["a", "b"],
                        "min_items": 1,
                    },
                ],
            }
        ]
        self.options = mod.TaskOptions("demo", self.groups)
        self.path = self.root / "native.json"
        self.seed = {
            "nested": {"enabled": True, "other": 8},
            "mode": "a",
            "targets": ["b", "a"],
            "keep": 12,
        }
        self.path.write_text(json.dumps(self.seed), encoding="utf-8")

    def test_round_trip_preserves_unsubmitted_fields_and_external_edits(self):
        self.assertEqual(self.options.read()[2]["value"], ["b", "a"])
        self.seed["keep"] = 99
        self.path.write_text(json.dumps(self.seed), encoding="utf-8")
        self.options.write_prepared(
            self.options.prepare({"enabled": False, "mode": "b", "targets": ["a"]})
        )
        self.assertEqual(
            json.loads(self.path.read_text()),
            {
                "nested": {"enabled": False, "other": 8},
                "mode": "b",
                "targets": ["a"],
                "keep": 99,
            },
        )

    def test_rejects_invalid_inputs_before_any_write(self):
        original = self.path.read_bytes()
        for values in [
            {"enabled": 1},
            {"mode": 2},
            {"mode": "unknown"},
            {"unknown": True},
            {"targets": []},
            {"targets": ["a", "a"]},
            {"targets": ["x"]},
        ]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.options.prepare(values)
            self.assertEqual(self.path.read_bytes(), original)

    def test_missing_files_and_fields_are_not_filled_or_created(self):
        self.path.unlink()
        self.assertEqual(self.options.read(), [])
        with self.assertRaises(ValueError):
            self.options.prepare({"mode": "b"})
        self.assertFalse(self.path.exists())
        self.path.write_text('{"nested": {}, "mode": "b"}', encoding="utf-8")
        self.assertEqual([row["id"] for row in self.options.read()], ["mode"])
        self.assertEqual(self.options.read()[0]["value"], "b")
        with self.assertRaises(ValueError):
            self.options.prepare({"enabled": True})
        self.assertEqual(json.loads(self.path.read_text()), {"nested": {}, "mode": "b"})

    def test_same_file_groups_merge_nested_options(self):
        self.groups.append(
            {
                "display_name": "另一任务",
                "config": "native.json",
                "fields": [
                    {
                        "id": "extra",
                        "display_name": "额外",
                        "keys": ["other", "flag"],
                        "type": "bool",
                    }
                ],
            }
        )
        self.seed["other"] = {"flag": False}
        self.path.write_text(json.dumps(self.seed), encoding="utf-8")
        pending = self.options.prepare({"enabled": False, "extra": True})
        self.assertEqual(len(pending), 1)
        self.options.write_prepared(pending)
        actual = json.loads(self.path.read_text())
        self.assertFalse(actual["nested"]["enabled"])
        self.assertTrue(actual["other"]["flag"])

    def test_current_unknown_value_can_be_preserved(self):
        self.seed["mode"] = "new upstream value"
        self.path.write_text(json.dumps(self.seed), encoding="utf-8")
        self.assertEqual(
            self.options.read()[1]["choices"][-1]["physical_name"], "new upstream value"
        )
        self.options.prepare({"mode": "new upstream value"})

    def test_local_sources_expand_without_executing_script(self):
        field = self.groups[0]["fields"][1]
        del field["values"]
        for source, files, expected in [
            (
                {"path": "characters.json", "field": "zh"},
                {"characters.json": '{"one":{"zh":"甲"},"two":{"zh":"乙"}}'},
                ["甲", "乙"],
            ),
            (
                {"path": "routes", "prefix": "冒险家协会_"},
                {
                    "routes/冒险家协会_枫丹.json": "{}",
                    "routes/冒险家协会_蒙德.json": "{}",
                    "routes/其他.json": "{}",
                },
                ["枫丹", "蒙德"],
            ),
            (
                {
                    "path": "agents.py",
                    "enum": "AgentEnum",
                    "argument": 1,
                    "prepend": ["随机"],
                },
                {
                    "agents.py": 'raise RuntimeError("must not execute")\nclass AgentEnum:\n    ONE = Agent("one", "甲")\n    TWO = Agent("two", "乙")\n'
                },
                ["随机", "甲", "乙"],
            ),
            (
                {"path": "areas.json", "key": ["areas"]},
                {"areas.json": '{"areas":{"甲":{},"乙":{}}}'},
                ["甲", "乙"],
            ),
        ]:
            with self.subTest(source=source):
                field["source"] = source
                for name, content in files.items():
                    path = self.root / name
                    path.parent.mkdir(exist_ok=True)
                    path.write_text(content, encoding="utf-8")
                self.assertEqual(
                    [
                        choice["physical_name"]
                        for choice in self.options._choices(field)
                    ],
                    expected,
                )

    def test_accepted_scope_is_declared(self):
        declarations = mod.load_declarations()
        self.assertEqual(
            set(declarations),
            {"ok-ef", "ok-ww", "BetterGI", "OneDragon-Launcher", "ok-nte"},
        )
        self.assertEqual(
            [group["display_name"] for group in declarations["BetterGI"]],
            ["领取每日奖励"],
        )
        self.assertNotIn(
            "随便观",
            [group["display_name"] for group in declarations["OneDragon-Launcher"]],
        )
        self.assertNotIn(
            "一咖舍", [group["display_name"] for group in declarations["ok-nte"]]
        )

    def test_absent_script_has_no_options(self):
        with patch.object(mod, "get_script_root_dir", return_value=None):
            self.assertEqual(self.options.read(), [])

    def test_corrupt_resource_omits_only_affected_choice(self):
        field = self.groups[0]["fields"][1]
        del field["values"]
        field["source"] = {"path": "broken.json", "field": "zh"}
        (self.root / "broken.json").write_text("{broken", encoding="utf-8")
        with self.assertLogs(mod.logger, level="WARNING") as logs:
            self.assertEqual(
                [row["id"] for row in self.options.read()], ["enabled", "targets"]
            )
        self.assertIn("JSONDecodeError", logs.output[0])

    def test_changed_upstream_resource_shape_is_reported_and_omitted(self):
        field = self.groups[0]["fields"][1]
        del field["values"]
        field["source"] = {"path": "changed.json", "field": "zh"}
        for content in ["[]", '{"one":{"name":"renamed"}}', '{"one":{"zh":1}}']:
            with self.subTest(content=content):
                (self.root / "changed.json").write_text(content, encoding="utf-8")
                with self.assertLogs(mod.logger, level="WARNING") as logs:
                    self.assertEqual(
                        [row["id"] for row in self.options.read()],
                        ["enabled", "targets"],
                    )
                self.assertIn("ValueError", logs.output[0])

    def test_undeclared_script_does_not_read_user_configuration(self):
        with patch.object(
            mod, "get_script_root_dir", side_effect=AssertionError("unexpected IO")
        ):
            self.assertEqual(mod.TaskOptions("custom", []).read(), [])
