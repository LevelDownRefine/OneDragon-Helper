"""备份与恢复通过 CLI 后台任务执行，恢复明确确认且不自动重试。"""

from PySide6.QtWidgets import QDialog, QLabel, QMessageBox, QVBoxLayout

from gui.cli_job import CliJob
from gui.dialogs import FormDialogBase, styled_msg_box


class JobDialog(FormDialogBase):
    def __init__(self, title):
        super().__init__()
        self.setWindowTitle(title)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(title + "，请等待完成…", self))
        self.set_pending(True)


class CliBackupMixin:
    def backupConfig(self):
        self._backup_job("backup.start", {})

    def restoreConfig(self):
        if self._session.busy:
            self._toast("已有后台操作，请稍候")
            return
        path = self._pick_zip()
        if not path:
            return
        box = styled_msg_box(
            None,
            QMessageBox.Warning,
            "恢复配置",
            "恢复将覆盖现有配置，并保留本机游戏路径。是否继续？",
        )
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.No)
        if box.exec() == QMessageBox.Yes:
            self._backup_job("restore.start", {"zip_path": path, "confirmed": True})

    def _backup_job(self, method, params):
        if self._session.busy:
            self._toast("已有后台操作，请稍候")
            return
        dialog = JobDialog("配置备份" if method == "backup.start" else "恢复配置")
        job = CliJob(self._session, self)

        def failed(failure):
            dialog.set_pending(False)
            dialog.done(QDialog.Rejected)
            self._toast(failure.message)

        def succeeded(value):
            dialog.set_pending(False)
            dialog.accept()
            try:
                validate_backup_result(value, method)
            except ValueError as exc:
                self._toast(str(exc) + "；操作结果不确定，请核对文件后再操作")
                return
            if method == "backup.start":
                self._toast(f"配置已备份：{value['path']}")
            else:
                if value["restored"]:
                    self.restoreCompleted.emit()
                message = f"已恢复 {value['restored']} 个文件"
                if value["skipped_scripts"]:
                    message += "；未配置目录，已跳过：" + "、".join(
                        value["skipped_scripts"]
                    )
                self._toast(message + "；本机游戏路径保持不变")

        job.succeeded.connect(succeeded)
        job.failed.connect(failed)
        dialog.show()
        job.start(method, params)
        if job.active:
            dialog.exec()
        job.deleteLater()
        dialog.deleteLater()


def validate_backup_result(value, method):
    if not isinstance(value, dict):
        raise ValueError("备份恢复结果无效")
    if method == "backup.start":
        if (
            "path" not in value
            or not isinstance(value["path"], str)
            or not value["path"]
        ):
            raise ValueError("备份路径无效")
    elif (
        "restored" not in value
        or type(value["restored"]) is not int
        or value["restored"] < 0
        or "skipped_scripts" not in value
        or not isinstance(value["skipped_scripts"], list)
        or not all(isinstance(name, str) for name in value["skipped_scripts"])
    ):
        raise ValueError("恢复结果无效")
