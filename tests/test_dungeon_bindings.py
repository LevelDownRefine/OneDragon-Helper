"""副本声明驱动真实 JSON 往返、显示别名和跨日常隔离。"""

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from src.config import set_config as adapters
from src.config.set_config import NTEConfig, ScriptConfig, WutheringWavesConfig
from src.config.task_config import (
    load_daily_map,
    validate_daily_definitions,
)
from src.service.app_service import AppService, build_task_item
from src.utils.utils_yaml import load_yaml_str


class TestDailyDeclarationRoundTrip(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for patcher in (
            patch.object(adapters, "load_config", side_effect=self._load),
            patch.object(adapters, "save_config", side_effect=self._save),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _load(self, script, rel):
        return json.loads((self.root / script / rel).read_text(encoding="utf-8"))

    def _save(self, script, rel, data):
        path = self.root / script / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def _nte_files(self, *, hunter_present=True):
        config = {
            "daily_anomaly": {"任务类型": "空幕", "空幕序号": 1, "次数": 9},
            "daily_anomaly_hunter": {"追猎目标": "音霸魔王", "目标消耗体力": 240},
            "other": {"enabled": False},
        }
        items = [{"id": "daily_anomaly", "enabled": True}]
        if hunter_present:
            items.append({"id": "daily_anomaly_hunter", "enabled": False})
        routine = {"Routine Items": [*items, {"id": "mail", "enabled": True}]}
        self._save("ok-nte", NTEConfig._config_rel_path, config)
        self._save("ok-nte", adapters.NTEConfig._routine_config_rel_path, routine)
        return config, routine

    def test_wuwa_menu_value_writes_native_value_and_reads_chinese_label(self):
        initial = {
            "Which to Farm": "Tacet Suppression",
            "Material Selection": "Weapon EXP",
            "Which Tacet Suppression to Farm": 3,
            "Other": {"enabled": False},
        }
        self._save("ok-ww", WutheringWavesConfig._config_rel_path, initial)
        daily = load_daily_map()["ok-ww"][0]
        row = build_task_item(daily, ("模拟领域", "Weapon EXP"))
        menu = next(item for item in row["options"] if item["name"] == "模拟领域")
        selection = next(
            item for item in menu["options"] if item["name"] == "共鸣者经验"
        )
        self.assertEqual(selection["value"], "Resonator EXP")
        AppService().set_daily_task("ok-ww", "每日任务", "模拟领域", selection["value"])
        self.assertEqual(
            self._load("ok-ww", WutheringWavesConfig._config_rel_path),
            {
                **initial,
                "Which to Farm": "Simulation Challenge",
                "Material Selection": "Resonator EXP",
            },
        )
        rows = AppService().get_daily_items("ok-ww", [daily])
        self.assertEqual(rows[0]["selection_label"], "模拟领域 · 共鸣者经验")

    def test_invalid_sequence_does_not_partially_change_dungeon(self):
        initial = {
            "Which to Farm": "Tacet Suppression",
            "Material Selection": "Weapon EXP",
        }
        self._save("ok-ww", WutheringWavesConfig._config_rel_path, initial)
        with self.assertRaises(AssertionError):
            WutheringWavesConfig().set_daily_task("每日任务", "模拟领域", "不存在")
        self.assertEqual(
            self._load("ok-ww", WutheringWavesConfig._config_rel_path), initial
        )
        malformed = {"Which to Farm": "Tacet Suppression", "Material Selection": 1}
        with self.assertRaises(AssertionError):
            WutheringWavesConfig()._update_task(
                malformed, "每日任务", "模拟领域", "Resonator EXP"
            )
        self.assertEqual(
            malformed, {"Which to Farm": "Tacet Suppression", "Material Selection": 1}
        )

    def test_unknown_native_value_displays_without_new_alias(self):
        self._save(
            "ok-ww",
            WutheringWavesConfig._config_rel_path,
            {"Which to Farm": "New Challenge"},
        )
        selection = WutheringWavesConfig()._read_daily_task("每日任务")
        self.assertEqual(selection, ("New Challenge", None))

    def test_nte_roundtrip_preserves_other_tasks_and_fields(self):
        initial, routine = self._nte_files()
        cfg = NTEConfig()
        cfg.set_daily_task("daily_anomaly_hunter", "海囚")
        self.assertEqual(cfg._read_daily_task("daily_anomaly_hunter"), ("海囚", None))
        expected = deepcopy(initial)
        expected["daily_anomaly_hunter"]["追猎目标"] = "海囚"
        self.assertEqual(self._load("ok-nte", cfg._config_rel_path), expected)
        routine["Routine Items"][1]["enabled"] = True
        self.assertEqual(
            self._load("ok-nte", adapters.NTEConfig._routine_config_rel_path), routine
        )
        cfg.set_daily_task("daily_anomaly", "空幕", 3)
        self.assertEqual(cfg._read_daily_task("daily_anomaly"), ("空幕", 3))
        self.assertEqual(cfg._read_daily_task("daily_anomaly_hunter"), ("海囚", None))
        self.assertEqual(
            self._load("ok-nte", adapters.NTEConfig._routine_config_rel_path), routine
        )

    def test_disable_preserves_selection_and_other_tasks_then_can_reenable(self):
        for daily_name, native_id, option, sequence in (
            ("daily_anomaly", "daily_anomaly", "空幕", 3),
            ("daily_anomaly_hunter", "daily_anomaly_hunter", "海囚", None),
        ):
            with self.subTest(daily_name=daily_name):
                initial, routine = self._nte_files()
                routine["Routine Items"][1]["enabled"] = True
                routine_path = adapters.NTEConfig._routine_config_rel_path
                self._save("ok-nte", routine_path, routine)
                service = AppService()
                service.set_task_enabled("ok-nte", daily_name, False)
                cfg = NTEConfig()
                self.assertEqual(cfg._read_task_enabled(daily_name), False)
                saved_config = self._load("ok-nte", cfg._config_rel_path)
                self.assertEqual(saved_config, initial)
                expected = deepcopy(routine)
                for item in expected["Routine Items"]:
                    if item["id"] == native_id:
                        item["enabled"] = False
                self.assertEqual(self._load("ok-nte", routine_path), expected)
                with patch.object(adapters, "save_config") as save:
                    service.set_task_enabled("ok-nte", daily_name, False)
                save.assert_not_called()
                self.assertEqual(
                    self._load("ok-nte", cfg._config_rel_path), saved_config
                )
                rows = service.get_daily_items("ok-nte", load_daily_map()["ok-nte"])
                row = next(row for row in rows if row["name"] == daily_name)
                self.assertEqual(row["selection_label"], "不启用")
                self.assertIn(
                    {"name": "不启用", "options": [], "action": "disable"},
                    row["options"],
                )
                service.set_daily_task("ok-nte", daily_name, option, sequence)
                self.assertEqual(cfg._read_daily_task(daily_name), (option, sequence))
                self.assertEqual(self._load("ok-nte", routine_path), routine)

    def test_both_dailies_can_be_disabled_without_reading_stage_file(self):
        _, routine = self._nte_files()
        routine_path = adapters.NTEConfig._routine_config_rel_path
        for item in routine["Routine Items"][:2]:
            item["enabled"] = False
        self._save("ok-nte", routine_path, routine)
        (self.root / "ok-nte" / NTEConfig._config_rel_path).unlink()
        service = AppService()
        rows = service.get_daily_items("ok-nte", load_daily_map()["ok-nte"])
        self.assertEqual(
            [row["display_name"] for row in rows], ["异象界域", "追猎目标"]
        )
        self.assertEqual([row["selection_label"] for row in rows], ["不启用", "不启用"])
        service.set_task_enabled("ok-nte", "daily_anomaly", False)
        service.set_task_enabled("ok-nte", "daily_anomaly_hunter", False)
        self.assertEqual(self._load("ok-nte", routine_path), routine)

    def test_enabled_task_without_target_is_not_displayed_as_disabled(self):
        _, routine = self._nte_files()
        routine["Routine Items"][1]["enabled"] = True
        self._save("ok-nte", adapters.NTEConfig._routine_config_rel_path, routine)
        self._save("ok-nte", NTEConfig._config_rel_path, {})
        rows = AppService().get_daily_items("ok-nte", load_daily_map()["ok-nte"])
        self.assertEqual(
            [row["selection_label"] for row in rows], ["选择副本", "选择副本"]
        )
        self.assertTrue(all(row["options"] for row in rows))

    def test_missing_routine_target_does_not_save_main_config(self):
        initial, routine = self._nte_files(hunter_present=False)
        for option in ("海囚", "不启用"):
            with (
                self.subTest(option=option),
                self.assertRaisesRegex(AssertionError, "必须唯一包含"),
            ):
                NTEConfig().set_daily_task("daily_anomaly_hunter", option)
        self.assertEqual(self._load("ok-nte", NTEConfig._config_rel_path), initial)
        self.assertEqual(
            self._load("ok-nte", adapters.NTEConfig._routine_config_rel_path),
            routine,
        )

    def test_invalid_selection_or_native_field_never_changes_enable_state(self):
        for daily_name, option, sequence in (
            ("daily_anomaly", "空幕", "3"),
            ("daily_anomaly", "空幕", None),
            ("daily_anomaly_hunter", "不存在", None),
            ("daily_anomaly_hunter", "海囚", 1),
            ("daily_anomaly_hunter", "不启用", 1),
            ("daily_anomaly_hunter", "海囚", None),
        ):
            with self.subTest(daily_name=daily_name, option=option, sequence=sequence):
                initial, routine = self._nte_files()
                initial["daily_anomaly_hunter"]["追猎目标"] = 1
                self._save("ok-nte", NTEConfig._config_rel_path, initial)
                with self.assertRaises(AssertionError):
                    NTEConfig().set_daily_task(daily_name, option, sequence)
                self.assertEqual(
                    self._load("ok-nte", NTEConfig._config_rel_path), initial
                )
                self.assertEqual(
                    self._load("ok-nte", adapters.NTEConfig._routine_config_rel_path),
                    routine,
                )

    def test_nte_reads_each_task_regardless_of_declaration_order(self):
        _, routine = self._nte_files()
        routine["Routine Items"][1]["enabled"] = True
        self._save("ok-nte", adapters.NTEConfig._routine_config_rel_path, routine)
        definitions = deepcopy(load_daily_map()["ok-nte"])
        for definition in definitions:
            definition["options"]["values"].reverse()
        with patch.object(
            NTEConfig,
            "_daily_configs",
            {
                adapters.get_physical_name(definition): definition
                for definition in reversed(definitions)
            },
        ):
            cfg = NTEConfig()
            self.assertEqual(cfg._read_daily_task("daily_anomaly"), ("空幕", 1))
            self.assertEqual(
                cfg._read_daily_task("daily_anomaly_hunter"), ("音霸魔王", None)
            )

    def test_nte_new_daily_only_needs_a_static_declaration(self):
        initial, routine = self._nte_files()
        initial["new_mode"] = {"type": "old", "index": 1}
        routine["Routine Items"].append({"id": "new_mode", "enabled": False})
        self._save("ok-nte", NTEConfig._config_rel_path, initial)
        self._save("ok-nte", adapters.NTEConfig._routine_config_rel_path, routine)
        definition = {
            "display_name": "新日常",
            "type": "daily",
            "allow_disable": True,
            "physical_name": "new_mode",
            "options": {
                "key": "type",
                "values": [
                    {
                        "display_name": "新副本",
                        "physical_name": "new_native",
                        "options": {
                            "key": "index",
                            "values": [{"display_name": "目标", "physical_name": 2}],
                        },
                    }
                ],
            },
        }
        validate_daily_definitions("ok-nte", [definition])
        with patch.object(NTEConfig, "_daily_configs", {"new_mode": definition}):
            cfg = NTEConfig()
            cfg.set_daily_task("new_mode", "新副本", 2)
            self.assertEqual(cfg._read_daily_task("new_mode"), ("新副本", 2))
        expected = {**initial, "new_mode": {"type": "new_native", "index": 2}}
        self.assertEqual(self._load("ok-nte", NTEConfig._config_rel_path), expected)
        routine["Routine Items"][-1]["enabled"] = True
        self.assertEqual(
            self._load("ok-nte", adapters.NTEConfig._routine_config_rel_path), routine
        )

    def test_same_dungeon_name_in_two_dailies_has_independent_binding(self):
        definitions = load_yaml_str(
            "example:\n- display_name: 资源\n  options:\n    key: resource_kind\n    values:\n    - display_name: 材料\n      physical_name: resource_native\n      options:\n        key: resource_target\n        values:\n        - display_name: 目标\n          physical_name: 1\n- display_name: 清理\n  options:\n    key: cleanup_kind\n    values:\n    - display_name: 材料\n      physical_name: cleanup_native\n      options:\n        key: cleanup_target\n        values:\n        - display_name: 目标\n          physical_name: 2\n"
        )["example"]
        validate_daily_definitions("example", definitions)

        class ExampleConfig(ScriptConfig):
            _script_name = "example"
            _config_rel_path = "daily.json"

        cfg = ExampleConfig()
        cfg._daily_configs = {
            adapters.get_physical_name(definition): definition
            for definition in reversed(definitions)
        }
        initial = {"resource_kind": "old", "cleanup_kind": "old", "other": False}
        self._save("example", "daily.json", initial)
        cfg.set_daily_task("清理", "材料", 2)
        cfg.set_daily_task("资源", "材料", 1)
        self.assertEqual(cfg._read_daily_task("资源"), ("材料", 1))
        self.assertEqual(cfg._read_daily_task("清理"), ("材料", 2))
        self.assertEqual(
            self._load("example", "daily.json"),
            {
                "resource_kind": "resource_native",
                "resource_target": 1,
                "cleanup_kind": "cleanup_native",
                "cleanup_target": 2,
                "other": False,
            },
        )


class TestDailyDeclarationValidation(unittest.TestCase):
    def test_rejects_ambiguous_or_invalid_bindings(self):
        valid = {
            "display_name": "A",
            "physical_name": "native",
            "options": {"key": "target"},
        }
        for options in (
            [valid, {**valid, "display_name": "B"}],
            [
                valid,
                {
                    **valid,
                    "display_name": "B",
                    "physical_name": "other",
                    "key": "other_kind",
                },
            ],
            [{"display_name": "A", "options": {"key": "kind"}}],
            [{"display_name": "A", "section": None}],
            [
                {
                    "display_name": "A",
                    "options": {
                        "key": "target",
                        "values": [
                            {"display_name": "一", "physical_name": 1},
                            {"display_name": "另一个一", "physical_name": 1},
                        ],
                    },
                }
            ],
        ):
            with self.subTest(options=options), self.assertRaises(AssertionError):
                definition = {
                    "display_name": "每日",
                    "options": {"key": "kind", "values": options},
                }
                validate_daily_definitions("example", [definition])
                cfg = ScriptConfig()
                cfg._daily_configs = {"每日": definition}
                cfg._update_task({"kind": "old"}, "每日", "A", 1)

    def test_quoted_yaml_values_keep_native_type(self):
        daily = load_yaml_str(
            "example:\n- display_name: 每日\n  options:\n    key: kind\n    values:\n    - display_name: 展示\n      physical_name: native\n      options:\n        key: target\n        values:\n        - display_name: 标签\n          physical_name: native_target\n"
        )["example"]
        validate_daily_definitions("example", daily)
        cfg = ScriptConfig()
        cfg._daily_configs = {"每日": daily[0]}
        config = {"kind": "old", "target": "old_target"}
        cfg._update_task(config, "每日", "展示", "native_target")
        self.assertEqual(config, {"kind": "native", "target": "native_target"})
        self.assertEqual(cfg._read_task(config, "每日"), ("展示", "native_target"))
        self.assertEqual(
            build_task_item(daily[0], ("展示", "native_target"))["selection_label"],
            "展示 · 标签",
        )
        selected = daily[0]["options"]["values"][0]["options"]["values"][0][
            "physical_name"
        ]
        cfg._update_task(config, "每日", "展示", selected)
        self.assertEqual(config["target"], "native_target")

    def test_sequence_type_and_declaration_are_preserved_during_roundtrip(self):
        definition = {
            "display_name": "每日",
            "options": {
                "key": "kind",
                "values": [
                    {
                        "display_name": "材料",
                        "physical_name": "native",
                        "options": {
                            "key": "target",
                            "values": [{"display_name": "第一本", "physical_name": 1}],
                        },
                    }
                ],
            },
        }
        original = deepcopy(definition)
        cfg = ScriptConfig()
        cfg._daily_configs = {"每日": definition}
        config = {"kind": "old", "target": 2, "other": True}
        for sequence in ("1", True):
            with self.subTest(sequence=sequence), self.assertRaises(AssertionError):
                cfg._update_task(config, "每日", "材料", sequence)
            self.assertEqual(config, {"kind": "old", "target": 2, "other": True})
        cfg._update_task(config, "每日", "材料", 1)
        self.assertEqual(cfg._read_task(config, "每日"), ("材料", 1))
        self.assertEqual(definition, original)
        self.assertEqual(
            build_task_item(definition, ("材料", 1))["selection_label"], "材料 · 第一本"
        )
        self.assertEqual(
            build_task_item(definition, ("材料", "1"))["selection_label"], "材料 · 1"
        )
