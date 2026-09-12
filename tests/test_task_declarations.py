"""统一任务声明、具名周常更新及同步工具的边界。"""

import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from src.config import set_config as adapters
from src.config import task_config
from src.utils.utils_yaml import dump_yaml, load_yaml
from tools import sync_oknte_dungeons, sync_okww_dungeons


class TestTaskDeclarations(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "task_list.yml"
        patcher = patch.object(
            task_config,
            "get_task_list_yml_path_under_root",
            return_value=str(self.path),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_type_filters_preserve_order_names_and_native_keys(self):
        first = {
            "display_name": "资源",
            "type": "daily",
            "options": {"key": "stage", "values": []},
        }
        second = {"display_name": "清理", "type": "daily"}
        weekly = {
            "display_name": "周本",
            "physical_name": "native_weekly",
            "type": "weekly",
            "key": "start_day",
        }
        data = {"example": [first, weekly, second], "daily_only": [first]}
        dump_yaml(str(self.path), data)
        self.assertEqual(task_config.load_task_map(), data)
        self.assertEqual(
            task_config.load_daily_map(),
            {"example": [first, second], "daily_only": [first]},
        )
        self.assertEqual(task_config.load_weekly_map(), {"example": [weekly]})
        self.assertEqual(load_yaml(str(self.path)), data)

    def test_daily_and_weekly_share_one_parse_without_sharing_mutable_data(self):
        daily = {"display_name": "资源", "type": "daily"}
        weekly = {"display_name": "周本", "type": "weekly"}
        data = {"example": [daily, weekly]}
        dump_yaml(str(self.path), data)
        with patch.object(task_config, "load_yaml", wraps=load_yaml) as read:
            first = task_config.load_daily_map()
            first["example"][0]["display_name"] = "改动副本"
            self.assertEqual(task_config.load_daily_map(), {"example": [daily]})
            self.assertEqual(task_config.load_weekly_map(), {"example": [weekly]})
            self.assertEqual(task_config.load_task_map(), data)
        self.assertEqual(read.call_count, 1)

    def test_changed_declaration_is_reloaded_and_revalidated(self):
        dump_yaml(
            str(self.path), {"example": [{"display_name": "甲", "type": "daily"}]}
        )
        task_config.load_task_map()
        updated = {"example": [{"display_name": "改过的任务", "type": "weekly"}]}
        dump_yaml(str(self.path), updated)
        self.assertEqual(task_config.load_task_map(), updated)
        dump_yaml(str(self.path), {"example": [{"display_name": "缺少类型"}]})
        with self.assertRaisesRegex(AssertionError, "type"):
            task_config.load_task_map()

    def test_task_names_are_unique_across_types(self):
        for extra, error in (
            ({"display_name": "资源"}, "任务名重复"),
            ({"display_name": "周本", "physical_name": "资源"}, "任务物理名重复"),
        ):
            data = {
                "example": [
                    {"display_name": "资源", "type": "daily"},
                    {**extra, "type": "weekly"},
                ]
            }
            dump_yaml(str(self.path), data)
            with self.assertRaisesRegex(AssertionError, error):
                task_config.load_task_map()

    def test_type_is_required_and_known(self):
        for extra in ({}, {"type": "monthly"}, {"type": None}, {"period": "daily"}):
            dump_yaml(str(self.path), {"example": [{"display_name": "任务", **extra}]})
            with self.subTest(extra=extra), self.assertRaises(AssertionError):
                task_config.load_task_map()

    def test_multiple_native_weeklies_are_allowed(self):
        tasks = [
            {"display_name": "甲", "physical_name": "a", "type": "weekly"},
            {"display_name": "乙", "physical_name": "b", "type": "weekly"},
        ]
        dump_yaml(str(self.path), {"example": tasks})
        self.assertEqual(task_config.load_weekly_map(), {"example": tasks})

    def test_type_is_independent_of_native_keys(self):
        for kind, load in (
            ("daily", task_config.load_daily_map),
            ("weekly", task_config.load_weekly_map),
        ):
            task = {
                "display_name": "任务",
                "type": kind,
                "key": "same_field",
                "options": {"key": "selection", "values": []},
            }
            dump_yaml(str(self.path), {"example": [task]})
            self.assertEqual(load(), {"example": [task]})

    def test_no_weekly_tasks_does_not_declare_support(self):
        dump_yaml(
            str(self.path),
            {"example": [{"display_name": "资源", "type": "daily"}], "empty": []},
        )
        self.assertEqual(task_config.load_weekly_map(), {})


class TestNamedWeeklyTasks(unittest.TestCase):
    def test_missing_flag_field_does_not_select_date_task(self):
        cfg = adapters.StarRailConfig()
        cfg._weekly_configs = {"货币战争": {"display_name": "货币战争"}}
        with (
            patch.object(cfg, "_load", return_value={"other": True}),
            patch.object(cfg, "_save") as save,
            self.assertRaisesRegex(AssertionError, "key"),
        ):
            cfg.set_weekly_task("货币战争", 4)
        save.assert_not_called()

    def test_echo_of_war_uses_declared_date_field_for_both_entry_points(self):
        cfg = adapters.StarRailConfig()
        cfg._weekly_configs = {
            "历战余响": {"display_name": "历战余响", "key": "custom_start_day"}
        }
        initial = {"custom_start_day": 1, "other": True}
        with (
            patch.object(cfg, "_load", side_effect=lambda **_: deepcopy(initial)),
            patch.object(cfg, "_save") as save,
        ):
            cfg.set_weekly_task("历战余响", 4)
            save.assert_called_once_with({**initial, "custom_start_day": 4})
            save.reset_mock()
            cfg.set_weekly_start_day(5)
            save.assert_called_once_with({**initial, "custom_start_day": 5})

    def test_garden_uses_declared_list_field_and_value(self):
        cfg = adapters.WutheringWavesConfig()
        cfg._weekly_configs = {
            "列表任务": {
                "display_name": "列表任务",
                "key": "custom_list",
                "physical_name": "native_task",
            }
        }
        initial = {"custom_list": ["other"], "unrelated": True}
        with (
            patch.object(cfg, "_load", return_value=initial),
            patch.object(cfg, "_save") as save,
            patch.object(adapters, "is_weekly_start_reached", return_value=True),
        ):
            cfg.set_weekly_task("列表任务", 4)
        save.assert_called_once_with(
            {"custom_list": ["other", "native_task"], "unrelated": True}
        )
        self.assertEqual(initial["custom_list"], ["other"])

    def test_adapter_dispatches_named_weekly_without_updating_other_tasks(self):
        initial = {"currencywars_enable": False, "other": {"count": 7}}
        with (
            patch.object(adapters.StarRailConfig, "_load", return_value=initial),
            patch.object(adapters.StarRailConfig, "_save") as save,
            patch.object(adapters, "is_weekly_start_reached", return_value=True),
        ):
            adapters.set_config(
                "March7th-Launcher", weekly_name="货币战争", weekly_start=4
            )
        save.assert_called_once_with({**initial, "currencywars_enable": True})
        self.assertFalse(initial["currencywars_enable"])

    def test_single_currency_task_does_not_require_or_change_echo_of_war(self):
        cfg = adapters.StarRailConfig()
        initial = {"currencywars_enable": False, "other": {"count": 7}}
        with (
            patch.object(cfg, "_load", return_value=initial),
            patch.object(cfg, "_save") as save,
            patch.object(adapters, "is_weekly_start_reached", return_value=True),
        ):
            cfg.set_weekly_task("货币战争", 4)
        save.assert_called_once_with({**initial, "currencywars_enable": True})
        self.assertFalse(initial["currencywars_enable"])

    def test_single_echo_of_war_does_not_require_currency_flag(self):
        cfg = adapters.StarRailConfig()
        initial = {"echo_of_war_start_day_of_week": 1, "other": {"count": 7}}
        with (
            patch.object(cfg, "_load", return_value=initial),
            patch.object(cfg, "_save") as save,
            patch.object(adapters, "is_weekly_start_reached") as date_check,
        ):
            cfg.set_weekly_task("历战余响", 4)
        save.assert_called_once_with({**initial, "echo_of_war_start_day_of_week": 4})
        date_check.assert_not_called()
        self.assertEqual(initial["echo_of_war_start_day_of_week"], 1)

    def test_unknown_weekly_task_is_rejected_before_loading(self):
        cfg = adapters.StarRailConfig()
        with (
            patch.object(cfg, "_load") as read,
            patch.object(cfg, "_save") as save,
            self.assertRaisesRegex(AssertionError, "未适配的周常"),
        ):
            cfg.set_weekly_task("不存在", 4)
        read.assert_not_called()
        save.assert_not_called()

    def test_star_rail_tasks_are_independent_and_save_once(self):
        definitions = adapters.StarRailConfig._weekly_configs
        initial = {
            "currencywars_enable": False,
            "echo_of_war_start_day_of_week": 1,
            "instance_names": {"历战余响": "已有副本"},
            "other": {"enabled": True},
        }
        for ordered in (definitions, dict(reversed(list(definitions.items())))):
            cfg = adapters.StarRailConfig()
            cfg._weekly_configs = ordered
            with (
                self.subTest(order=list(ordered)),
                patch.object(cfg, "_load", return_value=deepcopy(initial)) as read,
                patch.object(cfg, "_save") as save,
                patch.object(adapters, "is_weekly_start_reached", return_value=True),
            ):
                cfg.set_weekly_tasks(4)
                read.assert_called_once_with()
                save.assert_called_once_with(
                    {
                        **initial,
                        "currencywars_enable": True,
                        "echo_of_war_start_day_of_week": 4,
                    }
                )
                self.assertEqual(read.return_value, initial)

    def test_weekly_without_options_does_not_read_or_write_instance_names(self):
        cfg = adapters.StarRailConfig()
        with patch.object(cfg, "_load") as load, patch.object(cfg, "_save") as save:
            self.assertEqual(cfg._read_weekly_task("货币战争"), (None, None))
            load.assert_not_called()
            with self.assertRaisesRegex(AssertionError, "options.key"):
                cfg.set_weekly_task_option("货币战争", "不应写入")
            save.assert_not_called()

    def test_later_task_failure_does_not_save_or_mutate_loaded_config(self):
        cfg = adapters.StarRailConfig()
        cfg._weekly_configs = dict(reversed(list(cfg._weekly_configs.items())))
        # 日期可更新，但后续开关类型错误；不能保存前一个任务的修改。
        initial = {"currencywars_enable": "invalid", "echo_of_war_start_day_of_week": 1}
        config = deepcopy(initial)
        with (
            patch.object(cfg, "_load", return_value=config),
            patch.object(cfg, "_save") as save,
            patch.object(adapters, "is_weekly_start_reached", return_value=True),
            self.assertRaisesRegex(AssertionError, "类型不一致"),
        ):
            cfg.set_weekly_tasks(4)
        save.assert_not_called()
        self.assertEqual(config, initial)

    def test_multiple_weekly_flags_preserve_unrelated_native_tasks(self):
        cfg = adapters.WutheringWavesConfig()
        field = "Additional Tasks to Run After Daily Task"
        cfg._weekly_configs = {
            "甲": {"display_name": "甲", "key": field, "physical_name": "weekly_a"},
            "乙": {"display_name": "乙", "key": field, "physical_name": "weekly_b"},
        }
        initial = {field: ["other"]}
        with (
            patch.object(cfg, "_load", return_value=initial),
            patch.object(cfg, "_save") as save,
            patch.object(adapters, "is_weekly_start_reached", return_value=True),
        ):
            cfg.set_weekly_tasks(3)
        save.assert_called_once_with({field: ["other", "weekly_a", "weekly_b"]})
        self.assertEqual(initial, {field: ["other"]})

    def test_editing_echo_of_war_does_not_toggle_currency_wars(self):
        cfg = adapters.StarRailConfig()
        initial = {"currencywars_enable": False, "echo_of_war_start_day_of_week": 1}
        with (
            patch.object(cfg, "_load", return_value=deepcopy(initial)),
            patch.object(cfg, "_save") as save,
        ):
            cfg.set_weekly_start_day(5)
        save.assert_called_once_with({**initial, "echo_of_war_start_day_of_week": 5})


class TestTaskSyncIsolation(unittest.TestCase):
    def test_sync_preserves_weeklies_other_dailies_and_other_scripts(self):
        for module, script, daily_name, category in (
            (sync_okww_dungeons, "ok-ww", "每日任务", "凝素领域"),
            (sync_oknte_dungeons, "ok-nte", "daily_anomaly", "空幕"),
        ):
            tasks = [
                {
                    "display_name": "额外日常",
                    "type": "daily",
                    "options": {"values": []},
                },
                {
                    "display_name": daily_name,
                    "type": "daily",
                    "options": {
                        "values": [
                            {
                                "display_name": category,
                                "options": {
                                    "values": [
                                        {"display_name": "旧本", "physical_name": 1}
                                    ]
                                },
                            }
                        ]
                    },
                },
            ]
            tasks.append(
                {"display_name": "周本", "type": "weekly", "key": "weekly_flag"}
            )
            other = [{"display_name": "任务", "type": "daily"}]
            original = {script: tasks, "other_script": other}
            with tempfile.TemporaryDirectory() as tmp, self.subTest(script=script):
                path = str(Path(tmp) / "task_list.yml")
                dump_yaml(path, original)
                with patch.object(module, "_DUNGEON_PATH", path):
                    if module is sync_okww_dungeons:
                        module._apply_new({category: 2}, {category: [1]})
                    else:
                        module._apply_numeric({category: 2})
                result = load_yaml(path)
                self.assertEqual(result[script][2], tasks[2])
                self.assertEqual(result[script][:1], tasks[:1])
                self.assertEqual(result["other_script"], other)
                options = result[script][1]["options"]["values"][0]["options"]["values"]
                self.assertEqual([item["physical_name"] for item in options], [1, 2])
