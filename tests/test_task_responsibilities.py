"""Task 的声明规则、具体任务的原生规则和 service 展示边界。"""

import unittest
from copy import deepcopy
from unittest.mock import patch

from src.config import set_config as adapters
from src.config.set_config import NTEConfig, ScriptConfig
from src.service.app_service import AppService, build_task_item


class TestTaskResponsibilities(unittest.TestCase):
    def test_nte_can_create_selection_fields_without_replacing_other_tasks(self):
        script = NTEConfig()
        config = {"daily_anomaly": {}, "daily_anomaly_hunter": {"追猎目标": "海囚"}}
        other_task = config["daily_anomaly_hunter"]
        self.assertTrue(script._update_daily_task(config, "daily_anomaly", "空幕", 2))
        self.assertEqual(config["daily_anomaly"], {"任务类型": "空幕", "空幕序号": 2})
        self.assertIs(config["daily_anomaly_hunter"], other_task)
        self.assertEqual(other_task, {"追猎目标": "海囚"})
        self.assertFalse(script._update_daily_task(config, "daily_anomaly", "空幕", 2))

    def test_nte_failure_does_not_leave_new_secondary_field_or_enable_task(self):
        script = NTEConfig()
        config = {"daily_anomaly": {"任务类型": 1}}
        routine = {"Routine Items": [{"id": "daily_anomaly", "enabled": False}]}
        original = deepcopy(config)
        with (
            patch.object(script, "_load", side_effect=[routine, config]),
            patch.object(script, "_save") as save,
            self.assertRaisesRegex(AssertionError, "类型不一致"),
        ):
            script.set_daily_task("daily_anomaly", "空幕", 2)
        save.assert_not_called()
        self.assertEqual(config, original)
        self.assertFalse(routine["Routine Items"][0]["enabled"])

    def test_weekly_selection_uses_declared_weekly_file(self):
        script = ScriptConfig()
        script._script_name = "example"
        script._config_rel_path = "main.json"
        script._weekly_config_rel_path = "weekly.json"
        script._weekly_configs = {
            "周本": {
                "display_name": "周本",
                "type": "weekly",
                "options": {
                    "key": "stage",
                    "values": [{"display_name": "目标", "physical_name": "native"}],
                },
            }
        }
        files = {
            path: {"stage": "old", "other": True}
            for path in ("main.json", "weekly.json")
        }

        def save(script_name, path, config):
            self.assertEqual(script_name, "example")
            files[path] = deepcopy(config)

        with (
            patch.object(
                adapters,
                "load_config",
                side_effect=lambda _, path: deepcopy(files[path]),
            ),
            patch.object(adapters, "save_config", side_effect=save),
        ):
            script.set_weekly_task_option("周本", "目标")
            self.assertEqual(script._read_weekly_task("周本"), ("目标", None))
        self.assertEqual(files["weekly.json"], {"stage": "native", "other": True})
        self.assertEqual(files["main.json"], {"stage": "old", "other": True})

    def test_incompatible_fields_rejected_before_mutation_and_readback(self):
        for task_type in ("daily", "weekly"):
            definition = {
                "display_name": "资源",
                "type": task_type,
                "options": {
                    "values": [
                        {
                            "display_name": "A",
                            "options": {
                                "key": "kind",
                                "values": [{"display_name": "一"}],
                            },
                        },
                        {
                            "display_name": "B",
                            "options": {
                                "key": "other",
                                "values": [{"display_name": "二"}],
                            },
                        },
                    ]
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
            config = {"kind": "A", "other": "old"}
            with self.subTest(task_type=task_type):
                with self.assertRaisesRegex(AssertionError, "无法唯一反读"):
                    task._update_selection(config, definition, "B", "二")
                with self.assertRaisesRegex(AssertionError, "无法唯一反读"):
                    task._read_selection_config(config, definition)
                self.assertEqual(config, {"kind": "A", "other": "old"})

    def test_nte_task_value_statically_binds_both_operations(self):
        definition = {
            "display_name": "资源",
            "type": "daily",
            "physical_name": "daily_anomaly",
            "options": {
                "key": "任务类型",
                "values": [
                    {
                        "display_name": "空幕",
                        "options": {
                            "key": "空幕序号",
                            "values": [{"display_name": "目标", "physical_name": 2}],
                        },
                    }
                ],
            },
        }
        script = NTEConfig()
        task = script
        task._daily_configs = {"资源": definition}
        native = {"daily_anomaly": {"任务类型": "old", "空幕序号": 1}}
        routine = {"Routine Items": [{"id": "daily_anomaly", "enabled": True}]}
        with (
            patch.object(
                script,
                "_load",
                side_effect=lambda path=None, **_: (
                    routine if path == task._routine_config_rel_path else native
                ),
            ),
            patch.object(script, "_save"),
        ):
            task.set_daily_task("资源", "空幕", 2)
            self.assertEqual(task._read_daily_task("资源"), ("空幕", 2))
        self.assertEqual(native, {"daily_anomaly": {"任务类型": "空幕", "空幕序号": 2}})

    def test_display_groups_preserve_identity_and_render_existing_alias(self):
        definition = {
            "display_name": "资源",
            "type": "daily",
            "options": {
                "values": [
                    {
                        "display_name": "分类",
                        "options": {
                            "key": "stage",
                            "values": [
                                {"display_name": "友好名称", "physical_name": "native"}
                            ],
                        },
                    }
                ]
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
        native = {"stage": "old"}
        task._update_selection(native, definition, "分类", "native")
        selection = task._read_selection_config(native, definition)
        self.assertEqual(selection, ("分类", "native"))
        self.assertEqual(
            build_task_item(definition, selection)["selection_label"], "友好名称"
        )
        self.assertEqual(native, {"stage": "native"})

    def test_unknown_native_number_is_formatted_only_by_service(self):
        definition = {
            "display_name": "资源",
            "options": {
                "key": "stage",
                "values": [{"display_name": "一", "physical_name": 1}],
            },
        }
        selection = ScriptConfig()._read_selection_config({"stage": 2}, definition)
        self.assertEqual(selection, (2, None))
        self.assertEqual(build_task_item(definition, selection)["selection_label"], "2")

    def test_weekly_popup_uses_same_filtered_options_as_row(self):
        definition = {
            "display_name": "周本",
            "type": "weekly",
            "options": {
                "values": [
                    {"display_name": "A"},
                    {
                        "display_name": "空分类",
                        "options": {"values": []},
                    },
                ]
            },
        }
        service = AppService()
        with (
            patch.object(service, "get_weekly_map", return_value=[definition]),
            patch("src.service.app_service.get_weekly_task", return_value=("A", None)),
        ):
            row = service.get_weekly_items("example")[0]
            popup = service.get_weekly_task_options("example", "周本")
        self.assertEqual(popup, [option["name"] for option in row["options"]])
        self.assertEqual(popup, ["A"])

    def test_missing_resource_keeps_current_native_value_visible(self):
        definition = {
            "display_name": "资源",
            "options": {
                "key": "kind",
                "values": [
                    {
                        "display_name": "材料",
                        "options": {
                            "key": "stage",
                            "values": [],
                        },
                    }
                ],
            },
        }
        row = build_task_item(definition, ("材料", "新副本"))
        self.assertEqual(row["options"], [])
        self.assertEqual(row["selection_label"], "材料 · 新副本")

    def test_unset_native_selection_does_not_pick_first_menu_item(self):
        for task_type in ("daily", "weekly"):
            for definition in (
                {
                    "display_name": "资源",
                    "type": task_type,
                    "options": {"key": "stage", "values": [{"display_name": "A"}]},
                },
                {
                    "display_name": "资源",
                    "type": task_type,
                    "options": {
                        "values": [
                            {
                                "display_name": "分类",
                                "options": {
                                    "key": "stage",
                                    "values": [{"display_name": "A"}],
                                },
                            }
                        ]
                    },
                },
            ):
                with self.subTest(definition=definition):
                    row = build_task_item(definition, (None, None))
                    self.assertEqual(row["selection_label"], "选择副本")
                    self.assertTrue(row["options"])

    def test_display_group_aliases_must_be_unambiguous(self):
        definition = {
            "display_name": "资源",
            "options": {
                "values": [
                    {
                        "display_name": group,
                        "options": {
                            "key": "stage",
                            "values": [
                                {"display_name": group + "别名", "physical_name": 1}
                            ],
                        },
                    }
                    for group in ("A", "B")
                ]
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
        with self.assertRaisesRegex(AssertionError, "无法唯一反读"):
            task._read_selection_config({"stage": 1}, definition)
