"""全局设置预校验与委托；不运行任务。"""

import unittest
from dataclasses import asdict
from unittest.mock import patch

from src.service import run_service, settings_service
from src.service.schedule import RunOptions, StartupOptions


class SettingsServiceTests(unittest.TestCase):
    def test_invalid_startup_never_saves(self):
        with patch.object(settings_service, "apply_startup_options") as save:
            for value in (
                {},
                {"enabled": 1, "delay_seconds": 60},
                {"enabled": True, "delay_seconds": True},
                {"enabled": True, "delay_seconds": 0},
                {"enabled": False, "delay_seconds": 3601},
            ):
                with (
                    self.subTest(value=value),
                    self.assertRaises(run_service.InvalidRunRequest),
                ):
                    settings_service.save_startup(value)
        save.assert_not_called()

    def test_settings_save_without_starting_and_saved_run_without_saving(self):
        options = RunOptions(mute_enabled=True, close_running_enabled=False)
        with (
            patch.object(settings_service, "apply_run_options") as save_run,
            patch.object(settings_service, "apply_startup_options") as save_startup,
            patch.object(run_service, "selected_scripts", return_value=[]),
            patch.object(run_service, "load_run_options", return_value=options),
            patch.object(run_service, "apply_run_options") as forbidden,
            patch.object(run_service.chain_service, "schedule_run") as run,
        ):
            settings_service.save_startup({"enabled": False, "delay_seconds": 120})
            settings_service.save_run_options(asdict(options))
            target = run_service.saved_run(["test"])
        save_startup.assert_called_once_with(StartupOptions(False, 120))
        save_run.assert_called_once_with(options)
        forbidden.assert_not_called()
        run.assert_not_called()
        self.assertEqual(target["args"][-1], "run")
