"""示例中的 ok-script 启动任务使用稳定的类名。"""

import unittest
from pathlib import Path

from ruamel.yaml import YAML


class TestExampleOkTaskArguments(unittest.TestCase):
    def test_default_launches_named_daily_tasks(self):
        root = Path(__file__).resolve().parents[3]
        data = YAML(typ="safe").load(
            (root / "config/config.example.yml").read_text(encoding="utf-8")
        )
        expected = {
            "ok-ww.exe": "-t DailyTask -e",
            "ok-ef.exe": "-t DailyTask -e",
            "ok-nte.exe": "-t DailyRoutineTask -e",
        }
        scripts = {
            entry["script_path"].replace("\\", "/").split("/")[-1]: entry
            for entry in data["script_list"]
        }
        for executable, arguments in expected.items():
            with self.subTest(executable=executable):
                self.assertEqual(scripts[executable]["script_arguments"], arguments)

    def test_ok_ap_game_and_launch_defaults(self):
        root = Path(__file__).resolve().parents[3]
        data = YAML(typ="safe").load(
            (root / "config/config.example.yml").read_text(encoding="utf-8")
        )
        matches = [
            item
            for item in data["script_list"]
            if item["script_path"].endswith("ok-ap.exe")
        ]
        self.assertEqual(len(matches), 1)
        item = matches[0]
        self.assertEqual(item["game_process_name"], "AzurPromilia.exe")
        self.assertEqual(item["game_arguments"], "-start=azurpromilia_launcher")
        self.assertEqual(item["script_arguments"], "-t 1 -e")
