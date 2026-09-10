"""自动启动设置：旧配置兼容、非法输入与实际 YAML 往返。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.service.app_service import AppService
from src.service.schedule import RunOptions, StartupOptions, load_startup_options
from src.utils.utils_yaml import dump_yaml, load_yaml


class TestStartupOptions(unittest.TestCase):
    def test_old_or_partial_config_keeps_defaults(self):
        for data in ({}, {"startup": {}}, {"startup": {"enabled": True}}):
            with self.subTest(data=data):
                self.assertEqual(load_startup_options(data), StartupOptions(True, 60))
        self.assertEqual(
            load_startup_options({"startup": {"enabled": False}}),
            StartupOptions(False, 60),
        )

    def test_valid_delay_boundaries(self):
        for delay in (1, 45, 3600):
            with self.subTest(delay=delay):
                self.assertEqual(
                    load_startup_options(
                        {"startup": {"enabled": True, "delay_seconds": delay}}
                    ),
                    StartupOptions(True, delay),
                )

    def test_invalid_config_never_automatically_launches(self):
        invalid = [None, [], "false", {"enabled": "false"}, {"enabled": 1}]
        invalid.extend(
            {"delay_seconds": value} for value in (None, True, 0, -1, 3601, 2.5, "30")
        )
        for block in invalid:
            with (
                self.subTest(block=block),
                self.assertLogs("src.service.schedule", level="WARNING"),
            ):
                self.assertEqual(
                    load_startup_options({"startup": block}), StartupOptions(False, 60)
                )

    def test_preferences_persist_without_overwriting_run_options(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory, "schedule.yml"))
            original = {
                "daily_run": {"enabled": False, "target_time": "04:10"},
                "notify": {"enabled": False, "email": "local@example.com"},
                "future_option": {"keep": "value"},
            }
            dump_yaml(path, original)
            with patch(
                "src.service.schedule.get_schedule_yml_path_under_root",
                return_value=path,
            ):
                service = AppService()
                service.apply_startup_options(StartupOptions(False, 125))
                data = load_yaml(path)
                for key, value in original.items():
                    self.assertIn(key, data)
                    self.assertEqual(data[key], value)
                self.assertEqual(
                    AppService().load_startup_options(), StartupOptions(False, 125)
                )
                service.apply_run_options(RunOptions(mute_enabled=True))
                self.assertEqual(
                    AppService().load_startup_options(), StartupOptions(False, 125)
                )
                service.apply_startup_options(StartupOptions(True, 125))
                self.assertEqual(
                    AppService().load_startup_options(), StartupOptions(True, 125)
                )
