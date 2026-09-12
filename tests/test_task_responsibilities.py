"""Task 的声明规则、具体任务的原生规则和 service 展示边界。"""

import unittest
from copy import deepcopy
from unittest.mock import patch

from src.config import set_config as adapters
from src.config.set_config import ArknightsConfig, NTEConfig, ScriptConfig
from src.service.app_service import AppService, build_task_item


class TestTaskResponsibilities(unittest.TestCase):
    def test_unadapted_weekly_selection_never_calls_daily_hooks(self):
        for script_type in (ScriptConfig, NTEConfig, ArknightsConfig):
            with (
                self.subTest(script_type=script_type),
                patch.dict(adapters._CONFIGS, {"example": script_type}),
                patch.object(script_type, "_update_daily_task") as update,
                patch.object(script_type, "_load") as load,
                patch.object(script_type, "_save") as save,
            ):
                adapters.set_weekly_task_option("example", "周本", "新本")
                self.assertEqual(
                    adapters.get_weekly_task("example", "周本"), (None, None)
                )
                update.assert_not_called()
                load.assert_not_called()
                save.assert_not_called()

    def test_daily_lookup_cannot_resolve_a_weekly_name(self):
        for script_type in (ScriptConfig, NTEConfig, ArknightsConfig):
            script = script_type()
            script._weekly_configs = {
                "独立周常": {
                    "display_name": "独立周常",
                    "options": {"key": "stage", "values": [{"display_name": "新本"}]},
                }
            }
            config = {"stage": "old"}
            with self.subTest(script_type=script_type):
                with self.assertRaisesRegex(AssertionError, "未适配的日常"):
                    script._update_daily_task(config, "独立周常", "新本")
                with self.assertRaisesRegex(AssertionError, "未适配的日常"):
                    script._read_daily_config(config, "独立周常")
                self.assertEqual(config, {"stage": "old"})

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

    def test_daily_selection_does_not_use_weekly_file(self):
        script = ScriptConfig()
        script._script_name = "example"
        script._config_rel_path = "main.json"
        script._weekly_config_rel_path = "weekly.json"
        script._daily_configs = {
            "周本": {
                "display_name": "周本",
                "type": "daily",
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
            script.set_daily_task("周本", "目标")
            self.assertEqual(script._read_daily_task("周本"), ("目标", None))
        self.assertEqual(files["main.json"], {"stage": "native", "other": True})
        self.assertEqual(files["weekly.json"], {"stage": "old", "other": True})

    def test_incompatible_fields_rejected_before_mutation_and_readback(self):
        definition = {
            "display_name": "资源",
            "type": "daily",
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
        task._daily_configs = {"资源": definition}
        config = {"kind": "A", "other": "old"}
        with self.assertRaisesRegex(AssertionError, "无法唯一反读"):
            task._update_daily_task(config, "资源", "B", "二")
        with self.assertRaisesRegex(AssertionError, "无法唯一反读"):
            task._read_daily_config(config, "资源")
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
        task._daily_configs = {"资源": definition}
        native = {"stage": "old"}
        task._update_daily_task(native, "资源", "分类", "native")
        selection = task._read_daily_config(native, "资源")
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
        task = ScriptConfig()
        task._daily_configs = {"资源": definition}
        selection = task._read_daily_config({"stage": 2}, "资源")
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
        task._daily_configs = {"资源": definition}
        with self.assertRaisesRegex(AssertionError, "无法唯一反读"):
            task._read_daily_config({"stage": 1}, "资源")
