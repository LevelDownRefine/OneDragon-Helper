"""脚本声明加载、注册绑定及菜单数据隔离。"""

import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from src.config import set_config as adapters
from src.config import task_config
from src.service.app_service import get_daily_map
from src.utils.utils_yaml import dump_yaml


class TestAdapterDeclarations(unittest.TestCase):
    def test_registration_and_service_use_physical_identity_when_display_changes(self):
        from src.service.app_service import AppService

        self.dailies[0]["physical_name"] = "native_daily"
        for display in ("资源", "改过的展示名"):
            self.dailies[0]["display_name"] = display
            cls = self._register(self.definition)
            self.assertEqual(list(cls._daily_configs), ["native_daily", "清理"])
            self.assertIn("native_daily", cls._daily_configs)
            with patch(
                "src.service.app_service.get_daily_task", return_value=("金币", None)
            ) as read:
                rows = AppService().get_daily_items("example", self.dailies)
            self.assertEqual(read.call_args_list[0].args, ("example", "native_daily"))
            self.assertEqual(rows[0]["name"], "native_daily")
            self.assertEqual(rows[0]["display_name"], display)
            self.assertEqual(rows[1]["name"], "清理")
            with self.assertRaisesRegex(AssertionError, "未适配"):
                cls()._read_daily_task(display)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "config").mkdir()
        self.path = self.root / "config/script_adapters.yml"
        self.dungeon_path = self.root / "config/task_list.yml"
        self.definition = {
            "display_name": "示例",
            "config_path": "settings/daily.json",
            "backup_paths": ["settings", "extra.json"],
        }
        self.dailies = [
            {
                "display_name": "资源",
                "type": "daily",
                "options": {"key": "resource_stage", "values": []},
            },
            {
                "display_name": "清理",
                "type": "daily",
                "options": {"key": "cleanup_stage", "values": []},
            },
        ]

    def _load_dungeons(self):
        dump_yaml(str(self.dungeon_path), {"example": self.dailies})
        with patch.object(
            task_config,
            "get_task_list_yml_path_under_root",
            return_value=str(self.dungeon_path),
        ):
            return task_config.load_daily_map()

    def _register(self, definition):
        options = self._load_dungeons()
        attrs = {
            "_script_name": "example",
            "display_name": definition["display_name"],
            "_config_rel_path": definition["config_path"],
            "_backup_paths": tuple(definition["backup_paths"]),
        }
        for key, attr in (
            ("game_config_path", "_game_config_rel_path"),
            ("game_path_keys", "_game_path_keys"),
            ("template_path", "_template_rel_path"),
            ("weekly_config_path", "_weekly_config_rel_path"),
            ("background", "background"),
        ):
            if key in definition:
                attrs[attr] = (
                    tuple(definition[key])
                    if key == "game_path_keys"
                    else definition[key]
                )
        cls = type("Example", (adapters.ScriptConfig,), attrs)
        with (
            patch.object(adapters, "load_daily_map", return_value=options),
            patch.dict(adapters._CONFIGS),
        ):
            return adapters.register(cls)

    def test_minimal_declaration_binds_fields_and_optional_defaults(self):
        cls = self._register(self.definition)
        self.assertEqual(cls.display_name, "示例")
        self.assertEqual(cls._config_rel_path, "settings/daily.json")
        self.assertEqual(cls._backup_paths, ("settings", "extra.json"))
        self.assertEqual(
            {
                name: daily["options"]["key"]
                for name, daily in cls._daily_configs.items()
            },
            {"资源": "resource_stage", "清理": "cleanup_stage"},
        )
        self.assertEqual(cls._game_path_keys, ())
        for attr in (
            "_game_config_rel_path",
            "_template_rel_path",
            "_weekly_config_rel_path",
            "background",
        ):
            self.assertEqual(getattr(cls, attr), "")

    def test_registration_copies_raw_declarations_without_sharing_mutations(self):
        cls = self._register(self.definition)
        self.assertEqual(list(cls._daily_configs.values()), self.dailies)
        cls._daily_configs["资源"]["options"]["values"].append({"display_name": "金币"})
        self.assertEqual(self.dailies[0]["options"]["values"], [])
        other = self._register(self.definition)
        self.assertEqual(other._daily_configs["资源"]["options"]["values"], [])

    def test_shared_task_entry_requires_unique_physical_names_across_files(self):
        self.dailies[0]["physical_name"] = "native_task"
        with (
            patch.object(
                adapters,
                "load_weekly_map",
                return_value={
                    "example": [
                        {"display_name": "周常别名", "physical_name": "native_task"}
                    ]
                },
            ),
            self.assertRaisesRegex(AssertionError, "任务物理名重复"),
        ):
            self._register(self.definition)

    def test_registration_preserves_script_capabilities(self):
        cls = self._register(
            {
                **self.definition,
                "game_config_path": "settings/game.json",
                "game_path_keys": ["launcher", "exe"],
                "template_path": "example.json",
                "weekly_config_path": "settings/weekly.json",
                "background": "assets/bg.webp",
            }
        )
        self.assertEqual(cls._game_config_rel_path, "settings/game.json")
        self.assertEqual(cls._game_path_keys, ("launcher", "exe"))
        self.assertEqual(cls._template_rel_path, "example.json")
        self.assertEqual(cls._weekly_config_rel_path, "settings/weekly.json")
        self.assertEqual(cls.background, "assets/bg.webp")

    def test_registration_requires_explicit_script_environment(self):
        attrs = {
            "_script_name": "example",
            "_config_rel_path": "daily.json",
            "_backup_paths": ("daily.json",),
        }
        for key in attrs:
            missing = dict(attrs)
            del missing[key]
            cls = type("Missing", (adapters.ScriptConfig,), missing)
            with self.subTest(key=key), self.assertRaisesRegex(AssertionError, key):
                adapters.register(cls)
        cls = type(
            "MissingGameConfig",
            (adapters.ScriptConfig,),
            {**attrs, "_game_path_keys": ("exe",)},
        )
        with self.assertRaisesRegex(AssertionError, "_game_config_rel_path"):
            adapters.register(cls)

    def test_custom_daily_can_omit_simple_field(self):
        del self.dailies[1]["options"]["key"]
        cls = self._register(self.definition)
        self.assertEqual(
            cls._daily_configs["资源"]["options"]["key"],
            "resource_stage",
        )
        self.assertNotIn("value_field", cls._daily_configs["清理"])

    def test_daily_schema_is_validated_in_dungeon_file(self):
        for bad in (
            [
                {
                    "display_name": "资源",
                    "type": "daily",
                    "options": {"key": 1, "values": []},
                }
            ],
            [{"display_name": "资源", "options": {"values": {}}}],
            [self.dailies[0], self.dailies[0]],
            {"daily": self.dailies},
        ):
            with self.subTest(bad=bad), self.assertRaises(AssertionError):
                self.dailies = bad
                self._load_dungeons()

    def test_task_loading_does_not_require_script_environment_file(self):
        expected = {"example": self.dailies}
        self.assertEqual(self._load_dungeons(), expected)
        self.assertFalse(self.path.exists())

    def test_register_requires_a_matching_declaration(self):
        cls = type(
            "Unknown",
            (adapters.ScriptConfig,),
            {
                "_script_name": "unknown",
                "_config_rel_path": "daily.json",
                "_backup_paths": ("daily.json",),
            },
        )
        with self.assertRaisesRegex(AssertionError, "缺少日常声明"):
            adapters.register(cls)

    def test_menu_extraction_does_not_mutate_shared_declarations(self):
        data = self._load_dungeons()
        original = deepcopy(data)
        with patch("src.service.app_service.load_daily_map", return_value=data):
            menu = get_daily_map()
        self.assertEqual(menu, {"example": self.dailies})
        menu["example"][0]["options"]["values"].append({"display_name": "金币"})
        self.assertEqual(data, original)

    def test_shipped_declarations_and_registered_adapters_match(self):
        self.assertEqual(set(task_config.load_daily_map()), set(adapters._CONFIGS))
