"""测试 src/gui/controllers/backup.py：一键备份的 GUI 动作。"""

import unittest
from unittest.mock import MagicMock

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


if __name__ == "__main__":
    unittest.main()
