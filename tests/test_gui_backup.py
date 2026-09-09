"""测试 src/gui/controllers/backup.py：一键备份 / 恢复的 GUI 动作。"""

import unittest
from unittest.mock import MagicMock, patch

from src.gui.controllers.backup import BackupController


class TestBackupConfig(unittest.TestCase):
    def _make_controller(self, create_backup):
        svc = MagicMock()
        svc.create_backup.side_effect = create_backup
        toast = MagicMock()
        return BackupController(app_service=svc, toast=toast), svc, toast

    def test_toasts_backup_path(self):
        """备份成功：toast 产物路径。"""
        ctrl, svc, toast = self._make_controller(lambda: "C:/odh/config/backups/b.zip")
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
            lambda _zip: {"restored": 46, "game_path_kept": 0, "pre_backup": "x.zip"}
        )
        svc.restore_backup.assert_called_once_with("C:/odh/config/backups/b.zip")
        toast.assert_called_once_with("已恢复 46 个文件")

    def test_toasts_kept_game_paths(self):
        """保留了游戏路径时 toast 带出保留处数。"""
        _svc, toast = self._run(
            lambda _zip: {"restored": 46, "game_path_kept": 3, "pre_backup": "x.zip"}
        )
        toast.assert_called_once_with("已恢复 46 个文件（保留游戏路径 3 处）")

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


if __name__ == "__main__":
    unittest.main()
