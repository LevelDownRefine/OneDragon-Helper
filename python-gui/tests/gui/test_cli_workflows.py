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
        controller = CliSettingsController(Mock(), self.session, Mock())
        controller._pick_zip = Mock(return_value="backup.zip")
        with patch("gui.controllers.cli_backup.styled_msg_box") as box:
            box.return_value.exec.return_value = 0
            controller.restoreConfig()
        self.assertEqual(self.transport.requests, [])

    def test_confirmed_restore_passes_same_wire_parameters_as_rust(self):
        controller = CliSettingsController(Mock(), self.session, Mock())
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
        self.transport.running = False
        self.transport.closed.emit()

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
