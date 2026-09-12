"""共用声明结构与具名日常的读写契约。"""

import unittest
from copy import deepcopy
from unittest.mock import patch

from src.config.set_config import ArknightsConfig, ScriptConfig
from src.config.task_config import (
    get_options,
    validate_daily_definitions,
    validate_weekly_definitions,
)
from src.service.app_service import AppService, build_task_item


class TestTaskLevels(unittest.TestCase):
    def test_maa_display_aliases_do_not_change_stages_or_fallback(self):
        script = ArknightsConfig()
        task = script
        task._daily_configs = dict(task._daily_configs)
        task._daily_configs["每日任务"] = deepcopy(task._daily_configs["每日任务"])
        for option in task._daily_configs["每日任务"]["options"]["values"]:
            option["display_name"] = "新" + option["display_name"]
        queue = [
            {"$type": "FightTask", "StagePlan": [stage], "IsEnable": False}
            for stage in ("Annihilation", "AP-5", "LS-6", "CE-6", "1-7")
        ]
        config = {"Configurations": {"Default": {"TaskQueue": queue}}}
        task._update_daily_task(config, "每日任务", "新红票")
        self.assertEqual(
            [entry["IsEnable"] for entry in queue], [True, True, False, False, True]
        )
        with patch.object(script, "_load", return_value=config):
            self.assertEqual(task._read_daily_task("每日任务"), ("新红票", None))
            task._update_daily_task(config, "每日任务", "新土")
            self.assertEqual(task._read_daily_task("每日任务"), ("新土", None))

    def test_single_level_daily_uses_physical_values_or_display_fallback(self):
        for option, old_value in (
            ({"display_name": "金币"}, "old"),
            ({"display_name": "金币", "physical_name": "gold"}, "old"),
            ({"display_name": "金币", "physical_name": 2}, 1),
        ):
            with self.subTest(option=option):
                definition = {
                    "display_name": "资源",
                    "type": "daily",
                    "options": {"key": "stage", "values": [option]},
                }
                validate_daily_definitions("example", [definition])
                task = ScriptConfig()
                task._daily_configs = {"资源": definition}
                config = {"stage": old_value, "other": True}
                task._update_daily_task(config, "资源", "金币")
                expected = option.get("physical_name", "金币")
                self.assertEqual(config, {"stage": expected, "other": True})
                self.assertEqual(
                    task._read_daily_config(config, "资源"), ("金币", None)
                )
                self.assertFalse(task._update_daily_task(config, "资源", "金币"))
                with self.assertRaisesRegex(AssertionError, "不支持 sequence"):
                    task._update_daily_task(config, "资源", "金币", 1)

    def test_option_named_disable_is_an_ordinary_selection(self):
        definition = {
            "display_name": "资源",
            "type": "daily",
            "options": {
                "key": "stage",
                "values": [{"display_name": "不启用", "physical_name": "native_stage"}],
            },
        }
        task = ScriptConfig()
        setattr(
            task,
            "_weekly_configs"
            if definition.get("type", "daily") == "weekly"
            else "_daily_configs",
            {"资源": definition},
        )
        config = {"stage": "old"}
        task._update_daily_task(config, "资源", "不启用")
        self.assertEqual(config, {"stage": "native_stage"})
        service = AppService()
        with patch(
            "src.service.app_service.get_daily_task",
            return_value=task._read_daily_config(config, "资源"),
        ):
            row = service.get_daily_items("example", [definition])[0]
        self.assertNotIn("action", row["options"][0])

    def definition(self, task_type):
        return {
            "display_name": "资源",
            "type": task_type,
            "options": {
                "key": "kind",
                "values": [
                    {
                        "display_name": "材料",
                        "physical_name": "native",
                        "options": {
                            "key": "target",
                            "values": [{"display_name": "高级", "physical_name": 2}],
                        },
                    }
                ],
            },
        }

    def test_daily_nested_roundtrip_preserves_declaration_and_other_settings(self):
        definition = self.definition("daily")
        original = deepcopy(definition)
        validate_daily_definitions("example", [definition])
        script = ScriptConfig()
        script._daily_configs = {"资源": definition}
        config = {"kind": "old", "target": 1, "other": True}
        with (
            patch.object(script, "_load", return_value=config),
            patch.object(script, "_save") as save,
        ):
            script.set_daily_task("资源", "材料", 2)
            self.assertEqual(script._read_daily_task("资源"), ("材料", 2))
            script.set_daily_task("资源", "材料", 2)
        save.assert_called_once_with({"kind": "native", "target": 2, "other": True})
        self.assertEqual(definition, original)

    def test_each_list_owns_its_field_without_inheritance(self):
        definition = self.definition("daily")
        original = deepcopy(definition)
        parent = get_options(definition)[0]
        self.assertEqual(definition["options"]["key"], "kind")
        self.assertEqual(parent["options"]["key"], "target")
        self.assertNotIn("options", get_options(parent)[0])
        parent["options"]["key"] = "custom"
        self.assertEqual(definition, original)

    def test_invalid_child_binding_does_not_partially_update_parent(self):
        for missing_binding in (True, False):
            with self.subTest(missing_binding=missing_binding):
                definition = self.definition("daily")
                if missing_binding:
                    del definition["options"]["values"][0]["options"]["key"]
                task = ScriptConfig()
                task._daily_configs = {"资源": definition}
                config = {"kind": "old", "target": "wrong type"}
                original = deepcopy(config)
                with (
                    patch.object(task, "_load", return_value=config),
                    patch.object(task, "_save") as save,
                    self.assertRaises(AssertionError),
                ):
                    task.set_daily_task("资源", "材料", 2)
                save.assert_not_called()
                self.assertEqual(config, original)

    def test_inherited_and_explicit_routes_cannot_alias_same_native_value(self):
        definition = {
            "display_name": "资源",
            "options": {
                "key": "stage",
                "values": [
                    {"display_name": "A", "physical_name": 1},
                    {"display_name": "B", "physical_name": 1},
                ],
            },
        }
        for validate in (validate_daily_definitions, validate_weekly_definitions):
            with self.assertRaisesRegex(AssertionError, "无法唯一反读"):
                validate("example", [definition])

    def test_recursive_schema_is_independent_of_current_selection_depth(self):
        for task_type, validate in (
            ("daily", validate_daily_definitions),
            ("weekly", validate_weekly_definitions),
        ):
            definition = self.definition(task_type)
            definition["options"]["values"][0]["options"]["values"][0]["options"] = {
                "key": "third",
                "values": [
                    {
                        "display_name": "第三层",
                        "options": {"source": {"path": "fourth.json"}, "key": "fourth"},
                    }
                ],
            }
            validate("example", [definition])
            task = ScriptConfig()
            setattr(
                task,
                "_weekly_configs"
                if definition.get("type", "daily") == "weekly"
                else "_daily_configs",
                {"资源": definition},
            )
            if task_type == "daily":
                config = {"kind": "old", "target": 1}
                with self.assertRaisesRegex(AssertionError, "两层"):
                    task._update_daily_task(config, "资源", "材料", 2)
                self.assertEqual(config, {"kind": "old", "target": 1})
                with self.assertRaisesRegex(AssertionError, "两层"):
                    task._read_daily_config(config, "资源")
            with self.assertRaisesRegex(AssertionError, "两层"):
                build_task_item(definition, ("材料", 2))

    def test_child_native_values_must_identify_one_option(self):
        definition = self.definition("weekly")
        definition["options"]["values"][0]["options"]["values"].append(
            {"display_name": "另一目标", "physical_name": 2}
        )
        with self.assertRaisesRegex(AssertionError, "无法唯一反读"):
            validate_weekly_definitions("example", [definition])

    def test_weekly_menu_preserves_nested_native_values(self):
        service = AppService()
        definition = self.definition("weekly")
        with (
            patch.object(service, "get_weekly_map", return_value=[definition]),
            patch("src.service.app_service.get_weekly_task", return_value=("材料", 2)),
        ):
            row = service.get_weekly_items("example")[0]
        self.assertEqual(row["selection_label"], "材料 · 高级")
        self.assertEqual(
            row["options"],
            [
                {
                    "name": "材料",
                    "options": [{"name": "高级", "value": 2}],
                }
            ],
        )
        with patch("src.service.app_service.set_weekly_task_option") as write:
            service.set_weekly_task_option("example", "资源", "材料", 2)
        write.assert_called_once_with("example", "资源", "材料", 2)
