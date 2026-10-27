"""设置表单与备份恢复只通过 CLI 提交；成功回执决定关闭和刷新。"""

import unittest
from dataclasses import asdict
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QDialog, QMessageBox

from gui.cli_client import CliFailure
from gui.controllers.cli_settings import CliSettingsController
from src.service.schedule import RunOptions, StartupOptions
from tests.gui.helpers import get_app
from tests.gui.rpc_test_support import RpcHarness


def settings_view():
    return {
        "startup": asdict(StartupOptions()),
        "daily_enabled": False,
        "run_options": asdict(RunOptions()),
        "shutdown_supported": True,
    }


class TestOpenConfig(unittest.TestCase):
    def setUp(self):
        get_app()
        self.rpc = RpcHarness()
        self.toast = Mock()
        self.ctrl = CliSettingsController(self.rpc.session, self.toast)
        self.addCleanup(self.rpc.session.detach)

    def open_dialog(self, action=None):
        dialog = Mock()
        dialog.startup_options = StartupOptions(False, 125)
        dialog.isVisible.return_value = True
        dialog.exec.side_effect = action
        with patch("gui.controllers.cli_settings.ConfigDialog", return_value=dialog):
            self.ctrl.openConfig()
            self.assertEqual(self.rpc.requests[-1], ("settings.view", {}))
            self.rpc.reply(settings_view())
        return dialog

    def test_cancel_does_not_save_any_settings(self):
        dialog = self.open_dialog()
        self.assertEqual(self.rpc.requests, [("settings.view", {})])
        dialog.accept.assert_not_called()

    def test_save_preferences_waits_for_rpc_ack(self):
        dialog = self.open_dialog()
        dialog.saveRequested.connect.call_args.args[0]()
        self.assertEqual(
            self.rpc.requests[-1],
            ("settings.startup_save", {"options": asdict(StartupOptions(False, 125))}),
        )
        dialog.accept.assert_not_called()
        self.rpc.reply(None)
        dialog.accept.assert_called_once_with()
        self.toast.assert_called_once_with("启动设置已保存")

    def test_menu_dispatch_does_not_save_pending_preferences(self):
        dialog = self.open_dialog()
        dispatch = dialog.actionRequested.connect.call_args.args[0]
        for action in ("backup", "restore", "settings", "daily", "update"):
            with (
                self.subTest(action=action),
                patch.object(self.ctrl, "backupConfig") as backup,
                patch.object(self.ctrl, "restoreConfig") as restore,
                patch.object(self.ctrl, "configureRunOptions") as settings,
                patch.object(self.ctrl.daily_plan, "edit") as daily,
                patch.object(self.ctrl.update, "open") as update,
            ):
                # openConfig 捕获的是当前方法；为每轮重新创建菜单。
                dialog = self.open_dialog()
                dispatch = dialog.actionRequested.connect.call_args.args[0]
                dispatch(action)
                calls = {
                    "backup": backup,
                    "restore": restore,
                    "settings": settings,
                    "daily": daily,
                    "update": update,
                }
                calls[action].assert_called_once_with(
                    *([dialog] if action == "update" else [])
                )
        self.assertTrue(
            all(method == "settings.view" for method, _ in self.rpc.requests)
        )

    def test_save_failure_keeps_dialog_and_allows_retry(self):
        dialog = self.open_dialog()
        save = dialog.saveRequested.connect.call_args.args[0]
        save()
        self.rpc.fail("locked")
        dialog.show_error.assert_called_once_with("locked")
        dialog.accept.assert_not_called()
        self.assertEqual(dialog.startup_options, StartupOptions(False, 125))
        self.toast.assert_not_called()
        save()
        self.rpc.reply(None)
        dialog.accept.assert_called_once_with()

    def test_read_failure_is_reported_without_opening_dialog(self):
        with patch("gui.controllers.cli_settings.ConfigDialog") as dialog:
            self.ctrl.openConfig()
            self.rpc.fail("locked")
        dialog.assert_not_called()
        self.toast.assert_called_once_with("locked")
        self.assertFalse(self.ctrl._opening)

    def test_run_settings_can_be_saved_without_launch(self):
        dialog = Mock()
        dialog.run_options = RunOptions(mute_enabled=True)
        with patch(
            "gui.controllers.cli_settings.RunConfirmDialog", return_value=dialog
        ) as create:
            self.ctrl.configureRunOptions()
            self.rpc.reply(settings_view())
        create.call_args.kwargs["submit"](dialog)
        self.assertEqual(
            self.rpc.requests[-1],
            ("settings.run_save", {"options": asdict(dialog.run_options)}),
        )
        dialog.accept.assert_not_called()
        self.rpc.reply(None)
        dialog.accept.assert_called_once_with()
        self.assertFalse(
            any(method.startswith("run.") for method, _ in self.rpc.requests)
        )


