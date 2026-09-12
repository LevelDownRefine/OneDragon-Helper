"""多个日常的公共契约：声明、命名读写、展示与同步隔离。"""

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from src.config import set_config as adapters
from src.config import task_config
from src.config.set_config import ScriptConfig, get_daily_task, set_config
from src.config.task_config import load_daily_map
from src.service.app_service import AppService, build_task_item, get_daily_map
from tools import sync_oknte_dungeons, sync_okww_dungeons


class ExampleConfig(ScriptConfig):
    _script_name = "example"
    display_name = "示例"
    _config_rel_path = "daily.json"
    _backup_paths = ("daily.json",)


class TestNamedDailyReadWrite(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "daily.json"
        self.initial = {
            "resource_stage": "金币",
            "cleanup_stage": "经验",
            "other": {"enabled": False, "count": 3},
        }
        self.path.write_text(json.dumps(self.initial), encoding="utf-8")
        dailies = [
            {
                "display_name": "资源",
                "options": {"key": "resource_stage", "values": []},
            },
            {"display_name": "清理", "options": {"key": "cleanup_stage", "values": []}},
        ]
        with (
            patch.object(adapters, "load_daily_map", return_value={"example": dailies}),
            patch.dict(adapters._CONFIGS),
        ):
            adapters.register(ExampleConfig)
        for patcher in (
            patch.dict(adapters._CONFIGS, {"example": ExampleConfig}),
            patch.object(adapters, "load_config", side_effect=self._read),
            patch.object(adapters, "save_config", side_effect=self._write),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _read(self, script, path):
        self.assertEqual((script, path), ("example", "daily.json"))
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, script, path, data):
        self.assertEqual((script, path), ("example", "daily.json"))
        self.path.write_text(json.dumps(data), encoding="utf-8")

    def test_second_daily_roundtrip_preserves_first_and_other_fields(self):
        AppService().set_daily_task("example", "清理", "材料")
        self.assertEqual(get_daily_task("example", "清理"), ("材料", None))
        self.assertEqual(get_daily_task("example", "资源"), ("金币", None))
        expected = {**self.initial, "cleanup_stage": "材料"}
        self.assertEqual(self._read("example", "daily.json"), expected)
        AppService().set_daily_task("example", "资源", "装备")
        self.assertEqual(get_daily_task("example", "资源"), ("装备", None))
        self.assertEqual(get_daily_task("example", "清理"), ("材料", None))

    def test_declaration_reorder_does_not_change_identity(self):
        definitions = [
            {"display_name": "清理", "options": {"values": [{"display_name": "经验"}]}},
            {"display_name": "资源", "options": {"values": [{"display_name": "金币"}]}},
        ]
        rows = AppService().get_daily_items("example", definitions)
        self.assertEqual([r["name"] for r in rows], ["清理", "资源"])
        self.assertEqual([r["selection_label"] for r in rows], ["经验", "金币"])

    def test_unknown_daily_rejected_without_writing(self):
        with self.assertRaises(AssertionError):
            set_config("example", "材料", daily_name="不存在")
        with self.assertRaises(AssertionError):
            get_daily_task("example", "不存在")
        self.assertEqual(self._read("example", "daily.json"), self.initial)

    def test_daily_write_cannot_implicitly_target_first_item(self):
        with self.assertRaisesRegex(AssertionError, "必须指定日常名"):
            set_config("example", "材料")
        self.assertEqual(self._read("example", "daily.json"), self.initial)


class TestDailyDeclarations(unittest.TestCase):
    def test_source_only_daily_accepts_native_selection_without_resource_expansion(
        self,
    ):
        cfg = ScriptConfig()
        cfg._daily_configs = {
            "资源": {
                "display_name": "资源",
                "options": {"key": "stage", "source": {"path": "stages.json"}},
            }
        }
        config = {"stage": "旧本", "other": True}
        task = cfg
        task._daily_configs = dict(task._daily_configs)
        task._update_daily_task(config, "资源", "新本")
        self.assertEqual(task._read_daily_config(config, "资源"), ("新本", None))
        self.assertEqual(config, {"stage": "新本", "other": True})

    def test_secondary_value_defaults_to_name_when_writing(self):
        cfg = ScriptConfig()
        cfg._daily_configs = {
            "资源": {
                "display_name": "资源",
                "options": {
                    "key": "kind",
                    "values": [
                        {
                            "display_name": "材料",
                            "options": {
                                "key": "stage",
                                "values": [{"display_name": "高级"}],
                            },
                        }
                    ],
                },
            }
        }
        config = {"kind": "材料", "stage": "旧本"}
        task = cfg
        task._daily_configs = dict(task._daily_configs)
        task._update_daily_task(config, "资源", "材料", "高级")
        self.assertEqual(task._read_daily_config(config, "资源"), ("材料", "高级"))
        self.assertEqual(config["stage"], "高级")

    def test_nte_declares_two_dailies_and_other_scripts_keep_one(self):
        with patch("src.service.app_service.get_task_options", return_value=[]):
            data = get_daily_map()
        self.assertEqual(len(data), 7)
        for script, definitions in data.items():
            with self.subTest(script=script):
                expected = (
                    ["异象界域", "追猎目标"] if script == "ok-nte" else ["每日任务"]
                )
                self.assertEqual(
                    [item["display_name"] for item in definitions], expected
                )
                self.assertTrue(all(item["options"]["values"] for item in definitions))

    def test_rejects_duplicate_empty_and_unnamed_dailies(self):
        valid = {"display_name": "资源", "type": "daily", "options": {"values": []}}
        for definitions in (
            [valid, valid],
            [{"display_name": "", "options": {"values": []}}],
            [{"options": []}],
            valid,
        ):
            task_config._load_task_map.cache_clear()  # 每个 mock 代表一份新声明。
            with (
                self.subTest(definitions=definitions),
                patch(
                    "src.config.task_config.load_yaml",
                    return_value={"example": definitions},
                ),
                self.assertRaises(AssertionError),
            ):
                load_daily_map()

    def test_each_daily_expands_its_own_source_without_mutating_declarations(self):
        data = {
            "example": [
                {
                    "display_name": "资源",
                    "options": {
                        "values": [
                            {
                                "display_name": "目录",
                                "options": {"source": {"path": "a.json"}},
                            }
                        ]
                    },
                },
                {
                    "display_name": "清理",
                    "options": {
                        "values": [
                            {
                                "display_name": "目录",
                                "options": {"source": {"path": "b.json"}},
                            }
                        ]
                    },
                },
            ]
        }
        original = deepcopy(data)
        with (
            patch("src.service.app_service.load_daily_map", return_value=data),
            patch(
                "src.service.app_service.get_task_options",
                side_effect=[["金币"], ["经验"]],
            ) as read,
        ):
            result = get_daily_map()["example"]
        self.assertEqual(data, original)
        self.assertEqual(read.call_args_list[1].args, ("example", "目录", "b.json"))
        self.assertEqual(
            result[0]["options"]["values"][0]["options"]["values"][0]["display_name"],
            "金币",
        )
        self.assertEqual(
            result[1]["options"]["values"][0]["options"]["values"][0]["display_name"],
            "经验",
        )

    def test_unknown_native_value_is_displayed_without_new_alias(self):
        daily = {
            "display_name": "资源",
            "options": {"values": [{"display_name": "金币"}]},
        }
        self.assertEqual(
            build_task_item(daily, ("新关卡", None))["selection_label"], "新关卡"
        )

    def test_display_group_does_not_replace_native_dungeon(self):
        daily = {
            "display_name": "资源",
            "options": {
                "values": [
                    {
                        "display_name": "圣遗物",
                        "options": {
                            "values": [
                                {
                                    "display_name": "仲夏庭园",
                                    "physical_name": "仲夏庭园",
                                }
                            ]
                        },
                    }
                ]
            },
        }
        self.assertEqual(
            build_task_item(daily, ("仲夏庭园", None))["selection_label"], "仲夏庭园"
        )

    def test_noop_daily_keeps_declared_label(self):
        daily = {
            "display_name": "每日任务",
            "options": {"values": [{"display_name": "培养方案"}]},
        }
        self.assertEqual(
            build_task_item(daily, (None, None))["selection_label"], "培养方案"
        )

    def test_sync_tools_find_daily_by_name_after_insertion(self):
        for module, script, daily_name in (
            (sync_okww_dungeons, "ok-ww", "每日任务"),
            (sync_oknte_dungeons, "ok-nte", "daily_anomaly"),
            (sync_oknte_dungeons, "ok-nte", "daily_anomaly_hunter"),
        ):
            with self.subTest(script=script):
                data = {
                    script: [
                        {
                            "display_name": "另一个日常",
                            "type": "daily",
                            "options": {"values": [{"display_name": "不动"}]},
                        },
                        {
                            "display_name": daily_name,
                            "type": "daily",
                            "options": {"values": [{"display_name": "目标"}]},
                        },
                    ]
                }
                result = (
                    module._daily_dungeons(data, daily_name)
                    if script == "ok-nte"
                    else module._daily_dungeons(data)
                )
                self.assertIs(result, data[script][1]["options"]["values"])
