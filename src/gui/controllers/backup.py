"""配置备份控制器：一键备份自身配置与各子脚本 config。

独立 QObject，只做「调 service + 结果 toast」，不承载备份逻辑。
"""

from PySide6.QtCore import QObject, Signal, Slot

from src.service.app_service import AppService


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
