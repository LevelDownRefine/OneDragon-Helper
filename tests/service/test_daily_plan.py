"""每日计划：配置往返、系统任务注册与每次触发时运行全部脚本。"""

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
    DailyTaskState,
    WindowsDailyTask,
    apply_daily_plan,
    load_daily_plan,
    read_daily_task_state,
)
from src.service.schedule import RunOptions
from src.utils.utils_yaml import dump_yaml, load_yaml


class TestDailyPlanConfig(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = str(Path(directory.name, "schedule.yml"))
        self.original = {
            "daily_run": {"enabled": False, "target_time": "04:10"},
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
            load_daily_plan({"daily_run": {"enabled": True, "target_time": "09:40"}}),
            DailyPlanOptions(True, "09:40"),
        )

    def test_invalid_plan_is_disabled(self):
        for block in (
            [],
            "yes",
            {"enabled": "false"},
            {"enabled": True, "target_time": "25:10"},
        ):
            with (
                self.subTest(block=block),
                self.assertLogs("src.service.daily_plan", level="WARNING"),
            ):
                self.assertFalse(load_daily_plan({"daily_run": block}).enabled)

    def test_legacy_script_names_is_ignored(self):
        # 旧 schedule.yml 残留的 script_names 忽略不读，计划仍按启用与时间生效。
        self.assertEqual(
            load_daily_plan(
                {
                    "daily_run": {
                        "enabled": True,
                        "target_time": "08:30",
                        "script_names": ["A", "removed"],
                    }
                }
            ),
            DailyPlanOptions(True, "08:30"),
        )

    @patch("src.service.daily_plan.WindowsDailyTask")
    def test_stale_system_task_is_registered_again_on_save(self, task):
        """系统任务被外部删除 / 禁用 / 改时间时，保存同样的设置也重新注册。"""
        for state in (
            DailyTaskState(),
            DailyTaskState(True, False, "08:30"),
            DailyTaskState(True, True, "05:00"),
        ):
            with self.subTest(state=state):
                task.return_value.read.return_value = state
                task.return_value.sync.reset_mock()
                apply_daily_plan(DailyPlanOptions(True, "08:30"))
                task.return_value.sync.assert_called_once_with(
                    DailyPlanOptions(True, "08:30")
                )

    @patch("src.service.daily_plan.WindowsDailyTask")
    def test_missing_system_task_is_not_deleted_again_when_disabling(self, task):
        task.return_value.read.return_value = DailyTaskState()
        apply_daily_plan(DailyPlanOptions(False, "08:30"))
        task.return_value.sync.assert_not_called()

    @patch("src.service.daily_plan.WindowsDailyTask")
    def test_enable_update_disable_persist_and_preserve_other_options(self, task):
        # 回读按「上一次 sync 写到系统里的状态」推进，与真实任务计划一致。
        task.return_value.read.side_effect = [
            DailyTaskState(),
            DailyTaskState(True, True, "00:00"),
            DailyTaskState(True, True, "23:59"),
        ]
        for options in (
            DailyPlanOptions(True, "00:00"),
            DailyPlanOptions(True, "23:59"),
            DailyPlanOptions(False, "23:59"),
        ):
            apply_daily_plan(options)
            self.assertEqual(load_daily_plan(), options)
            self.assertEqual(load_yaml(self.path)["notify"], self.original["notify"])
        self.assertEqual(
            [call.args[0] for call in task.return_value.sync.call_args_list],
            [
                DailyPlanOptions(True, "00:00"),
                DailyPlanOptions(True, "23:59"),
                DailyPlanOptions(False, "23:59"),
            ],
        )

    @patch("src.service.daily_plan.WindowsDailyTask")
    def test_registration_failure_leaves_config_unchanged(self, task):
        task.return_value.read.return_value = DailyTaskState()
        task.return_value.sync.side_effect = OSError("denied")
        with self.assertRaisesRegex(OSError, "denied"):
            apply_daily_plan(DailyPlanOptions(True))
        self.assertEqual(load_yaml(self.path), self.original)

    @patch("src.service.daily_plan.WindowsDailyTask")
    def test_save_failure_restores_previous_task(self, task):
        task.return_value.read.return_value = DailyTaskState()
        with (
            patch(
                "src.service.daily_plan.save_schedule", side_effect=OSError("disk full")
            ),
            self.assertRaises(OSError),
        ):
            apply_daily_plan(DailyPlanOptions(True, "08:00"))
        self.assertEqual(
            [c.args[0] for c in task.return_value.sync.call_args_list],
            [DailyPlanOptions(True, "08:00"), DailyPlanOptions()],
        )
        self.assertEqual(load_yaml(self.path), self.original)


class TestDailyRun(unittest.TestCase):
    def test_disabled_or_no_scripts_never_runs(self):
        service = AppService()
        cases = (
            (False, {"script_list": [{"display_name": "A", "script_path": "a.py"}]}),
            (True, {"script_list": []}),
        )
        for enabled, config in cases:
            with (
                self.subTest(enabled=enabled),
                patch(
                    "src.service.daily_plan.load_daily_plan",
                    return_value=DailyPlanOptions(enabled),
                ),
                patch("src.service.daily_plan.load_config", return_value=config),
                patch("src.service.daily_plan.chain_service.schedule_run") as run,
            ):
                service.run_daily_plan()
                run.assert_not_called()

    def test_runs_all_scripts_with_daily_plan_run_options(self):
        service = AppService()
        with (
            patch(
                "src.service.daily_plan.load_daily_plan",
                return_value=DailyPlanOptions(
                    True,
                    run_options=RunOptions(
                        mute_enabled=True,
                        shutdown_enabled=True,
                        shutdown_delay=90,
                        rerun_enabled=True,
                        notify_enabled=True,
                        email="a@example.com",
                    ),
                ),
            ),
            patch(
                "src.service.daily_plan.load_config",
                return_value={
                    "script_list": [
                        {"display_name": "A", "script_path": "a.py"},
                        {"display_name": "B", "script_path": "b.py", "enabled": False},
                    ]
                },
            ),
            patch("src.service.daily_plan.chain_service.schedule_run") as run,
        ):
            service.run_daily_plan()
        args, kwargs = run.call_args
        self.assertEqual(args, ({"A", "B"}, "now"))
        self.assertTrue(kwargs["mute"])
        self.assertEqual(kwargs["shutdown_delay"], 90)
        self.assertTrue(kwargs["rerun_enabled"])
        self.assertEqual(
            kwargs["smtp_config"],
            {
                "enabled": True,
                "email": "a@example.com",
                "smtp_host": "",
                "smtp_port": None,
            },
        )
        self.assertTrue(kwargs["close_running"])

    @patch("src.cli.AppService")
    def test_cli_runs_daily_without_entering_gui(self, service):
        self.assertEqual(run_cli(build_parser().parse_args(["--run-daily"])), 0)
        service.return_value.run_daily_plan.assert_called_once_with()


class TestDailyTaskState(unittest.TestCase):
    def test_matches_only_when_registered_enabled_and_same_time(self):
        enabled = DailyPlanOptions(True, "08:30")
        self.assertTrue(DailyTaskState(True, True, "08:30").matches(enabled))
        self.assertFalse(DailyTaskState(True, True, "08:31").matches(enabled))
        self.assertFalse(DailyTaskState(True, True, "").matches(enabled))
        self.assertFalse(DailyTaskState(True, False, "08:30").matches(enabled))
        self.assertFalse(DailyTaskState().matches(enabled))

    def test_disabled_plan_matches_only_an_absent_task(self):
        self.assertTrue(DailyTaskState().matches(DailyPlanOptions(False, "08:30")))
        self.assertFalse(
            DailyTaskState(True, True, "08:30").matches(
                DailyPlanOptions(False, "08:30")
            )
        )


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

    def _foreign_task(self) -> Mock:
        foreign = Mock()
        foreign.Name = "UserDailyTask"
        return foreign

    def _own_task(self, enabled=True, boundary="2030-05-01T08:30:00") -> Mock:
        own = Mock()
        own.Name = self.task.name
        own.Enabled = enabled
        own.Definition.Triggers.Count = 1
        own.Definition.Triggers.Item.return_value.StartBoundary = boundary
        return own

    def test_read_reports_enabled_task_and_its_trigger_time(self):
        self.folder.GetTasks.return_value = [self._foreign_task(), self._own_task()]
        self.assertEqual(self.task.read(), DailyTaskState(True, True, "08:30"))

    def test_read_unregistered_or_foreign_task_returns_empty_state(self):
        for tasks in ([], [self._foreign_task()]):
            with self.subTest(tasks=tasks):
                self.folder.GetTasks.return_value = tasks
                self.assertEqual(self.task.read(), DailyTaskState())

    def test_read_disabled_task_is_reported_as_disabled(self):
        self.folder.GetTasks.return_value = [self._own_task(enabled=False)]
        self.assertEqual(self.task.read(), DailyTaskState(True, False, "08:30"))

    def test_read_task_without_usable_trigger_has_no_time(self):
        for boundary in ("", "not-a-time"):
            with self.subTest(boundary=boundary):
                self.folder.GetTasks.return_value = [self._own_task(boundary=boundary)]
                self.assertEqual(self.task.read(), DailyTaskState(True, True, ""))
        no_trigger = self._own_task()
        no_trigger.Definition.Triggers.Count = 0
        self.folder.GetTasks.return_value = [no_trigger]
        self.assertEqual(self.task.read(), DailyTaskState(True, True, ""))

    def test_state_reader_degrades_to_unregistered_when_read_fails(self):
        with (
            patch.object(WindowsDailyTask, "read", side_effect=OSError("denied")),
            self.assertLogs("src.service.daily_plan", level="WARNING") as logs,
        ):
            self.assertEqual(read_daily_task_state(), DailyTaskState())
        self.assertIn("denied", "\n".join(logs.output))

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
