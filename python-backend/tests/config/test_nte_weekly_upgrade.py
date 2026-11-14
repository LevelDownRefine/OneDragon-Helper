"""使用真实 JSON 读写模拟 ok-nte 升级后的周本配置。"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.config.set_config import NTEConfig


class TestNteWeeklyUpgrade(unittest.TestCase):
    def test_upgrade_old_routine_and_config(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            working = root / "data/apps/ok-nte/working"
            configs = working / "configs"
            configs.mkdir(parents=True)
            task_file = configs / "DailyRoutineTaskConfigs.json"
            routine_file = configs / "DailyRoutineTask.json"
            resources = working / "assets/game/weeklyboss_item/boss_names.json"
            resources.parent.mkdir(parents=True)
            resources.write_text(
                json.dumps(
                    {"Dress Sleeves of Vanity": {"zh_CN": "永不谢幕的阿拉克涅"}},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            old_task = {"daily_anomaly": {"目标": "保留"}}
            old_routine = {
                "Routine Items": [{"id": "daily_anomaly", "enabled": True}],
                "其他": 42,
            }
            task_file.write_text(
                json.dumps(old_task, ensure_ascii=False), encoding="utf-8"
            )
            routine_file.write_text(
                json.dumps(old_routine, ensure_ascii=False), encoding="utf-8"
            )
            with patch(
                "src.utils.utils_sub_config.get_script_root_dir", return_value=str(root)
            ):
                adapter = NTEConfig()
                self.assertIsNone(adapter._read_weekly_task("异象巡礼"))
                self.assertEqual(
                    json.loads(task_file.read_text(encoding="utf-8")), old_task
                )
                adapter.set_weekly_task("异象巡礼", "永不谢幕的阿拉克涅")
                adapter.set_weekly_start_day("异象巡礼", 2)
                task = json.loads(task_file.read_text(encoding="utf-8"))
                routine = json.loads(routine_file.read_text(encoding="utf-8"))
                self.assertEqual(task["daily_anomaly"], old_task["daily_anomaly"])
                self.assertEqual(
                    task["anomaly_pilgrimage"],
                    {"目标": ["Dress Sleeves of Vanity"], "每周开始运行日": "周二"},
                )
                self.assertEqual(
                    routine["Routine Items"],
                    [
                        {"id": "anomaly_pilgrimage", "enabled": True},
                        *old_routine["Routine Items"],
                    ],
                )
                self.assertEqual(routine["其他"], 42)
                self.assertEqual(
                    adapter._read_weekly_task("异象巡礼"), "永不谢幕的阿拉克涅"
                )
                adapter.prepare_weekly_start_days({"异象巡礼": 0})
                routine = json.loads(routine_file.read_text(encoding="utf-8"))
                self.assertFalse(routine["Routine Items"][0]["enabled"])
                self.assertTrue(routine["Routine Items"][1]["enabled"])
                self.assertEqual(
                    json.loads(task_file.read_text(encoding="utf-8")), task
                )
