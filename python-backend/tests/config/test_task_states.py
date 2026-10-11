"""状态查询直接由任务对象解释，MAA 初始化只由编辑或运行准备触发。"""

import json
import unittest
from copy import deepcopy
from functools import cache
from pathlib import Path
from unittest.mock import patch

from src.config import daily as daily_mod
from src.config import set_config
from src.config import weekly as weekly_mod
from src.service.run_actions import apply_subscript_config


class TestTaskStates(unittest.TestCase):
    def setUp(self):
        fixture = Path(__file__).parents[1] / "fixtures/maa_gui.new.scrubbed.json"
        self.data = json.loads(fixture.read_text(encoding="utf-8"))
        self.queue = self.data["Configurations"]["Default"]["TaskQueue"]
        self.queue.clear()
        self.saved = []

        def save(*args):
            config = args[-1]
            self.saved.append(deepcopy(config))
            self.data.clear()
            self.data.update(deepcopy(config))

        self.enterContext(
            patch.dict(set_config._CONFIGS, {"MAA": cache(set_config.ArknightsConfig)})
        )
        for module in (daily_mod, weekly_mod):
            self.enterContext(
                patch.object(
                    module,
                    "load_script_config",
                    side_effect=lambda *a, **kw: deepcopy(self.data),
                )
            )
            self.enterContext(
                patch.object(module, "save_script_config", side_effect=save)
            )
        self.resource = self.enterContext(
            patch.object(daily_mod, "read_activity_stages", return_value=["AT-8"])
        )

    def test_cold_queries_leave_the_native_queue_untouched(self):
        before = deepcopy(self.data)
        with patch.object(set_config.ArknightsConfig, "_init_config") as initialize:
            records = set_config.get_daily_readback("MAA")
            self.assertIsNone(set_config.get_weekly_task("MAA", "理智药剂"))
        self.assertEqual(
            records,
            [
                {"name": name, "task": None, "sequence": None, "enabled": False}
                for name in ("活动关卡", "理智作战", "剩余理智")
            ],
        )
        initialize.assert_not_called()
        self.resource.assert_not_called()
        self.assertEqual(self.saved, [])
        self.assertEqual(self.data, before)

    def test_queries_keep_disabled_selections_and_refresh_native_state(self):
        self.queue.append(
            {
                "$type": "FightTask",
                "Name": "理智作战",
                "StagePlan": ["CE-6"],
                "IsEnable": False,
            }
        )
        first = set_config.get_daily_readback("MAA")[1]
        self.assertEqual(
            first,
            {"name": "理智作战", "task": "CE-6", "sequence": None, "enabled": False},
        )
        first["task"] = "菜单修改"
        self.queue[0].update(StagePlan=["AP-5"], IsEnable=True)
        second = set_config.get_daily_readback("MAA")[1]
        self.assertEqual(
            second,
            {"name": "理智作战", "task": "AP-5", "sequence": None, "enabled": True},
        )
        self.assertEqual(self.saved, [])

    def test_daily_state_follows_declarations_without_script_registration(self):
        declaration = {
            "display_name": "日常",
            "class": "Daily",
            "config": "native.json",
            "enable_key": "enabled",
            "options": {
                "key": "kind",
                "values": [
                    {
                        "display_name": "材料",
                        "physical_name": "material",
                        "options": {
                            "key": "stage",
                            "values": [{"display_name": "副本", "physical_name": 2}],
                        },
                    }
                ],
            },
        }
        with (
            patch.object(
                set_config, "load_daily_map", return_value={"custom": [declaration]}
            ),
            patch.object(
                daily_mod,
                "load_script_config",
                return_value={"kind": "material", "stage": 2, "enabled": False},
            ),
        ):
            records = set_config.get_daily_readback("custom")
            self.assertEqual(set_config.get_daily_readback("unknown"), [])
        self.assertEqual(
            records, [{"name": "日常", "task": "材料", "sequence": 2, "enabled": False}]
        )

    def test_weekly_state_uses_its_declared_mechanism_and_path(self):
        class SelectableWeekly(weekly_mod.Weekly):
            def read_task(self):
                data = self._load_config(allow_missing=True)
                assert data is not None and "boss" in data
                return data["boss"]

        declaration = {
            "display_name": "独有周常",
            "class": "SelectableWeekly",
            "config": "weekly.yml",
            "key": "boss",
        }
        with (
            patch.dict(
                weekly_mod.WEEKLY_CLASSES, {"SelectableWeekly": SelectableWeekly}
            ),
            patch.object(
                weekly_mod, "load_weekly_map", return_value={"custom": [declaration]}
            ),
            patch.object(
                weekly_mod, "load_script_config", return_value={"boss": "副本"}
            ) as load,
        ):
            self.assertEqual(set_config.get_weekly_task("custom", "独有周常"), "副本")
            self.assertIsNone(set_config.get_weekly_task("custom", "不存在"))
            self.assertIsNone(set_config.get_weekly_task("unknown", "独有周常"))
        load.assert_called_once_with(
            "custom", "custom", "weekly.yml", allow_missing=True
        )

    def test_run_prepares_maa_even_without_weekly_settings(self):
        apply_subscript_config({"MAA"}, None)
        queue = self.data["Configurations"]["Default"]["TaskQueue"]
        self.assertEqual(
            [task["Name"] for task in queue],
            ["剿灭作战", "活动关优先", "理智作战", "剩余理智"],
        )
        self.assertTrue(queue[0]["IsEnable"])
        self.assertTrue(all(task["UseExpiringMedicine"] for task in queue))
        self.assertEqual(len(self.saved), 1)

    def test_edit_initializes_missing_slots_and_keeps_the_selection(self):
        set_config.set_config("MAA", "理智作战", "CE-6")
        self.assertEqual(
            set_config.get_daily_readback("MAA")[1],
            {"name": "理智作战", "task": "CE-6", "sequence": None, "enabled": True},
        )
        queue = self.data["Configurations"]["Default"]["TaskQueue"]
        self.assertEqual(len(queue), 4)
        self.assertTrue(queue[0]["IsEnable"])
        self.assertGreater(len(self.saved), 0)
