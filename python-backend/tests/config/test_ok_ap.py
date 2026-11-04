"""OK-AP 原生一键日常开关的读写。"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.config.native_task_switch import NativeTaskSwitch, load_native_task_switch_map
from src.config.set_config import AzurPromiliaConfig
from src.config.task.daily import build_dailies
from src.config.task.task_declarations import get_daily_configs


class TestOkAp(unittest.TestCase):
    def test_config_path_without_daily_cards(self):
        self.assertEqual(
            AzurPromiliaConfig()._daily_config_rel_path(),
            "data/apps/ok-ap/working/configs/DailyTask.json",
        )

    def test_daily_switches_preserve_other_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data/apps/ok-ap/working/configs/DailyTask.json"
            path.parent.mkdir(parents=True)
            original = {
                "家园每日": True,
                "委托每日": False,
                "每日收菜": False,
                "多账户模式": True,
            }
            path.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
            with patch(
                "src.utils.utils_sub_config.get_script_root_dir", return_value=directory
            ):
                switch = NativeTaskSwitch(
                    "ok-ap", load_native_task_switch_map()["ok-ap"]
                )
                self.assertEqual(
                    switch.read(),
                    [
                        {"name": "家园每日", "enabled": True},
                        {"name": "每日收菜", "enabled": False},
                    ],
                )
                switch.write({"每日收菜": True})
            original["每日收菜"] = True
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), original)

    def test_commission_selection_and_enable_use_separate_files(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / "data/apps/ok-ap/working/configs"
            folder.mkdir(parents=True)
            commission = folder / "CommissionDailyTask.json"
            routine = folder / "DailyTask.json"
            commission.write_text(
                json.dumps({"选择委托": "银光闪闪", "other": 7}, ensure_ascii=False),
                encoding="utf-8",
            )
            routine.write_text(
                json.dumps({"委托每日": False, "家园每日": True}, ensure_ascii=False),
                encoding="utf-8",
            )
            with patch(
                "src.utils.utils_sub_config.get_script_root_dir", return_value=directory
            ):
                daily = build_dailies("ok-ap", "蓝色星原", get_daily_configs("ok-ap"))[
                    0
                ]
                self.assertEqual(daily.read(), ("委托每日", "银光闪闪"))
                self.assertFalse(daily.read_enabled())
                daily.update("委托每日", "深巢梦魇")
                daily.set_enabled(True)
                self.assertEqual(daily.read(), ("委托每日", "深巢梦魇"))
                self.assertTrue(daily.read_enabled())
            self.assertEqual(
                json.loads(commission.read_text(encoding="utf-8")),
                {"选择委托": "深巢梦魇", "other": 7},
            )
            self.assertEqual(
                json.loads(routine.read_text(encoding="utf-8")),
                {"委托每日": True, "家园每日": True},
            )
