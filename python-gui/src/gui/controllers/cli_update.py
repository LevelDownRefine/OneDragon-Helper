"""更新使用 CLI 会话持有的发布信息和后台任务，不接收客户端安装路径。"""

from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QDialog

from gui.cli_job import CliJob
from gui.update_dialog import UpdateDialog
from src.update.service import RELEASES_URL


class CliUpdateController(QObject):
    def __init__(self, session, parent=None):
        super().__init__(parent)
        self._session = session
        self._dialog = None
        self._next_operation = "check"
        self._operation = "check"
        self._close_pending = False
        self._job = CliJob(session, self)
        self._job.progress.connect(self._progress)
        self._job.succeeded.connect(self._finished)
        self._job.failed.connect(self._failed)
        self._job.cancelled.connect(self._cancelled)

    def open(self, parent=None):
        if self._dialog is not None:
            self._dialog.raise_()
            self._dialog.activateWindow()
            return
        self._dialog = UpdateDialog()
        self._close_pending = False
        self._next_operation = "check"
        self._dialog.actionRequested.connect(self._advance)
        self._dialog.closeRequested.connect(self._close)
        self._dialog.releasesRequested.connect(self._open_releases)
        self._dialog.finished.connect(self._dialog_finished)
        self._dialog.show()
        self._check()

    def _check(self):
        dialog = self._dialog
        self._dialog.show_state("checking", "正在读取更新信息…")

        def loaded(value):
            validate_update_view(value)
            if self._dialog is not dialog:
                return
            if self._close_pending:
                self._dialog.done(QDialog.Rejected)
                return
            self._dialog.version_label.setText(f"当前版本：{value['version']}")
            previous = value["previous_result"]
            self._dialog.previous_label.setVisible(previous is not None)
            if previous is not None:
                messages = {
                    "installed": "上次更新已安装完成。",
                    "recovered": "上次更新已恢复到旧版本。",
                    "failed": "上次更新未完成。",
                    "restart_failed": "上次更新已安装，请手动重新打开助手。",
                }
                text = messages[previous["status"]]
                if "error" in previous:
                    text += "\n" + previous["error"]
                self._dialog.previous_label.setText(text)
            if value["unavailable_reason"]:
                self._dialog.show_state("unsupported", value["unavailable_reason"])
            elif value["handoff_ready"]:
                self._dialog.show_state(
                    "error", "安装已交接，请关闭助手并等待更新器完成"
                )
            else:
                self._start("check")

        self._session.call("update.view", {}, loaded, self._failed)

    def _advance(self):
        if self._job.active or self._session.busy:
            return
        if self._next_operation == "check":
            self._check()
        else:
            self._start(self._next_operation)

    def _start(self, operation):
        if self._session.busy:
            self._dialog.show_state("error", "已有后台操作，请结束后重试")
            return
        states = {
            "check": ("checking", "正在检查新版本…"),
            "download": ("downloading", "正在下载更新，可随时取消。"),
            "install": ("installing", "正在准备安装，助手即将关闭并重启…"),
        }
        assert operation in states
        self._operation = operation
        self._dialog.show_state(*states[operation])
        self._job.start("update." + operation)

    def _progress(self, received, total):
        if self._dialog is not None and not self._close_pending:
            self._dialog.show_progress(received, total)

    def _finished(self, value):
        try:
            validate_update_result(value, self._operation)
        except ValueError as exc:
            from gui.cli_client import CliFailure

            self._failed(CliFailure("invalid_response", str(exc)))
            return
        if self._close_pending:
            self._dialog.done(QDialog.Rejected)
        elif self._operation == "check":
            release = value["release"]
            if release is None:
                self._next_operation = "check"
                self._dialog.show_state("current", "当前已是最新版本。")
            else:
                self._next_operation = "download"
                self._dialog.notes.setPlainText(
                    release["notes"] or "此版本未提供更新说明。"
                )
                self._dialog.notes.show()
                self._dialog.show_state("available", f"发现新版本 {release['version']}")
        elif self._operation == "download":
            self._next_operation = "install"
            self._dialog.show_state(
                "ready", "下载与校验完成。安装时将关闭助手，完成后重新打开。"
            )
        else:
            self._dialog.accept()
            QApplication.instance().quit()

    def _failed(self, failure):
        self._next_operation = "check"
        if self._dialog is None:
            return
        if self._close_pending:
            self._dialog.done(QDialog.Rejected)
        else:
            self._dialog.show_state("error", failure.message)

    def _close(self):
        if self._job.active:
            if self._job.cancel():
                self._close_pending = True
                self._dialog.show_state("cancelling", "正在取消，请等待当前操作结束…")
        else:
            self._dialog.done(QDialog.Rejected)

    def _cancelled(self):
        self._next_operation = "check"
        self._dialog.done(QDialog.Rejected)

    def _dialog_finished(self):
        assert not self._job.active
        dialog = self._dialog
        self._dialog = None
        dialog.deleteLater()

    def _open_releases(self):
        if not QDesktopServices.openUrl(QUrl(RELEASES_URL)):
            self._dialog.status_label.setText("无法打开浏览器，请稍后重试。")


def validate_release(value):
    if value is None:
        return
    if (
        not isinstance(value, dict)
        or not all(
            key in value and isinstance(value[key], str) for key in ("version", "notes")
        )
        or "size" not in value
        or type(value["size"]) is not int
        or value["size"] < 0
    ):
        raise ValueError("发布信息无效")


def validate_update_view(value):
    if (
        not isinstance(value, dict)
        or not all(
            key in value
            for key in (
                "version",
                "unavailable_reason",
                "previous_result",
                "releases_url",
                "release",
                "prepared_version",
                "handoff_ready",
            )
        )
        or not all(
            isinstance(value[key], str)
            for key in ("version", "unavailable_reason", "releases_url")
        )
        or type(value["handoff_ready"]) is not bool
        or (
            value["prepared_version"] is not None
            and not isinstance(value["prepared_version"], str)
        )
    ):
        raise ValueError("更新信息无效")
    validate_release(value["release"])
    previous = value["previous_result"]
    if previous is not None and (
        not isinstance(previous, dict)
        or "status" not in previous
        or not isinstance(previous["status"], str)
        or previous["status"]
        not in {"installed", "recovered", "failed", "restart_failed"}
        or ("error" in previous and not isinstance(previous["error"], str))
    ):
        raise ValueError("上次更新状态无效")


def validate_update_result(value, operation):
    if not isinstance(value, dict):
        raise ValueError("更新结果无效")
    if operation == "check":
        if "release" not in value:
            raise ValueError("发布信息缺失")
        validate_release(value["release"])
    elif (
        "version" not in value
        or not isinstance(value["version"], str)
        or not value["version"]
        or (
            operation == "install"
            and ("ready" not in value or value["ready"] is not True)
        )
    ):
        raise ValueError("更新交接结果无效")
