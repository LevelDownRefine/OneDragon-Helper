"""周常声明驱动原生任务写入，展示名和排列顺序不参与定位。"""

import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from src.config import set_config as adapters
from src.config import task_config
from src.service.app_service import get_weekly_map
from src.utils.utils_yaml import dump_yaml


class TestWeeklyBindings(unittest.TestCase):
    def test_weekly_display_alias_does_not_change_native_task_or_menu_identity(self):
        from src.service.app_service import AppService

        definitions = [
            {
                "display_name": "改过的周本名",
                "physical_name": "历战余响",
                "key": "echo_of_war_start_day_of_week",
                "options": {
                    "values": [
                        {"display_name": "别名", "physical_name": "native_stage"}
                    ]
                },
            }
        ]
        cls = self._register(adapters.StarRailConfig, definitions)
        self.assertEqual(list(cls._weekly_configs), ["历战余响"])
        config = {"instance_names": {"历战余响": "old", "other": "keep"}}
        with (
            patch.dict(adapters._CONFIGS, {"example": cls}),
            patch.object(cls, "_load", side_effect=lambda **_: deepcopy(config)),
            patch.object(cls, "_save", side_effect=config.update),
        ):
            service = AppService()
            service.set_weekly_task_option("example", "历战余响", "别名")
            self.assertEqual(
                config["instance_names"], {"历战余响": "native_stage", "other": "keep"}
            )
            row = service.get_weekly_items("example")[0]
            self.assertEqual(row["name"], "历战余响")
            self.assertEqual(row["display_name"], "改过的周本名")
            self.assertEqual(row["selection_label"], "别名")
            self.assertEqual(
                service.get_weekly_task_options("example", "历战余响"), ["别名"]
            )

    def test_weekly_alias_roundtrip_preserves_other_native_settings(self):
        for value in ("native_stage", 2):
            cls = type(
                "ExampleWeekly",
                (adapters.StarRailConfig,),
                {
                    "_script_name": "example",
                    "_weekly_configs": {
                        "历战余响": {
                            "display_name": "历战余响",
                            "options": {
                                "values": [
                                    {"display_name": "别名", "physical_name": value},
                                    {"display_name": "原生名"},
                                ]
                            },
                        }
                    },
                },
            )
            config = {"instance_names": {"其他任务": "other"}, "other": True}
            with (
                self.subTest(value=value),
                patch.dict(adapters._CONFIGS, {"example": cls}),
                patch.object(
                    cls,
                    "_load",
                    side_effect=lambda snapshot=config, **_: deepcopy(snapshot),
                ),
                patch.object(cls, "_save", side_effect=config.update),
            ):
                adapters.set_weekly_task_option("example", "历战余响", "别名")
                self.assertEqual(config["instance_names"]["历战余响"], value)
                self.assertEqual(
                    adapters.get_weekly_task("example", "历战余响"), ("别名", None)
                )
                adapters.set_weekly_task_option("example", "历战余响", "原生名")
                self.assertEqual(
                    adapters.get_weekly_task("example", "历战余响"), ("原生名", None)
                )
                config["instance_names"]["历战余响"] = "未维护的新副本"
                self.assertEqual(
                    adapters.get_weekly_task("example", "历战余响"),
                    ("未维护的新副本", None),
                )
            self.assertEqual(config["instance_names"]["其他任务"], "other")
            self.assertTrue(config["other"])

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

    def _load(self, definitions):
        if isinstance(definitions, list):
            definitions = [
                {**task, "type": "weekly"} if isinstance(task, dict) else task
                for task in definitions
            ]
        dump_yaml(str(self.path), {"example": definitions})
        return task_config.load_weekly_map()

    def _register(self, parent, definitions):
        self._load(definitions)
        cls = type(
            "ExampleWeekly",
            (parent,),
            {
                "_script_name": "example",
                "_config_rel_path": "settings.json",
                "_backup_paths": ("settings.json",),
                "_game_config_rel_path": parent._game_config_rel_path,
            },
        )
        with (
            patch.object(adapters, "load_daily_map", return_value={"example": []}),
            patch.dict(adapters._CONFIGS),
        ):
            return adapters.register(cls)

    def test_malformed_declarations_fail_at_load(self):
        for definitions in (
            {},
            ["周常"],
            [{}],
            [{"display_name": " "}],
            [{"display_name": "周常"}, {"display_name": "周常"}],
            [{"display_name": "周常", "key": ""}],
            [{"display_name": "周常", "key": True}],
            [{"display_name": "周常", "physical_name": ""}],
            [{"display_name": "周常", "physical_name": True}],
            [{"display_name": "周常", "task": "obsolete"}],
            [{"display_name": "周常", "task_name": "typo"}],
            [{"display_name": "周常", "options": {"source": 1}}],
            [{"display_name": "周常", "options": {"values": "副本"}}],
            [{"display_name": "周常", "options": {"values": [1]}}],
        ):
            with (
                self.subTest(definitions=definitions),
                self.assertRaises(AssertionError),
            ):
                self._load(definitions)

    def test_custom_task_ids_drive_all_native_writers_in_any_order(self):
        additional_tasks = "Additional Tasks to Run After Daily Task"
        cases = (
            (
                adapters.WutheringWavesConfig,
                {additional_tasks: ["other"]},
                {additional_tasks: ["other", "new_task"]},
            ),
            (
                adapters.EndfieldConfig,
                {"new_task": True, "other": 7},
                {"new_task": False, "other": 7},
            ),
            (
                adapters.ZenlessZoneZeroConfig,
                {
                    "app_list": [
                        {"app_id": "other", "enabled": False},
                        {"app_id": "new_task", "enabled": False},
                    ]
                },
                {
                    "app_list": [
                        {"app_id": "other", "enabled": False},
                        {"app_id": "new_task", "enabled": True},
                    ]
                },
            ),
            (
                adapters.StarRailConfig,
                {"new_task": False, "echo_of_war_start_day_of_week": 1, "other": 7},
                {"new_task": True, "echo_of_war_start_day_of_week": 4, "other": 7},
            ),
        )
        for parent, original, expected in cases:
            if parent is adapters.WutheringWavesConfig:
                binding = {"key": additional_tasks, "physical_name": "new_task"}
            elif parent is adapters.ZenlessZoneZeroConfig:
                binding = {"physical_name": "new_task"}
            else:
                binding = {"key": "new_task"}
            definitions = [{"display_name": "改过展示名", **binding}]
            if parent is adapters.StarRailConfig:
                definitions.insert(
                    0,
                    {
                        "display_name": "历战余响",
                        "key": "echo_of_war_start_day_of_week",
                    },
                )
            for ordered in (definitions, list(reversed(definitions))):
                with self.subTest(parent=parent.__name__, order=ordered):
                    cls = self._register(parent, ordered)
                    config = deepcopy(original)
                    with (
                        patch.object(cls, "_load", return_value=config),
                        patch.object(cls, "_load_weekly", return_value=config),
                        patch.object(cls, "_save") as save,
                        patch.object(cls, "_save_weekly") as save_weekly,
                        patch.object(
                            adapters, "is_weekly_start_reached", return_value=True
                        ),
                    ):
                        cls().set_weekly_tasks(4)
                    self.assertEqual(config, original)
                    saved = save if save.called else save_weekly
                    self.assertEqual(saved.call_args.args[0], expected)
                    self.assertEqual(save.call_count + save_weekly.call_count, 1)

    def test_maa_without_task_still_supports_weekly(self):
        cls = self._register(adapters.ArknightsConfig, [{"display_name": "理智药剂"}])
        with patch.dict(adapters._CONFIGS, {"example": cls}):
            self.assertTrue(adapters.supports_weekly("example"))
        self.assertIn("理智药剂", cls._weekly_configs)

    def test_empty_declaration_clears_inherited_weekly_support(self):
        cls = self._register(adapters.WutheringWavesConfig, [])
        with patch.dict(adapters._CONFIGS, {"example": cls}):
            self.assertFalse(adapters.supports_weekly("example"))
        with (
            patch.object(cls, "_load") as load,
            self.assertRaisesRegex(AssertionError, "未支持周常配置"),
        ):
            cls().set_weekly_tasks(4)
        load.assert_not_called()

    def test_declaring_weekly_requires_writer_even_without_task(self):
        with self.assertRaisesRegex(AssertionError, "必须实现.*weekly_task"):
            self._register(adapters.ScriptConfig, [{"display_name": "周常"}])

    def test_menu_expansion_does_not_change_shared_definitions(self):
        definitions = self._load(
            [
                {
                    "display_name": "周本",
                    "options": {
                        "source": {"path": "stages.json", "category": "weekly"}
                    },
                }
            ]
        )
        original = deepcopy(definitions)
        with (
            patch("src.service.app_service.load_weekly_map", return_value=definitions),
            patch("src.service.app_service.get_task_options", return_value=["A"]),
        ):
            menu = get_weekly_map("example")
        self.assertEqual(menu[0]["options"]["values"], [{"display_name": "A"}])
        menu[0]["physical_name"] = "changed"
        self.assertEqual(definitions, original)