class TestBackupAndRestore(unittest.TestCase):
    def setUp(self):
        get_app()
        self.rpc = RpcHarness()
        self.toast = Mock()
        self.ctrl = CliSettingsController(self.rpc.session, self.toast)
        self.completed = Mock()
        self.ctrl.restoreCompleted.connect(self.completed)
        self.addCleanup(self.rpc.session.detach)

    def start(self, method, params=None):
        job = Mock(active=False)
        with (
            patch("gui.controllers.cli_backup.CliJob", return_value=job),
            patch("gui.controllers.cli_backup.JobDialog") as dialog,
        ):
            self.ctrl._backup_job(method, {} if params is None else params)
        job.start.assert_called_once_with(method, {} if params is None else params)
        return job, dialog.return_value

    def succeed(self, job, result):
        job.succeeded.connect.call_args.args[0](result)

    def test_backup_toasts_result_only_after_success(self):
        job, dialog = self.start("backup.start")
        self.toast.assert_not_called()
        self.succeed(job, {"path": "C:/odh/config/backups/b.zip"})
        dialog.accept.assert_called_once_with()
        self.toast.assert_called_once_with("配置已备份：C:/odh/config/backups/b.zip")

    def test_backup_failure_toasts_without_success(self):
        job, dialog = self.start("backup.start")
        job.failed.connect.call_args.args[0](CliFailure("job_failed", "磁盘空间不足"))
        dialog.accept.assert_not_called()
        dialog.done.assert_called_once_with(QDialog.Rejected)
        self.toast.assert_called_once_with("磁盘空间不足")

    def test_restore_requires_selection_and_confirmation(self):
        with (
            patch.object(self.ctrl, "_pick_zip", return_value=""),
            patch.object(self.ctrl, "_backup_job") as start,
        ):
            self.ctrl.restoreConfig()
            start.assert_not_called()
        for answer, submitted in ((QMessageBox.No, False), (QMessageBox.Yes, True)):
            with (
                self.subTest(answer=answer),
                patch.object(self.ctrl, "_pick_zip", return_value="picked.zip"),
                patch("gui.controllers.cli_backup.styled_msg_box") as box,
                patch.object(self.ctrl, "_backup_job") as start,
            ):
                box.return_value.exec.return_value = answer
                self.ctrl.restoreConfig()
                if submitted:
                    start.assert_called_once_with(
                        "restore.start", {"zip_path": "picked.zip", "confirmed": True}
                    )
                else:
                    start.assert_not_called()
        self.toast.assert_not_called()

    def test_restore_success_reports_skips_and_refreshes(self):
        job, _dialog = self.start(
            "restore.start", {"zip_path": "picked.zip", "confirmed": True}
        )
        self.succeed(job, {"restored": 46, "skipped_scripts": ["second"]})
        self.completed.assert_called_once_with()
        self.toast.assert_called_once_with(
            "已恢复 46 个文件；未配置目录，已跳过：second；本机游戏路径保持不变"
        )

    def test_all_skipped_does_not_emit_completion(self):
        job, _dialog = self.start("restore.start")
        self.succeed(job, {"restored": 0, "skipped_scripts": ["first", "second"]})
        self.completed.assert_not_called()
        self.assertIn(
            "已恢复 0 个文件；未配置目录，已跳过：first、second",
            self.toast.call_args.args[0],
        )

    def test_failed_or_malformed_restore_never_emits_completion(self):
        # 损坏 ZIP 的业务拒绝由后端测试覆盖；GUI 只展示失败响应。
        job, _dialog = self.start("restore.start")
        job.failed.connect.call_args.args[0](
            CliFailure("job_failed", "恢复失败：zip 损坏")
        )
        self.completed.assert_not_called()
        self.assertEqual(self.toast.call_args.args[0], "恢复失败：zip 损坏")
        for result in ({}, {"restored": -1, "skipped_scripts": []}):
            with self.subTest(result=result):
                job, _dialog = self.start("restore.start")
                self.succeed(job, result)
                self.completed.assert_not_called()
                self.assertIn("操作结果不确定", self.toast.call_args.args[0])

    def test_busy_restore_does_not_pick_or_submit(self):
        self.assertTrue(self.rpc.session.hold())
        with patch.object(self.ctrl, "_pick_zip") as pick:
            self.ctrl.restoreConfig()
        pick.assert_not_called()
        self.assertEqual(self.rpc.requests, [])
        self.assertIn("已有后台操作", self.toast.call_args.args[0])
        self.rpc.session.release()
