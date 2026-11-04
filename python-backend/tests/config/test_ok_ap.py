"""OK-AP 原生一键日常开关的读写。"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.config.native_task_switch import NativeTaskSwitch, load_native_task_switch_map
from src.config.set_config import AzurPromiliaConfig


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
                        {"name": "委托每日", "enabled": False},
                        {"name": "每日收菜", "enabled": False},
                    ],
                )
                switch.write({"委托每日": True})
            original["委托每日"] = True
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), original)
