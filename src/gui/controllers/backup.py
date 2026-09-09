"""配置备份 / 恢复控制器：一键打包与一键还原。

独立 QObject，只做「弹窗选文件 + 调 service + 结果 toast」，不承载备份逻辑。
"""

import os

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QFileDialog

from src.service.app_service import AppService
from src.utils import get_root_dir

_FILTER = "配置备份 (*.zip)"


class BackupController(QObject):
    toastRequested = Signal(str)

    def __init__(self, app_service=None, toast=None, parent=None):
        super().__init__(parent)
        self._app_service = app_service or AppService()
        self._toast = toast or (lambda _msg: None)

    @Slot()
    def backupConfig(self):
        """一键打包配置并 toast 产物路径。

        磁盘满 / 权限不足等 OSError 从 QML 槽逃逸即崩，故在此收口为 toast。
        """
        try:
            path = self._app_service.create_backup()
        except OSError as exc:
            self._toast(f"备份失败：{exc}")
            return
        self._toast(f"配置已备份：{path}")

    def _pick_zip(self) -> str:
        """弹系统文件选择框选备份 zip（默认定位 config/backups）；取消返回空串。"""
        path, _selected = QFileDialog.getOpenFileName(
            None,
            "选择配置备份",
            os.path.join(get_root_dir(), "config", "backups"),
            _FILTER,
        )
        return path

    @Slot()
    def restoreConfig(self):
        """选一个备份 zip 恢复；已设置过的游戏路径保留现值。

        恢复会覆盖现有配置，失败（zip 损坏 / 磁盘 / 权限）从 QML 槽逃逸即崩，
        故在此收口为 toast。
        """
        zip_path = self._pick_zip()
        if not zip_path:
            return  # 用户取消
        try:
            result = self._app_service.restore_backup(zip_path)
        except (OSError, AssertionError, KeyError, ValueError) as exc:
            self._toast(f"恢复失败：{exc}")
            return
        kept = result["game_path_kept"]
        suffix = f"（保留游戏路径 {kept} 处）" if kept else ""
        self._toast(f"已恢复 {result['restored']} 个文件{suffix}")
