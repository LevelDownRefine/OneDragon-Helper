"""每日计划：配置往返、系统任务注册与每次触发时读取最新配置。"""

import os
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from src.cli import build_parser, run_cli
from src.service.app_service import AppService
from src.service.daily_plan import (
    DailyPlanOptions,
    WindowsDailyTask,
    apply_daily_plan,
    load_daily_plan,
)
from src.service.schedule import RunOptions
from src.utils.utils_yaml import dump_yaml, load_yaml


class TestDailyPlanConfig(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = str(Path(directory.name, "schedule.yml"))
        self.original = {
            "daily_run": {"enabled": False, "target_time": "04:10", "script_names": []},
            "notify": {"enabled": True, "email": "a@example.com"},
        }
        config_patcher = patch(
            "src.service.daily_plan.load_config",
            return_value={
                "script_list": [
                    {"display_name": "A", "script_path": "a.py", "enabled": True},
                    {"display_name": "B", "script_path": "b.py", "enabled": False},
                ]
            },
        )
        self.config = config_patcher.start().return_value
        self.addCleanup(config_patcher.stop)
        dump_yaml(self.path, self.original)
        patcher = patch(
            "src.service.schedule.get_schedule_yml_path_under_root",
            return_value=self.path,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_missing_plan_is_disabled_by_default(self):
        self.assertEqual(load_daily_plan({}), DailyPlanOptions())

    def test_saved_daily_plan_is_loaded(self):
        self.assertEqual(
            load_daily_plan(
                {
                    "daily_run": {
                        "enabled": True,
                        "target_time": "09:40",
                        "script_names": ["A"],
                    },
                }
            ),
            DailyPlanOptions(True, "09:40", ("A",)),
        )

    def test_invalid_plan_is_disabled(self):
        for block in (
            [],
            "yes",
            {"enabled": "false"},
            {"enabled": True, "target_time": "25:10"},
            {"enabled": True, "script_names": "A"},
            {"enabled": True, "script_names": ["A", "A"]},
            {"enabled": True, "script_names": [None]},
        ):
            with (
                self.subTest(block=block),
                self.assertLogs("src.service.daily_plan", level="WARNING"),
            ):
                self.assertFalse(load_daily_plan({"daily_run": block}).enabled)

    def test_legacy_plan_freezes_selection_once_and_preserves_time(self):
        self.original["daily_run"] = {"enabled": True, "target_time": "08:30"}
        dump_yaml(self.path, self.original)
        first = load_daily_plan()
        self.assertEqual(first, DailyPlanOptions(True, "08:30", ("A",)))
        self.config["script_list"][0]["enabled"] = False
        self.config["script_list"][1]["enabled"] = True
        self.assertEqual(load_daily_plan(), first)
        self.assertEqual(load_yaml(self.path)["daily_run"]["script_names"], ["A"])
        self.assertEqual(load_yaml(self.path)["notify"], self.original["notify"])

    def test_legacy_migration_failure_is_not_silently_used(self):
        dump_yaml(self.path, {"daily_run": {"enabled": True, "target_time": "08:30"}})
        with (
            patch(
                "src.service.daily_plan.save_schedule", side_effect=OSError("locked")
            ),
            self.assertRaisesRegex(OSError, "locked"),
        ):
            load_daily_plan()

    @patch("src.service.daily_plan.WindowsDailyTask")
    def test_changing_only_scripts_does_not_reregister_trigger(self, task):
        apply_daily_plan(DailyPlanOptions(True, "08:30", ("A",)))
        task.return_value.sync.reset_mock()
        apply_daily_plan(DailyPlanOptions(True, "08:30", ("B",)))
        task.return_value.sync.assert_not_called()
        self.assertEqual(load_daily_plan(), DailyPlanOptions(True, "08:30", ("B",)))
        self.assertTrue(self.config["script_list"][0]["enabled"])
        self.assertFalse(self.config["script_list"][1]["enabled"])

    @patch("src.service.daily_plan.WindowsDailyTask")
    def test_empty_or_removed_script_cannot_enable_plan(self, task):
        for names in ((), ("removed",)):
            with self.subTest(names=names), self.assertRaises(ValueError):
                apply_daily_plan(DailyPlanOptions(True, script_names=names))
        task.return_value.sync.assert_not_called()
        self.assertEqual(load_yaml(self.path), self.original)

    @patch("src.service.daily_plan.WindowsDailyTask")
    def test_script_only_save_failure_keeps_old_plan_without_task_changes(self, task):
        first = DailyPlanOptions(True, "08:30", ("A",))
        apply_daily_plan(first)
        task.return_value.sync.reset_mock()
        with (
            patch(
                "src.service.daily_plan.save_schedule", side_effect=OSError("locked")
            ),
            self.assertRaises(OSError),
        ):
            apply_daily_plan(DailyPlanOptions(True, "08:30", ("B",)))
        self.assertEqual(load_daily_plan(), first)
        task.return_value.sync.assert_not_called()

    @patch("src.service.daily_plan.WindowsDailyTask")
    def test_enable_update_disable_persist_and_preserve_other_options(self, task):
        for options in (
            DailyPlanOptions(True, "00:00", ("A",)),
            DailyPlanOptions(True, "23:59", ("B",)),
            DailyPlanOptions(False, "23:59", ("B",)),
        ):
            apply_daily_plan(options)
            self.assertEqual(load_daily_plan(), options)
            self.assertEqual(load_yaml(self.path)["notify"], self.original["notify"])
        self.assertEqual(
            [call.args[0] for call in task.return_value.sync.call_args_list],
            [
                DailyPlanOptions(True, "00:00", ("A",)),
                DailyPlanOptions(True, "23:59", ("B",)),
                DailyPlanOptions(False, "23:59", ("B",)),
            ],
        )

    @patch("src.service.daily_plan.WindowsDailyTask")
    def test_registration_failure_leaves_config_unchanged(self, task):
        task.return_value.sync.side_effect = OSError("denied")
        with self.assertRaisesRegex(OSError, "denied"):
            apply_daily_plan(DailyPlanOptions(True, script_names=("A",)))
        self.assertEqual(load_yaml(self.path), self.original)

    @patch("src.service.daily_plan.WindowsDailyTask")
    def test_save_failure_restores_previous_task(self, task):
        with (
            patch(
                "src.service.daily_plan.save_schedule", side_effect=OSError("disk full")
            ),
            self.assertRaises(OSError),
        ):
            apply_daily_plan(DailyPlanOptions(True, "08:00", ("A",)))
        self.assertEqual(
            [c.args[0] for c in task.return_value.sync.call_args_list],
            [DailyPlanOptions(True, "08:00", ("A",)), DailyPlanOptions()],
        )
        self.assertEqual(load_yaml(self.path), self.original)


class TestDailyRun(unittest.TestCase):
    def test_removed_script_is_reported_without_running_unrelated_scripts(self):
        with (
            patch(
                "src.service.daily_plan.load_daily_plan",
                return_value=DailyPlanOptions(True, script_names=("removed",)),
            ),
            patch(
                "src.service.daily_plan.load_config",
                return_value={
                    "script_list": [
                        {"display_name": "B", "script_path": "b.py", "enabled": True}
                    ]
                },
            ),
            patch("src.service.daily_plan.chain_service.schedule_run") as run,
            patch("src.service.daily_plan.load_run_options") as options,
            self.assertLogs("src.service.daily_plan", level="WARNING") as logs,
        ):
            AppService().run_daily_plan()
        self.assertIn("removed", "\n".join(logs.output))
        run.assert_not_called()
        options.assert_not_called()

    def test_manual_selection_does_not_change_plan_and_run_options_stay_current(self):
        service = AppService()
        config = {
            "script_list": [
                {"display_name": "A", "script_path": "a.py"},
                {"display_name": "B", "script_path": "b.py", "enabled": False},
            ]
        }
        with (
            patch(
                "src.service.daily_plan.load_daily_plan",
                return_value=DailyPlanOptions(True, script_names=("A",)),
            ),
            patch("src.service.daily_plan.load_config", return_value=config),
            patch(
                "src.service.daily_plan.load_run_options",
                side_effect=[
                    RunOptions(),
                    RunOptions(
                        mute_enabled=True, shutdown_enabled=True, shutdown_delay=90
                    ),
                ],
            ),
            patch("src.service.daily_plan.chain_service.schedule_run") as run,
        ):
            service.run_daily_plan()
            config["script_list"][0]["enabled"] = False
            config["script_list"][1]["enabled"] = True
            service.run_daily_plan()
        first, second = run.call_args_list
        self.assertEqual(first.args, ({"A"}, "now"))
        self.assertFalse(first.kwargs["mute"])
        self.assertIsNone(first.kwargs["shutdown_delay"])
        self.assertEqual(second.args, ({"A"}, "now"))
        self.assertTrue(second.kwargs["mute"])
        self.assertEqual(second.kwargs["shutdown_delay"], 90)

    def test_disabled_or_empty_selection_never_runs_post_actions(self):
        service = AppService()
        for enabled in (False, True):
            with (
                self.subTest(enabled=enabled),
                patch(
                    "src.service.daily_plan.load_daily_plan",
                    return_value=DailyPlanOptions(enabled),
                ),
                patch(
                    "src.service.daily_plan.load_config",
                    return_value={
                        "script_list": [
                            {
                                "display_name": "A",
                                "script_path": "a.py",
                                "enabled": False,
                            }
                        ]
                    },
                ),
                patch("src.service.daily_plan.load_run_options") as read_options,
                patch("src.service.daily_plan.chain_service.schedule_run") as run,
            ):
                service.run_daily_plan()
                read_options.assert_not_called()
                run.assert_not_called()

    @patch("src.cli.AppService")
    def test_cli_runs_daily_without_entering_gui(self, service):
        self.assertEqual(run_cli(build_parser().parse_args(["--run-daily"])), 0)
        service.return_value.run_daily_plan.assert_called_once_with()


class TestWindowsDailyTask(unittest.TestCase):
    def setUp(self):
        self.service = Mock()
        self.folder = self.service.GetFolder.return_value
        self.definition = self.service.NewTask.return_value

        @contextmanager
        def connect():
            yield self.service

        patcher = patch("src.service.daily_plan._task_service", connect)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.task = WindowsDailyTask(os.path.abspath("中文 project"))

    def test_registers_daily_interactive_task_without_frozen_config_arguments(self):
        self.task.sync(DailyPlanOptions(True, "08:30"))
        self.task.sync(DailyPlanOptions(True, "09:40"))
        self.service.GetFolder.assert_called_with("\\")
        self.assertEqual(self.definition.Triggers.Create.return_value.DaysInterval, 1)
        self.assertTrue(
            self.definition.Triggers.Create.return_value.StartBoundary.endswith(
                "T09:40:00"
            )
        )
        self.assertEqual(self.definition.Principal.LogonType, 3)
        self.assertEqual(self.definition.Principal.RunLevel, 1)
        self.assertEqual(self.definition.Settings.MultipleInstances, 2)
        self.assertFalse(self.definition.Settings.StartWhenAvailable)
        self.assertFalse(self.definition.Settings.StopIfGoingOnBatteries)
        self.assertEqual(self.definition.Settings.ExecutionTimeLimit, "PT0S")
        action = self.definition.Actions.Create.return_value
        self.assertEqual(action.Arguments, "-m src.launcher --run-daily")
        self.assertEqual(action.WorkingDirectory, self.task.root_dir)
        self.assertEqual(
            [
                call.args[0]
                for call in self.folder.RegisterTaskDefinition.call_args_list
            ],
            [self.task.name, self.task.name],
        )

    def test_packaged_executable_uses_direct_entry(self):
        with (
            patch("sys.frozen", True, create=True),
            patch("sys.executable", "C:/中文 folder/helper.exe"),
        ):
            self.task.sync(DailyPlanOptions(True))
        action = self.definition.Actions.Create.return_value
        self.assertEqual(action.Path, "C:/中文 folder/helper.exe")
        self.assertEqual(action.Arguments, "--run-daily")

    def test_first_trigger_is_the_next_occurrence_without_immediate_catchup(self):
        for now, expected in (
            (datetime(2030, 5, 1, 8, 0), "2030-05-01T08:30:00"),
            (datetime(2030, 5, 1, 8, 30), "2030-05-02T08:30:00"),
            (datetime(2030, 5, 1, 9, 0), "2030-05-02T08:30:00"),
        ):
            with (
                self.subTest(now=now),
                patch("src.service.daily_plan.datetime") as clock,
            ):
                clock.now.return_value = now
                self.task.sync(DailyPlanOptions(True, "08:30"))
                self.assertEqual(
                    self.definition.Triggers.Create.return_value.StartBoundary, expected
                )

    def test_disable_deletes_only_this_installation_task(self):
        other = Mock()
        other.Name = "UserDailyTask"
        own = Mock()
        own.Name = self.task.name
        self.folder.GetTasks.return_value = [other, own]
        self.task.sync(DailyPlanOptions(False))
        self.folder.DeleteTask.assert_called_once_with(self.task.name, 0)
        self.folder.RegisterTaskDefinition.assert_not_called()
        self.folder.DeleteTask.reset_mock()
        self.folder.GetTasks.return_value = [other]
        self.task.sync(DailyPlanOptions(False))
        self.folder.DeleteTask.assert_not_called()

    def test_installation_names_are_stable_and_distinct(self):
        self.assertEqual(self.task.name, WindowsDailyTask(self.task.root_dir).name)
        self.assertNotEqual(
            self.task.name, WindowsDailyTask(self.task.root_dir + "-other").name
        )
