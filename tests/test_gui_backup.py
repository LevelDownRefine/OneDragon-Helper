"""测试 src/gui/controllers/backup.py：一键备份 / 恢复的 GUI 动作。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QDialog

from src.gui.controllers.backup import BackupController


class TestOpenConfig(unittest.TestCase):
    @patch("src.gui.controllers.backup.ConfigDialog")
    def test_selection_dispatches_after_dialog_closes(self, dialog_class):
        ctrl = BackupController(app_service=MagicMock(), toast=MagicMock())
        dialog = dialog_class.return_value
        events = []
        for selected in ("backup", "restore"):
            with self.subTest(action=selected):
                dialog.selected_action = selected
                events.clear()

                def close_dialog():
                    events.append("closed")
                    return QDialog.Accepted

                dialog.exec.side_effect = close_dialog
                with (
                    patch.object(
                        ctrl,
                        "backupConfig",
                        side_effect=lambda: events.append("backup"),
                    ),
                    patch.object(
                        ctrl,
                        "restoreConfig",
                        side_effect=lambda: events.append("restore"),
                    ),
                ):
                    ctrl.openConfig()
                self.assertEqual(events, ["closed", selected])

    @patch("src.gui.controllers.backup.ConfigDialog")
    def test_cancel_does_not_dispatch(self, dialog_class):
        ctrl = BackupController(app_service=MagicMock(), toast=MagicMock())
        dialog_class.return_value.exec.return_value = QDialog.Rejected
        with (
            patch.object(ctrl, "backupConfig") as backup,
            patch.object(ctrl, "restoreConfig") as restore,
        ):
            ctrl.openConfig()
        backup.assert_not_called()
        restore.assert_not_called()


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
