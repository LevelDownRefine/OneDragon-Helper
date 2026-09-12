"""声明中的字段、物理名、别名接入原有子类读写流程。"""

import importlib.util
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from src.config import task_config
from src.config.set_config import ArknightsConfig, NTEConfig, WutheringWavesConfig


class TestDeclarationBindings(unittest.TestCase):
    def setUp(self):
        self.daily = task_config.load_daily_map()
        self.weekly = task_config.load_weekly_map()

    def load_adapters(self):
        """隔离注册表，验证类属性在声明改变后仍绑定到正确字段。"""
        spec = importlib.util.spec_from_file_location(
            "declaration_test_adapters",
            Path(task_config.__file__).with_name("set_config.py"),
        )
        module = importlib.util.module_from_spec(spec)
        daily_patch = patch.object(
            task_config, "load_daily_map", return_value=self.daily
        )
        weekly_patch = patch.object(
            task_config, "load_weekly_map", return_value=self.weekly
        )
        daily_patch.start()
        weekly_patch.start()
        self.addCleanup(daily_patch.stop)
        self.addCleanup(weekly_patch.stop)
        spec.loader.exec_module(module)
        return module

    def test_wuwa_fields_and_values_come_from_declarations(self):
        task = self.daily["ok-ww"][0]
        task["options"]["key"] = "NativeCategory"
        task["options"]["values"] = [
            {
                "display_name": "测试类别",
                "physical_name": "NativeCategoryValue",
                "options": {
                    "key": "NativeStage",
                    "values": [{"display_name": "测试目标", "physical_name": 9}],
                },
            }
        ]
        cfg = self.load_adapters().WutheringWavesConfig()
        config = {"NativeCategory": "old", "NativeStage": 1, "unrelated": [1, 2]}
        original = deepcopy(config)
        with (
            patch.object(cfg, "_load", return_value=config),
            patch.object(cfg, "_save") as save,
        ):
            cfg.set_dungeon("测试类别", 9)
            self.assertEqual(cfg._read_dungeon(), ("测试类别", 9))
        self.assertEqual(
            config,
            {**original, "NativeCategory": "NativeCategoryValue", "NativeStage": 9},
        )
        save.assert_called_once_with(config)

    def test_display_only_categories_share_declared_field(self):
        for script in ("BetterGI", "ok-ef"):
            for option in self.daily[script][0]["options"]["values"]:
                option["options"]["key"] = "NativeTarget"
        adapters = self.load_adapters()
        for cls in (adapters.GenshinConfig, adapters.EndfieldConfig):
            with self.subTest(cls=cls.__name__):
                cfg = cls()
                config = {"NativeTarget": "old", "untouched": True}
                with (
                    patch.object(cfg, "_load", return_value=config),
                    patch.object(cfg, "_save"),
                ):
                    cfg.set_dungeon("只供展示的类别", "真实副本")
                    self.assertEqual(cfg._read_dungeon(), ("真实副本", None))
                self.assertEqual(
                    config, {"NativeTarget": "真实副本", "untouched": True}
                )

    def test_nte_modes_remain_exclusive_with_declared_native_names(self):
        anomaly, hunter = self.daily["ok-nte"]
        anomaly["physical_name"] = "native_anomaly"
        anomaly["options"]["key"] = "NativeType"
        anomaly["options"]["values"][0]["physical_name"] = "NativeCategory"
        anomaly["options"]["values"][0]["options"]["key"] = "NativeSequence"
        hunter["physical_name"] = "native_hunter"
        hunter["options"]["key"] = "NativeBoss"
        self.daily["ok-nte"].reverse()
        cfg = self.load_adapters().NTEConfig()
        config = {
            "native_anomaly": {"NativeType": "old", "NativeSequence": 1},
            "native_hunter": {"NativeBoss": "old"},
        }
        routine = {
            "Routine Items": [
                {"id": "native_anomaly", "enabled": False},
                {"id": "native_hunter", "enabled": True},
                {"id": "unrelated", "enabled": True},
            ]
        }

        def load(path=None, **kwargs):
            return routine if path == cfg._routine_config_rel_path else config

        with patch.object(cfg, "_load", side_effect=load), patch.object(cfg, "_save"):
            cfg.set_dungeon("空幕", 2)
            self.assertEqual(cfg._read_dungeon(), ("空幕", 2))
            self.assertEqual(
                config["native_anomaly"],
                {"NativeType": "NativeCategory", "NativeSequence": 2},
            )
            self.assertEqual(
                [item["enabled"] for item in routine["Routine Items"]],
                [True, False, True],
            )
            cfg.set_dungeon("追猎目标", "音霸魔王")
            self.assertEqual(cfg._read_dungeon(), ("追猎目标", "音霸魔王"))
            self.assertEqual(
                [item["enabled"] for item in routine["Routine Items"]],
                [False, True, True],
            )

    def test_weekly_task_name_and_selection_aliases_roundtrip(self):
        task = self.weekly["March7th-Launcher"][1]
        task["physical_name"] = "NativeWeekly"
        task["key"] = "NativeStartDay"
        task["options"] = {
            "values": [{"display_name": "副本别名", "physical_name": "NativeStage"}]
        }
        cfg = self.load_adapters().StarRailConfig()
        config = {"currencywars_enable": False, "instance_names": {"untouched": "keep"}}
        with (
            patch.object(cfg, "_load", return_value=config),
            patch.object(cfg, "_save"),
        ):
            cfg.set_weekly_dungeon("历战余响", "副本别名")
            self.assertEqual(cfg._read_weekly_dungeon("历战余响"), "副本别名")
            cfg.set_weekly_start_day(4)
        self.assertEqual(config["NativeStartDay"], 4)
        self.assertEqual(
            config["instance_names"],
            {"untouched": "keep", "NativeWeekly": "NativeStage"},
        )

    def test_weekly_list_membership_uses_declared_field_and_value(self):
        task = self.weekly["ok-ww"][0]
        task["physical_name"] = "NativeWeekly"
        task["key"] = "NativeTasks"
        cfg = self.load_adapters().WutheringWavesConfig()
        config = {"NativeTasks": ["unrelated"]}
        with (
            patch.object(cfg, "_load", return_value=config),
            patch.object(cfg, "_save"),
        ):
            cfg._write_weekly(True)
            self.assertEqual(config, {"NativeTasks": ["unrelated", "NativeWeekly"]})
            cfg._write_weekly(False)
            self.assertEqual(config, {"NativeTasks": ["unrelated"]})

    def test_maa_fixed_stage_behavior_does_not_depend_on_display_alias(self):
        for option in self.daily["MAA"][0]["options"]["values"]:
            if option["physical_name"] == "1-7":
                option["display_name"] = "新土别名"
        cfg = self.load_adapters().ArknightsConfig()
        queue = [
            {"$type": "FightTask", "StagePlan": [stage], "IsEnable": False}
            for stage in ("Annihilation", "1-7", "AP-5", "CE-6")
        ]
        config = {"Configurations": {"Default": {"TaskQueue": queue}}}
        with (
            patch.object(cfg, "_load", return_value=config),
            patch.object(cfg, "_save"),
        ):
            cfg.set_dungeon("新土别名")
            self.assertEqual(
                [task["IsEnable"] for task in queue], [True, True, False, False]
            )
            self.assertEqual(cfg._read_dungeon(), ("新土别名", None))
            cfg.set_dungeon("红票")
            self.assertEqual(
                [task["IsEnable"] for task in queue], [True, True, True, False]
            )
            self.assertEqual(cfg._read_dungeon(), ("红票", None))

    def test_native_single_daily_entry_points_remain_available(self):
        for cls in (WutheringWavesConfig, NTEConfig, ArknightsConfig):
            self.assertTrue(callable(cls.set_dungeon))
            self.assertTrue(callable(cls._update_task))
            self.assertFalse(hasattr(cls, "set_daily_task"))


if __name__ == "__main__":
    unittest.main()
