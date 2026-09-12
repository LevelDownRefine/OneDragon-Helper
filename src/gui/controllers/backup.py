"""配置备份 / 恢复控制器：一键打包与一键还原。

独立 QObject，只做「弹窗选文件 + 调 service + 结果 toast」，不承载备份逻辑。
"""

import logging
import os
import zipfile

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QDialog, QFileDialog
from ruamel.yaml.error import YAMLError

from src.gui.config_dialog import ConfigDialog
from src.gui.controllers.daily_plan import DailyPlanController
from src.gui.run_confirm_dialog import RunConfirmDialog
from src.service.app_service import AppService
from src.utils import get_root_dir

_FILTER = "配置备份 (*.zip)"
logger = logging.getLogger(__name__)


class BackupController(QObject):
    toastRequested = Signal(str)
    restoreCompleted = Signal()

    def __init__(self, app_service=None, toast=None, parent=None):
        super().__init__(parent)
        self._app_service = app_service or AppService()
        self._toast = toast or (lambda _msg: None)
        self.daily_plan = DailyPlanController(self._app_service, self._toast, self)

    @Slot()
    def openConfig(self):
        """菜单操作独立打开，启动设置仅点击保存后落盘。"""
        try:
            options = self._app_service.load_startup_options()
            daily_plan = self._app_service.load_daily_plan()
        except (OSError, YAMLError) as exc:
            logger.error("读取启动设置失败：%s: %s", type(exc).__name__, exc)
            self._toast(f"读取启动设置失败：{exc}")
            return
        dialog = ConfigDialog(startup_options=options, daily_plan=daily_plan)
        actions = {
            "daily": self.daily_plan.edit,
            "backup": self.backupConfig,
            "restore": self.restoreConfig,
            "settings": self.configureRunOptions,
        }

        def dispatch(action):
            assert action in actions
            actions[action]()
            if action == "daily":
                self.daily_plan.refresh()
                dialog.set_daily_plan_enabled(self.daily_plan.plan.enabled)

        def save():
            updated = dialog.startup_options
            if updated != options:
                try:
                    self._app_service.apply_startup_options(updated)
                except (OSError, YAMLError) as exc:
                    logger.error("保存启动设置失败：%s: %s", type(exc).__name__, exc)
                    dialog.show_error(f"保存失败：{exc}")
                    return
            dialog.accept()
            self._toast("启动设置已保存")

        dialog.actionRequested.connect(dispatch)
        dialog.saveRequested.connect(save)
        dialog.exec()

    def configureRunOptions(self):
        """保存共用运行选项，不启动脚本。"""
        try:
            dialog = RunConfirmDialog(
                0, self._app_service.load_run_options(), settings_only=True
            )
            if dialog.exec() != QDialog.Accepted:
                return
            assert dialog.run_options is not None
            self._app_service.apply_run_options(dialog.run_options)
        except (OSError, YAMLError) as exc:
            logger.error("保存运行选项失败：%s: %s", type(exc).__name__, exc)
            self._toast(f"保存运行选项失败：{exc}")
            return
        self._toast("运行选项已保存，下次运行生效")

    @Slot()
    def backupConfig(self):
        """一键打包配置并 toast 产物路径。

        磁盘满 / 权限不足等 OSError 从 QML 槽逃逸即崩，故在此收口为 toast。
        """
        try:
            result = self._app_service.create_backup()
        except (OSError, ValueError, zipfile.LargeZipFile) as exc:
            logger.error("[backup] 备份失败：%s: %s", type(exc).__name__, exc)
            self._toast(f"备份失败：{exc}")
            return
        assert "path" in result
        self._toast(f"配置已备份：{result['path']}")

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
        """选一个 ZIP，按当前脚本目录恢复配置，保留本机游戏路径。

        恢复会覆盖现有配置，失败（zip 损坏 / 磁盘 / 权限）从 QML 槽逃逸即崩，
        故在此收口为 toast。
        """
        zip_path = self._pick_zip()
        if not zip_path:
            return  # 用户取消
        try:
            result = self._app_service.restore_backup(zip_path)
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            logger.error("[backup] 恢复失败：%s: %s", type(exc).__name__, exc)
            self._toast(f"恢复失败：{exc}")
            return
        assert "skipped_scripts" in result and "restored" in result
        if result["restored"]:
            self.restoreCompleted.emit()
        message = f"已恢复 {result['restored']} 个文件"
        if result["skipped_scripts"]:
            message += f"；未配置目录，已跳过：{'、'.join(result['skipped_scripts'])}"
        if result["restored"]:
            message += "；本机游戏路径保持不变"
        self._toast(message)
