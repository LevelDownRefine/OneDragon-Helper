"""测试 src/gui/controllers/backup.py：一键备份 / 恢复的 GUI 动作。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QDialog

from src.gui.controllers.backup import BackupController
from src.service.daily_plan import DailyPlanOptions
from src.service.schedule import StartupOptions


class TestOpenConfig(unittest.TestCase):
    def setUp(self):
        self.service = MagicMock()
        self.service.load_startup_options.return_value = StartupOptions()
        self.service.load_daily_plan.return_value = DailyPlanOptions()
        self.toast = MagicMock()
        self.ctrl = BackupController(app_service=self.service, toast=self.toast)

    @patch("src.gui.controllers.backup.ConfigDialog")
    def test_cancel_does_not_save_any_settings(self, dialog_class):
        dialog = dialog_class.return_value
        dialog.exec.return_value = QDialog.Rejected
        dialog.startup_options = StartupOptions(False, 125)
        self.ctrl.openConfig()
        self.service.apply_startup_options.assert_not_called()
        self.service.apply_daily_plan.assert_not_called()

    @patch("src.gui.controllers.backup.ConfigDialog")
    def test_save_preferences_through_service(self, dialog_class):
        dialog = dialog_class.return_value
        dialog.startup_options = StartupOptions(False, 125)
        dialog.exec.side_effect = lambda: dialog.saveRequested.connect.call_args.args[
            0
        ]()
        self.ctrl.openConfig()
        self.service.apply_startup_options.assert_called_once_with(
            StartupOptions(False, 125)
        )
        dialog.accept.assert_called_once_with()
        self.service.apply_daily_plan.assert_not_called()

    @patch("src.gui.controllers.backup.ConfigDialog")
    def test_menu_dispatch_does_not_save_pending_preferences(self, dialog_class):
        dialog = dialog_class.return_value
        dialog.startup_options = StartupOptions(False, 125)
        for action in ("backup", "restore", "settings", "daily"):
            with (
                self.subTest(action=action),
                patch.object(self.ctrl, "backupConfig") as backup,
                patch.object(self.ctrl, "restoreConfig") as restore,
                patch.object(self.ctrl, "configureRunOptions") as settings,
                patch.object(self.ctrl.daily_plan, "edit") as daily,
            ):
                dialog.exec.side_effect = lambda chosen=action: (
                    dialog.actionRequested.connect.call_args.args[0](chosen)
                )
                self.ctrl.openConfig()
                calls = {
                    "backup": backup,
                    "restore": restore,
                    "settings": settings,
                    "daily": daily,
                }
                calls[action].assert_called_once_with()
                self.service.apply_startup_options.assert_not_called()

    @patch("src.gui.controllers.backup.ConfigDialog")
    def test_save_failure_keeps_dialog_and_input(self, dialog_class):
        dialog = dialog_class.return_value
        dialog.startup_options = StartupOptions(False, 30)
        dialog.exec.side_effect = lambda: dialog.saveRequested.connect.call_args.args[
            0
        ]()
        self.service.apply_startup_options.side_effect = OSError("locked")
        with self.assertLogs("src.gui.controllers.backup", level="ERROR"):
            self.ctrl.openConfig()
        dialog.show_error.assert_called_once_with("保存失败：locked")
        dialog.accept.assert_not_called()
        self.toast.assert_not_called()

    @patch("src.gui.controllers.backup.ConfigDialog")
    def test_read_failure_is_reported(self, dialog_class):
        self.service.load_startup_options.side_effect = OSError("locked")
        with self.assertLogs("src.gui.controllers.backup", level="ERROR"):
            self.ctrl.openConfig()
        dialog_class.assert_not_called()
        self.toast.assert_called_once_with("读取启动设置失败：locked")

    @patch("src.gui.controllers.backup.RunConfirmDialog")
    def test_run_settings_can_be_saved_without_launch(self, dialog_class):
        dialog = dialog_class.return_value
        dialog.exec.return_value = QDialog.Accepted
        self.ctrl.configureRunOptions()
        self.service.apply_run_options.assert_called_once_with(dialog.run_options)
        self.service.schedule_run.assert_not_called()


class TestBackupConfig(unittest.TestCase):
    def _make_controller(self, create_backup):
        svc = MagicMock()
        svc.create_backup.side_effect = create_backup
        toast = MagicMock()
        return BackupController(app_service=svc, toast=toast), svc, toast

    def test_toasts_backup_path(self):
        """备份成功：toast 产物路径。"""
        ctrl, svc, toast = self._make_controller(
            lambda: {"path": "C:/odh/config/backups/b.zip", "file_count": 2}
        )
        ctrl.backupConfig()
        svc.create_backup.assert_called_once_with()
        toast.assert_called_once_with("配置已备份：C:/odh/config/backups/b.zip")

    def test_os_error_toasts_failure(self):
        """磁盘/权限失败：转 toast，不从 QML 槽逃逸。"""
        ctrl, _svc, toast = self._make_controller(
            lambda: (_ for _ in ()).throw(OSError("磁盘空间不足"))
        )
        ctrl.backupConfig()
        toast.assert_called_once_with("备份失败：磁盘空间不足")


class TestRestoreConfig(unittest.TestCase):
    def _make_controller(self, restore_backup):
        svc = MagicMock()
        svc.restore_backup.side_effect = restore_backup
        toast = MagicMock()
        return BackupController(app_service=svc, toast=toast), svc, toast

    def _run(self, restore_backup, picked="C:/odh/config/backups/b.zip"):
        ctrl, svc, toast = self._make_controller(restore_backup)
        with patch.object(ctrl, "_pick_zip", return_value=picked):
            ctrl.restoreConfig()
        return svc, toast

    def test_restores_picked_zip_and_toasts(self):
        """选中 zip：调 service 恢复并 toast 恢复文件数。"""
        svc, toast = self._run(
            lambda _zip: {"restored": 46, "skipped_scripts": [], "pre_backup": "x.zip"}
        )
        svc.restore_backup.assert_called_once_with("C:/odh/config/backups/b.zip")
        toast.assert_called_once_with("已恢复 46 个文件；本机游戏路径保持不变")

    def test_toasts_skipped_scripts(self):
        """跳过未配置目录的脚本时列出名称。"""
        _svc, toast = self._run(
            lambda _zip: {
                "restored": 46,
                "skipped_scripts": ["second"],
                "pre_backup": "x.zip",
            }
        )
        toast.assert_called_once_with(
            "已恢复 46 个文件；未配置目录，已跳过：second；本机游戏路径保持不变"
        )

    def test_cancel_pick_does_nothing(self):
        """选择框取消 → 不调 service、不 toast。"""
        _svc, toast = self._run(lambda _zip: {}, picked="")
        toast.assert_not_called()

    def test_failure_toasts(self):
        """zip 损坏 / 磁盘失败：转 toast，不从 QML 槽逃逸。"""

        def boom(_zip):
            raise OSError("zip 损坏")

        _svc, toast = self._run(boom)
        toast.assert_called_once_with("恢复失败：zip 损坏")

    def test_real_broken_zip_toasts_without_success_signal(self):
        from src.service.app_service import AppService

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "broken.zip")
            path.write_bytes(b"not a zip")
            toast = MagicMock()
            ctrl = BackupController(app_service=AppService(), toast=toast)
            completed = MagicMock()
            ctrl.restoreCompleted.connect(completed)
            with patch.object(ctrl, "_pick_zip", return_value=str(path)):
                ctrl.restoreConfig()
            self.assertIn("恢复失败", toast.call_args.args[0])
            completed.assert_not_called()

    def test_completion_signal_only_after_success(self):
        ctrl, svc, _toast = self._make_controller(
            lambda _zip: {"restored": 1, "skipped_scripts": []}
        )
        completed = MagicMock()
        ctrl.restoreCompleted.connect(completed)
        with patch.object(ctrl, "_pick_zip", return_value="picked.zip"):
            ctrl.restoreConfig()
        completed.assert_called_once_with()
        completed.reset_mock()
        svc.restore_backup.side_effect = OSError("locked")
        with patch.object(ctrl, "_pick_zip", return_value="picked.zip"):
            ctrl.restoreConfig()
        completed.assert_not_called()
        with patch.object(ctrl, "_pick_zip", return_value=""):
            ctrl.restoreConfig()
        completed.assert_not_called()

    def test_all_skipped_does_not_emit_completion(self):
        ctrl, _svc, toast = self._make_controller(
            lambda _zip: {"restored": 0, "skipped_scripts": ["first", "second"]}
        )
        completed = MagicMock()
        ctrl.restoreCompleted.connect(completed)
        with patch.object(ctrl, "_pick_zip", return_value="picked.zip"):
            ctrl.restoreConfig()
        completed.assert_not_called()
        toast.assert_called_once_with(
            "已恢复 0 个文件；未配置目录，已跳过：first、second"
        )


if __name__ == "__main__":
    unittest.main()
