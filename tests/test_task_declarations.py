"""声明中的字段、物理名、别名接入原有子类读写流程。"""

import importlib.util
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from src.config import daily as daily_mod
from src.config import task_config
from src.config import weekly as weekly_mod
from src.config.daily import Daily
from src.config.set_config import ArknightsConfig, NTEConfig, WutheringWavesConfig
from src.utils.utils_weekly import DISABLED_START_DAY


def _read(cfg, daily_name: str) -> tuple[str | None, str | int | None]:
    """反读：经 Daily.read 的 I/O 闭环（读盘打桩由用例负责）。"""
    return cfg._dispatch_daily(daily_name).read()


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

    def make_weekly(self, class_name: str, script_name: str, declaration: dict):
        """按给定声明直接构造一条周常（声明即落点，改声明即改绑定）。"""
        return weekly_mod.WEEKLY_CLASSES[class_name](
            script_name, declaration, "测试脚本"
        )

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
            patch.object(Daily, "_load_daily_config", return_value=config),
            patch.object(Daily, "_save_daily_config") as save,
        ):
            cfg.set_daily_task("每日任务", "测试类别", 9)
            self.assertEqual(_read(cfg, "每日任务"), ("测试类别", 9))
        self.assertEqual(
            config,
            {**original, "NativeCategory": "NativeCategoryValue", "NativeStage": 9},
        )
        save.assert_called_once_with(config)

    def test_display_only_categories_share_declared_field(self):
        """两级写同一字段：落点写二级值，并顺带启用该日常的开关。"""
        for script in ("BetterGI", "ok-ef"):
            for option in self.daily[script][0]["options"]["values"]:
                option["options"]["key"] = "NativeTarget"
        adapters = self.load_adapters()
        cases = (
            (
                adapters.GenshinConfig,
                "圣遗物",
                {
                    "TaskDefinitions": {"daily-id": "自动秘境"},
                    "TaskEnabledList": {"daily-id": False},
                },
                {"TaskEnabledList": {"daily-id": True}},
            ),
            (
                adapters.EndfieldConfig,
                "干员养成",
                {"⭐刷体力": False},
                {"⭐刷体力": True},
            ),
        )
        for cls, task_name, switch_seed, switch_expected in cases:
            with self.subTest(cls=cls.__name__):
                cfg = cls()
                config = {**switch_seed, "NativeTarget": "old", "untouched": True}
                with (
                    patch.object(Daily, "_load_daily_config", return_value=config),
                    patch.object(daily_mod, "save_script_config"),
                ):
                    cfg.set_daily_task("每日任务", task_name, "真实副本")
                    self.assertEqual(_read(cfg, "每日任务"), ("真实副本", None))
                self.assertEqual(
                    config,
                    {
                        **switch_seed,
                        **switch_expected,
                        "NativeTarget": "真实副本",
                        "untouched": True,
                    },
                )

    def test_nte_daily_selection_follows_declared_native_names(self):
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

        with (
            patch.object(Daily, "_load_daily_config", return_value=config),
            patch.object(Daily, "_load_routine_config", return_value=routine),
            patch.object(daily_mod, "save_script_config"),
        ):
            cfg.set_daily_task("异象界域", "空幕", 2)
            self.assertEqual(_read(cfg, "异象界域"), ("空幕", 2))
            self.assertEqual(
                config["native_anomaly"],
                {"NativeType": "NativeCategory", "NativeSequence": 2},
            )
            # 只启用所选日常：另一个日常与无关项都不动
            self.assertEqual(
                [item["enabled"] for item in routine["Routine Items"]],
                [True, True, True],
            )
            routine["Routine Items"][0]["enabled"] = False  # 异象界域被用户停用
            cfg.set_daily_task("追猎目标", "追猎目标", "音霸魔王")
            self.assertEqual(_read(cfg, "追猎目标"), ("追猎目标", "音霸魔王"))
            self.assertEqual(
                [item["enabled"] for item in routine["Routine Items"]],
                [False, True, True],  # 停用的异象界域保持停用（工具层不再互斥）
            )

    def test_weekly_aliases_and_literal_start_day_roundtrip(self):
        """周常声明里的 key / enable_key 生效：改声明即改落点字段（含不启用分支）。"""
        declaration = self.weekly["March7th-Launcher"][1]
        declaration["key"] = "NativeStartDay"
        declaration["enable_key"] = "NativeEnable"
        weekly = self.make_weekly("EchoOfWarWeekly", "March7th-Launcher", declaration)
        config = {"currencywars_enable": False}
        with (
            patch.object(weekly, "_load_config", return_value=config),
            patch.object(weekly, "_save_config"),
        ):
            weekly.set_start_day(4)
            self.assertEqual(config["NativeStartDay"], 4)
            self.assertTrue(config["NativeEnable"])
            weekly.set_start_day(DISABLED_START_DAY)
        # 不启用只关总开关，字面起始日保留；同文件其它周常不受影响
        self.assertEqual(config["NativeStartDay"], 4)
        self.assertFalse(config["NativeEnable"])
        self.assertFalse(config["currencywars_enable"])

    def test_weekly_list_membership_uses_declared_field_and_value(self):
        declaration = self.weekly["ok-ww"][0]
        declaration["physical_name"] = "NativeWeekly"
        declaration["key"] = "NativeTasks"
        weekly = self.make_weekly("WutheringWavesWeekly", "ok-ww", declaration)
        config = {"NativeTasks": ["unrelated"]}
        with (
            patch.object(weekly, "_load_config", return_value=config),
            patch.object(weekly, "_save_config"),
            patch(
                "src.utils.utils_weekly.get_week_num",
                side_effect=[1, 0],
            ),
        ):
            # 周二(1)+1 >= 2 → 启用；周一(0)+1 < 2 → 停用
            weekly.prepare_start_day(2)
            self.assertEqual(config, {"NativeTasks": ["unrelated", "NativeWeekly"]})
            weekly.prepare_start_day(2)
            self.assertEqual(config, {"NativeTasks": ["unrelated"]})

    def test_maa_entry_and_stage_use_declared_physical_names(self):
        declaration = self.daily["MAA"][1]
        declaration["display_name"] = "新日常别名"
        declaration["physical_name"] = "NativeFight"
        declaration["options"]["values"] = [
            {"display_name": "新土别名", "physical_name": "1-7"}
        ]
        cfg = self.load_adapters().ArknightsConfig()
        queue = []
        config = {"Configurations": {"Default": {"TaskQueue": queue}}}
        with (
            patch.object(Daily, "_load_daily_config", return_value=config),
            patch.object(Daily, "_save_daily_config"),
        ):
            cfg.set_daily_task("新日常别名", "新土别名")
            self.assertEqual(queue[0]["Name"], "NativeFight")
            self.assertEqual(queue[0]["StagePlan"], ["1-7"])
            self.assertEqual(_read(cfg, "新日常别名"), ("新土别名", None))

    def test_native_single_daily_entry_points_remain_available(self):
        """单日常脚本的写/读入口仍在（都委托给该脚本解析出的日常实现类）。"""
        for cls in (WutheringWavesConfig, NTEConfig, ArknightsConfig):
            self.assertTrue(callable(cls.set_daily_task))
            for daily in cls()._dailies:
                self.assertTrue(callable(daily.update))


if __name__ == "__main__":
    unittest.main()
