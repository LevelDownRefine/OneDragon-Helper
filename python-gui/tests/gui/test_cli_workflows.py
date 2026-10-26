"""复杂流程验证任务身份、取消确认、断线保护及安装交接。"""

from dataclasses import asdict
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QDialog, QMessageBox

from gui.cli_client import CliFailure, CliSession
from gui.cli_job import CliJob
from gui.controllers.cli_backup import validate_backup_result
from gui.controllers.cli_daily_plan import CliDailyPlanController, parse_plan_view
from gui.controllers.cli_launch import CliLaunchController, validate_run_target
from gui.controllers.cli_settings import CliSettingsController
from gui.controllers.cli_update import CliUpdateController, validate_update_result
from gui.dialogs import FormDialogBase
from src.service.daily_plan import DailyPlanOptions
from src.service.schedule import RunOptions
from tests.gui.helpers import get_app


class Transport(QObject):
    succeeded = Signal(int, object)
    failed = Signal(int, object)
    closed = Signal()

    def __init__(self):
        super().__init__()
        self.usable = True
        self.running = True
        self.protected = False
        self.requests = []

    def request(self, method, params):
        self.requests.append((method, params))
        return len(self.requests)

    def close(self):
        self.usable = False

    def protect(self):
        self.protected = True

    def unprotect(self):
        self.protected = False


class LaunchWorkflowTests(TestCase):
    """两端共用的 run.view / prepare / saved 确认与交付契约。"""

    def setUp(self):
        get_app()
        self.transport = Transport()
        self.session = CliSession(self.transport, None)
        self.games = SimpleNamespace(
            games=[{"script_name": "A"}, {"script_name": "B"}],
            enabled=[True, False],
        )
        self.toast = Mock()
        self.controller = CliLaunchController(self.games, self.session, self.toast)
        self.controller._starter.start = Mock()

    def reply(self, value):
        self.transport.succeeded.emit(len(self.transport.requests), value)

    def view(self, *, invalid=(), options=None):
        return {
            "script_names": ["A"],
            "invalid": list(invalid),
            "options": asdict(options if options is not None else RunOptions()),
            "shutdown_supported": True,
        }

    def target(self):
        return {
            "kind": "command",
            "program": "python",
            "args": ["-m", "src.headless", "run"],
            "cwd": None,
            "env": {},
            "console": True,
            "input": '{"script_names":["A"]}',
        }

    def test_empty_selection_stays_local_without_confirmation_or_request(self):
        self.games.enabled = [False, False]
        with patch("gui.controllers.cli_launch.RunConfirmDialog") as dialog:
            self.controller.launchAll()
        self.toast.assert_called_once_with("没有勾选手动运行的脚本")
        dialog.assert_not_called()
        self.assertEqual(self.transport.requests, [])
        self.controller._starter.start.assert_not_called()
        self.assertFalse(self.controller.active)

    def test_saved_selection_failure_toasts_without_starting_or_replaying(self):
        self.controller.launchAll(confirm=False)
        self.transport.failed.emit(1, CliFailure(-32001, "脚本不存在: A"))
        self.toast.assert_called_once_with("脚本不存在: A")
        self.assertEqual(
            self.transport.requests, [("run.saved", {"script_names": ["A"]})]
        )
        self.controller._starter.start.assert_not_called()
        self.assertFalse(self.controller.active)

    def test_delivery_signals_report_result_and_release_launch_state(self):
        self.controller.launchAll(confirm=False)
        self.reply(self.target())
        self.controller._starter.failed.emit("运行配置交付超时")
        self.toast.assert_called_once_with("运行配置交付超时")
        self.assertFalse(self.controller.active)

        self.toast.reset_mock()
        self.controller.launchAll(confirm=False)
        self.reply(self.target())
        self.controller._starter.started.emit()
        self.toast.assert_called_once_with(
            "手动运行：已在独立控制台启动，关闭控制台即取消"
        )
        self.assertFalse(self.controller.active)
        self.assertEqual(
            self.transport.requests,
            [("run.saved", {"script_names": ["A"]})] * 2,
        )

    def test_cancel_keeps_saved_options_without_warning_or_prepare(self):
        options = RunOptions(shutdown_enabled=False, shutdown_delay=45)
        with (
            patch("gui.controllers.cli_launch.styled_msg_box") as warning,
            patch("gui.controllers.cli_launch.RunConfirmDialog") as dialog,
        ):
            dialog.return_value.exec.return_value = QDialog.Rejected
            self.controller.launchAll()
            self.reply(self.view(options=options))
        warning.assert_not_called()
        dialog.assert_called_once()
        self.assertEqual(dialog.call_args.args, (1, options))
        self.assertEqual(
            self.transport.requests, [("run.view", {"script_names": ["A"]})]
        )
        self.controller._starter.start.assert_not_called()
        self.assertFalse(self.controller.active)

    def test_invalid_warning_no_cancels_before_options_or_prepare(self):
        with (
            patch("gui.controllers.cli_launch.styled_msg_box") as warning,
            patch("gui.controllers.cli_launch.RunConfirmDialog") as dialog,
        ):
            warning.return_value.exec.return_value = QMessageBox.No
            self.controller.launchAll()
            self.reply(self.view(invalid=[{"name": "A", "reason": "exe 不存在"}]))
        self.assertIn("A：exe 不存在", warning.call_args.args[3])
        dialog.assert_not_called()
        self.assertEqual(
            self.transport.requests, [("run.view", {"script_names": ["A"]})]
        )
        self.controller._starter.start.assert_not_called()
        self.assertFalse(self.controller.active)

    def test_invalid_warning_yes_saves_edited_options_and_waits_for_ack(self):
        dialog = Mock()
        dialog.run_options = RunOptions(shutdown_enabled=True, shutdown_delay=120)
        saved_options = RunOptions(shutdown_enabled=False, shutdown_delay=45)
        target = self.target()

        def make_dialog(*args, **kwargs):
            self.assertEqual(args, (1, saved_options))
            assert "submit" in kwargs

            def execute():
                kwargs["submit"](dialog)
                self.controller._starter.start.assert_not_called()
                self.assertTrue(self.session.busy)
                self.assertEqual(
                    self.transport.requests[-1],
                    (
                        "run.prepare",
                        {
                            "script_names": ["A"],
                            "options": asdict(dialog.run_options),
                            "confirm_invalid": True,
                        },
                    ),
                )
                self.reply(target)
                return QDialog.Accepted

            dialog.exec.side_effect = execute
            return dialog

        with (
            patch("gui.controllers.cli_launch.styled_msg_box") as warning,
            patch(
                "gui.controllers.cli_launch.RunConfirmDialog", side_effect=make_dialog
            ),
        ):
            warning.return_value.exec.return_value = QMessageBox.Yes
            self.controller.launchAll()
            self.reply(
                self.view(
                    invalid=[{"name": "A", "reason": "exe 不存在"}],
                    options=saved_options,
                )
            )
        dialog.accept.assert_called_once()
        self.controller._starter.start.assert_called_once_with(target)
        self.assertFalse(self.session.busy)


