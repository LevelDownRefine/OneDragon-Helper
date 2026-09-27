"""每日计划表单边界：不访问本机系统任务。"""

import os
import unittest
from dataclasses import asdict
from unittest.mock import Mock, patch

from src.service import daily_cli
from src.service.daily_plan import DailyPlanOptions
from src.service.run_service import InvalidRunRequest
from src.service.schedule import RunOptions
from src.utils.utils_shutdown import RUST_CONFIRM_ENV


class DailyCliTests(unittest.TestCase):
    def test_read_failure_is_unknown_not_unregistered(self):
        with (
            patch.object(
                daily_cli,
                "_task",
                return_value=Mock(read=Mock(side_effect=OSError("denied"))),
            ),
            patch.object(daily_cli, "load_daily_plan", return_value=DailyPlanOptions()),
            self.assertLogs("src.service.daily_cli", level="WARNING"),
        ):
            view = daily_cli.daily_view()
        self.assertIsNone(view["state"])
        self.assertEqual(view["state_error"], "denied")

    def test_validation_before_registration_and_pause_preserves_options(self):
        plan = DailyPlanOptions(
            False, "04:10", RunOptions(shutdown_enabled=True, shutdown_delay=45)
        )
        with (
            patch.object(daily_cli, "apply_daily_plan") as save,
            patch.object(daily_cli, "_task") as task,
        ):
            for change in (
                {"enabled": 1},
                {"target_time": "25:00"},
                {"target_time": "bad"},
                {"unknown": True},
            ):
                with self.subTest(change=change), self.assertRaises(InvalidRunRequest):
                    daily_cli.save_daily({**asdict(plan), **change})
            save.assert_not_called()
            task.assert_not_called()
            daily_cli.save_daily(asdict(plan))
        save.assert_called_once_with(plan, task=task.return_value)

    def test_task_entry_uses_headless_and_frontend_without_config_snapshot(self):
        with (
            patch.dict(os.environ, {RUST_CONFIRM_ENV: "/中文 gui.exe"}),
            patch.object(daily_cli, "WindowsDailyTask") as task,
        ):
            daily_cli._task()
        self.assertEqual(
            task.call_args.kwargs["entry"][1],
            ["-m", "src.headless", "daily", "--shutdown-ui", "/中文 gui.exe"],
        )
