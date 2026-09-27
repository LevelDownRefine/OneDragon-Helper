"""手动运行配置、载荷与调度委托；不运行真实脚本或系统动作。"""

import json
import unittest
from dataclasses import asdict
from unittest.mock import patch

from src.service import run_service
from src.service.schedule import RunOptions


class RunServiceTests(unittest.TestCase):
    def test_invalid_options_rejected_before_save(self):
        defaults = asdict(RunOptions())
        for change in (
            {"mute_enabled": 1},
            {"shutdown_delay": True},
            {"shutdown_delay": 86401},
            {"smtp_port": "bad"},
            {"smtp_port": "65536"},
            {"auth_code": "test-secret"},
            {"shutdown_enabled": True},
            {"unknown": 1},
        ):
            with (
                self.subTest(change=change),
                self.assertRaises(run_service.InvalidRunRequest),
            ):
                run_service.parse_options({**defaults, **change})

    def test_invalid_script_warning_requires_confirmation(self):
        with (
            patch.object(run_service, "selected_scripts", return_value=[]),
            patch.object(
                run_service,
                "collect_invalid_script_messages",
                return_value=[("demo", "missing")],
            ),
            patch.object(run_service, "apply_run_options") as save,
            self.assertRaises(run_service.InvalidRunRequest),
        ):
            run_service.prepare_run(["demo"], asdict(RunOptions()), False)
        save.assert_not_called()

    def test_prepare_passes_names_in_stdin_and_omits_credentials(self):
        names = ["中文,逗号 & 空格"]
        options = RunOptions(
            email="test@example.invalid", auth_code="test-secret", mute_enabled=True
        )
        with (
            patch.object(run_service, "selected_scripts", return_value=[]),
            patch.object(
                run_service, "collect_invalid_script_messages", return_value=[]
            ),
            patch.object(run_service, "apply_run_options") as save,
            patch.object(
                run_service,
                "load_run_options",
                return_value=RunOptions(email=options.email, mute_enabled=True),
            ),
        ):
            target = run_service.prepare_run(names, asdict(options), False)
        save.assert_called_once_with(options)
        self.assertEqual(target["args"][-1], "run")
        self.assertTrue(target["console"])
        payload = json.loads(target["input"])
        self.assertEqual(payload["script_names"], names)
        self.assertEqual(payload["options"]["auth_code"], "")
        self.assertNotIn("test-secret", json.dumps(target))
        self.assertNotIn(names[0], target["args"])

    def test_failed_save_returns_no_launch_target(self):
        with (
            patch.object(run_service, "selected_scripts", return_value=[]),
            patch.object(
                run_service, "collect_invalid_script_messages", return_value=[]
            ),
            patch.object(
                run_service, "apply_run_options", side_effect=OSError("disk full")
            ),
            patch.object(run_service, "load_run_options") as read,
            self.assertRaisesRegex(OSError, "disk full"),
        ):
            run_service.prepare_run(["demo"], asdict(RunOptions()), False)
        read.assert_not_called()

    def test_worker_delegates_snapshot_options_to_original_scheduler(self):
        options = RunOptions(
            mute_enabled=True,
            unmute_enabled=True,
            close_running_enabled=False,
            rerun_enabled=True,
            notify_enabled=True,
            email="test@example.invalid",
            smtp_port="465",
        )
        with (
            patch.object(
                run_service,
                "selected_scripts",
                return_value=[{"display_name": "demo", "script_path": "demo.py"}],
            ),
            patch.object(run_service.chain_service, "schedule_run") as run,
        ):
            run_service.run_batch(["demo"], asdict(options))
        run.assert_called_once_with(
            {"demo"},
            "now",
            mute=True,
            unmute=True,
            close_running=False,
            rerun_enabled=True,
            smtp_config={
                "enabled": True,
                "email": "test@example.invalid",
                "smtp_port": 465,
            },
        )

    def test_empty_unknown_duplicate_selection_rejected(self):
        with patch.object(
            run_service,
            "load_config",
            return_value={
                "script_list": [{"display_name": "demo", "script_path": "demo.py"}]
            },
        ):
            for names in ([], ["missing"], ["demo", "demo"], [True]):
                with (
                    self.subTest(names=names),
                    self.assertRaises(run_service.InvalidRunRequest),
                ):
                    run_service.selected_scripts(names)