class WorkflowTests(TestCase):
    def setUp(self):
        get_app()
        self.transport = Transport()
        self.factory = Mock(return_value=Transport())
        self.session = CliSession(self.transport, self.factory)
        self.job = CliJob(self.session, interval_ms=100000)
        self.results, self.errors = [], []
        self.job.succeeded.connect(self.results.append)
        self.job.failed.connect(self.errors.append)
        self.addCleanup(self.job._timer.stop)

    def reply(self, value):
        self.transport.succeeded.emit(len(self.transport.requests), value)

    def start(self, method="restore.start"):
        self.job.start(
            method,
            {"zip_path": "backup.zip", "confirmed": True}
            if method == "restore.start"
            else {},
        )
        self.reply({"id": "job-1"})
        self.job._timer.stop()
        self.job._poll()

    def test_restore_polls_same_session_and_releases_only_terminal_result(self):
        self.start()
        self.assertTrue(self.session.busy)
        self.assertTrue(self.transport.protected)
        self.reply({"id": "job-1", "kind": "restore", "state": "running"})
        self.assertTrue(self.session.busy)
        self.job._timer.stop()
        self.job._poll()
        result = {"restored": 2, "skipped_scripts": []}
        self.reply(
            {"id": "job-1", "kind": "restore", "state": "succeeded", "result": result}
        )
        self.assertEqual(self.results, [result])
        self.assertFalse(self.session.busy)
        self.assertEqual(
            self.transport.requests[0],
            ("restore.start", {"zip_path": "backup.zip", "confirmed": True}),
        )
        self.assertEqual(
            self.transport.requests[1:], [("job.poll", {"job_id": "job-1"})] * 2
        )

    def test_rejected_start_keeps_session_and_allows_explicit_retry(self):
        self.job.start("restore.start", {"zip_path": "invalid.zip", "confirmed": True})
        self.transport.failed.emit(1, CliFailure(-32002, "invalid backup"))
        self.assertFalse(self.job.active)
        self.assertFalse(self.session.busy)
        self.assertTrue(self.session.usable)
        self.factory.assert_not_called()
        self.assertEqual(len(self.transport.requests), 1)
        self.job.start("restore.start", {"zip_path": "valid.zip", "confirmed": True})
        self.assertEqual(
            self.transport.requests[-1],
            ("restore.start", {"zip_path": "valid.zip", "confirmed": True}),
        )
        self.reply({"id": "job-2"})
        self.job._timer.stop()
        self.job._poll()
        self.reply(
            {
                "id": "job-2",
                "kind": "restore",
                "state": "succeeded",
                "result": {"restored": 1, "skipped_scripts": []},
            }
        )
        self.assertEqual(len(self.results), 1)

    def test_daily_busy_shows_feedback_without_read_or_open(self):
        toast = Mock()
        controller = CliDailyPlanController(self.session, toast)
        self.session.hold()
        controller.edit()
        toast.assert_called_once_with("已有后台操作，请稍候")
        self.assertEqual(self.transport.requests, [])
        toast.reset_mock()
        controller._opening = True
        controller.edit()
        toast.assert_not_called()
        self.session.release()

    def test_unknown_start_result_keeps_old_process_and_never_replays(self):
        self.job.start("restore.start", {"zip_path": "backup.zip", "confirmed": True})
        self.transport.usable = False
        self.transport.failed.emit(1, CliFailure("transport_failed", "lost"))
        self.assertFalse(self.job.active)
        self.assertTrue(self.session.busy)
        self.assertTrue(self.transport.protected)
        with self.assertRaises(RuntimeError):
            self.session.request("app.snapshot", {})
        self.factory.assert_not_called()
        self.transport.running = False
        self.transport.closed.emit()
        self.assertFalse(self.session.busy)
        self.session.request("app.snapshot", {})
        self.assertEqual(self.factory.return_value.requests, [("app.snapshot", {})])
        self.assertEqual(len(self.transport.requests), 1)

    def test_wrong_identity_or_missing_result_retires_session(self):
        for payload in (
            {"id": "other", "kind": "restore", "state": "running"},
            {"id": "job-1", "kind": "backup", "state": "running"},
            {"id": "job-1", "kind": "restore", "state": "succeeded"},
            {"id": "job-1", "kind": "restore", "state": "cancelled"},
        ):
            with self.subTest(payload=payload):
                transport = Transport()
                session = CliSession(transport, None)
                job = CliJob(session)
                errors = []
                job.failed.connect(errors.append)
                job.start("restore.start")
                transport.succeeded.emit(1, {"id": "job-1"})
                job._timer.stop()
                job._poll()
                transport.succeeded.emit(2, payload)
                self.assertEqual(errors[0].code, "invalid_response")
                self.assertFalse(transport.usable)
                self.assertTrue(session.busy)
                transport.running = False
                transport.closed.emit()

    def test_cancel_before_start_ack_sends_once_and_waits_for_terminal_poll(self):
        self.job.start("update.download")
        self.assertTrue(self.job.cancel())
        self.reply({"id": "job-1"})
        self.job._timer.stop()
        self.assertEqual(
            self.transport.requests[-1], ("job.cancel", {"job_id": "job-1"})
        )
        self.assertTrue(self.job.cancel())
        self.reply(True)
        self.assertTrue(self.job.active)
        self.job._poll()
        cancelled = Mock()
        self.job.cancelled.connect(cancelled)
        self.reply({"id": "job-1", "kind": "update.download", "state": "cancelled"})
        cancelled.assert_called_once()
        self.assertFalse(self.session.busy)

    def test_restore_is_not_cancellable_and_failure_reports_error(self):
        self.start()
        self.assertFalse(self.job.cancel())
        self.reply(
            {"id": "job-1", "kind": "restore", "state": "failed", "error": "disk full"}
        )
        self.assertEqual(self.errors[0].message, "disk full")
        self.assertTrue(self.transport.usable)
        self.assertFalse(self.session.busy)

    def test_form_cannot_close_during_ack_wait_and_can_retry_after_error(self):
        dialog = FormDialogBase()
        dialog.show()
        dialog.set_pending(True)
        dialog.reject()
        dialog.close()
        self.assertTrue(dialog.isVisible())
        dialog.set_pending(False)
        dialog.reject()
        self.assertFalse(dialog.isVisible())

    def test_saved_run_uses_cli_target_and_preserves_stdin_payload(self):
        games = SimpleNamespace(games=[{"script_name": "A"}], enabled=[True])
        controller = CliLaunchController(games, self.session, Mock())
        target = {
            "kind": "command",
            "program": "python",
            "args": ["-m", "src.headless", "run"],
            "cwd": None,
            "env": {},
            "console": True,
            "input": '{"script_names":["A"]}',
        }
        controller._starter.start = Mock()
        controller.launchAll(confirm=False)
        self.assertEqual(
            self.transport.requests, [("run.saved", {"script_names": ["A"]})]
        )
        self.reply(target)
        controller._starter.start.assert_called_once_with(target)
        self.assertTrue(controller.active)
        controller._starter.started.emit()
        self.assertFalse(controller.active)

    def test_restore_requires_confirmation_before_start(self):
        controller = CliSettingsController(self.session, Mock())
        controller._pick_zip = Mock(return_value="backup.zip")
        with patch("gui.controllers.cli_backup.styled_msg_box") as box:
            box.return_value.exec.return_value = 0
            controller.restoreConfig()
        self.assertEqual(self.transport.requests, [])

    def test_confirmed_restore_passes_same_wire_parameters_as_rust(self):
        controller = CliSettingsController(self.session, Mock())
        controller._pick_zip = Mock(return_value="backup.zip")
        controller._backup_job = Mock()
        with patch("gui.controllers.cli_backup.styled_msg_box") as box:
            box.return_value.exec.return_value = QMessageBox.Yes
            controller.restoreConfig()
        controller._backup_job.assert_called_once_with(
            "restore.start", {"zip_path": "backup.zip", "confirmed": True}
        )

    def test_manual_run_prepares_once_and_starts_only_after_save_ack(self):
        games = SimpleNamespace(games=[{"script_name": "A"}], enabled=[True])
        controller = CliLaunchController(games, self.session, Mock())
        controller._starter.start = Mock()
        target = {
            "kind": "command",
            "program": "python",
            "args": [],
            "cwd": None,
            "env": {},
            "console": True,
            "input": "{}",
        }
        dialog = Mock()
        dialog.run_options = RunOptions()

        def make_dialog(*_args, **kwargs):
            def execute():
                kwargs["submit"](dialog)
                kwargs["submit"](dialog)
                self.assertEqual(len(self.transport.requests), 2)
                self.assertTrue(self.session.busy)
                dialog.set_pending.assert_called_with(True)
                controller._starter.start.assert_not_called()
                self.reply(target)
                return QDialog.Accepted

            dialog.exec.side_effect = execute
            return dialog

        with patch(
            "gui.controllers.cli_launch.RunConfirmDialog", side_effect=make_dialog
        ):
            controller.launchAll()
            self.reply(
                {
                    "script_names": ["A"],
                    "invalid": [],
                    "options": asdict(RunOptions()),
                    "shutdown_supported": True,
                }
            )
        self.assertEqual(
            self.transport.requests[1],
            (
                "run.prepare",
                {
                    "script_names": ["A"],
                    "options": asdict(RunOptions()),
                    "confirm_invalid": False,
                },
            ),
        )
        controller._starter.start.assert_called_once_with(target)
        self.assertFalse(self.session.busy)

    def test_daily_plan_preserves_form_on_failure_and_registers_only_on_save(self):
        toast = Mock()
        controller = CliDailyPlanController(self.session, toast)
        options = DailyPlanOptions(enabled=True, target_time="06:00")
        dialog = Mock()
        dialog.daily_plan = options
        dialog.isVisible.return_value = True
        changed = Mock()
        controller.changed.connect(changed)

        def execute():
            save = dialog.saveRequested.connect.call_args.args[0]
            save()
            save()
            self.assertTrue(self.session.busy)
            self.assertEqual(len(self.transport.requests), 2)
            self.transport.failed.emit(2, CliFailure(-32002, "registration failed"))
            dialog.show_error.assert_called_with("registration failed")
            dialog.accept.assert_not_called()
            changed.assert_not_called()
            save()
            self.reply(None)

        dialog.exec.side_effect = execute
        with patch(
            "gui.controllers.cli_daily_plan.DailyPlanDialog", return_value=dialog
        ):
            controller.edit()
            self.reply(
                {
                    "plan": asdict(DailyPlanOptions()),
                    "state": None,
                    "state_error": "access denied",
                    "supported": True,
                    "shutdown_supported": True,
                }
            )
        dialog.state_label.setText.assert_called_once_with(
            "系统任务：读取失败（access denied）"
        )
        self.assertEqual(
            self.transport.requests[1:], [("plan.save", {"plan": asdict(options)})] * 2
        )
        dialog.accept.assert_called_once()
        changed.assert_called_once()
        self.assertEqual(controller.plan, options)

    def test_update_close_during_download_waits_for_cancelled_state(self):
        controller = CliUpdateController(self.session)
        controller._dialog = Mock()
        controller._start("download")
        controller._close()
        controller._dialog.done.assert_not_called()
        self.reply({"id": "job-1"})
        controller._job._timer.stop()
        self.reply(True)
        controller._dialog.done.assert_not_called()
        controller._job._poll()
        self.reply({"id": "job-1", "kind": "update.download", "state": "cancelled"})
        controller._dialog.done.assert_called_once_with(QDialog.Rejected)

    def test_large_download_progress_does_not_overflow_qt_int(self):
        progress = Mock()
        self.job.progress.connect(progress)
        self.start("update.download")
        self.reply(
            {
                "id": "job-1",
                "kind": "update.download",
                "state": "running",
                "progress": {"received": 3 * 1024**3, "total": 4 * 1024**3},
            }
        )
        progress.assert_called_once_with(3 * 1024**3, 4 * 1024**3)

    def test_install_only_quits_after_verified_ready(self):
        controller = CliUpdateController(self.session)
        controller._dialog = Mock()
        controller._operation = "install"
        with patch("gui.controllers.cli_update.QApplication.instance") as application:
            controller._finished({"version": "2.0", "ready": False})
            application.return_value.quit.assert_not_called()
            controller._dialog.accept.assert_not_called()
            controller._finished({"version": "2.0", "ready": True})
            controller._dialog.accept.assert_called_once()
            application.return_value.quit.assert_called_once()

    def test_update_error_requires_fresh_check_and_download_sends_no_url(self):
        controller = CliUpdateController(self.session)
        controller._dialog = Mock()
        controller._next_operation = "download"
        controller._advance()
        self.assertEqual(self.transport.requests, [("update.download", {})])
        self.transport.failed.emit(1, CliFailure(-32002, "failed"))
        self.assertEqual(controller._next_operation, "check")
        self.assertTrue(self.session.usable)
        self.assertFalse(self.session.busy)
        self.factory.assert_not_called()
        controller._advance()
        self.assertEqual(self.transport.requests[-1], ("update.view", {}))

    def test_plan_unknown_state_remains_explicit_and_invalid_payloads_fail(self):
        value = {
            "plan": asdict(DailyPlanOptions()),
            "state": None,
            "state_error": "access denied",
            "supported": True,
            "shutdown_supported": True,
        }
        plan, _ = parse_plan_view(value)
        self.assertEqual(plan, DailyPlanOptions())
        value["state_error"] = None
        with self.assertRaises(ValueError):
            parse_plan_view(value)
        for validator, payload in (
            (validate_run_target, {}),
            (
                lambda value: validate_backup_result(value, "restore.start"),
                {"restored": True, "skipped_scripts": []},
            ),
            (lambda value: validate_update_result(value, "install"), {"ready": True}),
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                validator(payload)
