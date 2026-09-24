"""更新窗口和工作线程；网络、文件及进程操作全部委托 AppService。"""

import logging
from threading import Event

from PySide6.QtCore import QObject, QThread, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QDialog

from src.gui.update_dialog import UpdateDialog
from src.update.service import RELEASES_URL, UpdateCancelled

logger = logging.getLogger(__name__)


class UpdateWorker(QThread):
    progress = Signal(object, object)

    def __init__(self, service, operation: str, payload=None, parent=None):
        super().__init__(parent)
        self.service = service
        self.operation = operation
        self.payload = payload
        self.cancelled = Event()
        self.result = None
        self.error = ""

    def run(self):
        try:
            if self.operation == "check":
                self.result = self.service.check_update()
            elif self.operation == "download":
                self.result = self.service.prepare_update(
                    self.payload,
                    progress=self.progress.emit,
                    cancelled=self.cancelled,
                )
            else:
                assert self.operation == "install"
                self.result = self.service.start_update(self.payload)
        except UpdateCancelled:
            self.cancelled.set()
            logger.info("用户已取消更新下载")
        except Exception as exc:  # noqa: BLE001 线程边界：记录并展示错误，避免窗口永久等待。
            logger.exception("更新操作失败: %s", self.operation)
            self.error = str(exc)


class UpdateController(QObject):
    def __init__(self, app_service, parent=None):
        super().__init__(parent)
        self._service = app_service
        self._dialog = None
        self._worker = None
        self._release = None
        self._prepared = None
        self._next_operation = "check"
        self._close_pending = False

    def open(self, parent=None):
        if self._dialog is not None:
            self._dialog.raise_()
            self._dialog.activateWindow()
            return
        self._dialog = UpdateDialog(parent)
        self._close_pending = False
        self._release = self._prepared = None
        self._next_operation = "check"
        self._dialog.actionRequested.connect(self._advance)
        self._dialog.closeRequested.connect(self._close)
        self._dialog.releasesRequested.connect(self._open_releases)
        self._dialog.finished.connect(self._dialog_finished)
        self._dialog.show()
        self._check()

    def _check(self):
        assert self._dialog is not None
        self._dialog.notes.hide()
        self._dialog.previous_label.hide()
        try:
            info = self._service.get_update_info()
        except (OSError, ValueError) as exc:
            logger.exception("读取更新信息失败")
            self._dialog.show_state("error", f"读取更新信息失败：{exc}")
            return
        self._dialog.version_label.setText(f"当前版本：{info.version}")
        previous = info.previous_result
        if previous is not None:
            assert "status" in previous
            messages = {
                "installed": "上次更新已安装完成。",
                "recovered": "上次更新已恢复到旧版本。",
                "failed": "上次更新未完成。",
                "restart_failed": "上次更新已安装，请手动重新打开助手。",
            }
            assert previous["status"] in messages
            text = messages[previous["status"]]
            if "error" in previous:
                text += "\n" + previous["error"]
            self._dialog.previous_label.setText(text)
            self._dialog.previous_label.show()
        if info.unavailable_reason:
            self._dialog.show_state("unsupported", info.unavailable_reason)
            return
        self._start("check")

    @Slot()
    def _advance(self):
        if self._worker is not None:
            return
        if self._next_operation == "check":
            self._check()
        else:
            self._start(self._next_operation)

    def _start(self, operation: str):
        assert self._dialog is not None and self._worker is None
        states = {
            "check": ("checking", "正在检查新版本…"),
            "download": ("downloading", "正在下载更新，可随时取消。"),
            "install": ("installing", "正在准备安装，助手即将关闭并重启…"),
        }
        assert operation in states
        self._dialog.show_state(*states[operation])
        self._next_operation = operation
        payload = self._prepared if operation == "install" else self._release
        self._worker = UpdateWorker(self._service, operation, payload, self)
        self._worker.progress.connect(self._progress)
        self._worker.finished.connect(self._finished)
        app = QApplication.instance()
        assert app is not None
        app.aboutToQuit.connect(self.shutdown)
        self._worker.start()

    @Slot(object, object)
    def _progress(self, received, total):
        if self._dialog is not None and not self._close_pending:
            self._dialog.show_progress(received, total)

    @Slot()
    def _finished(self):
        worker = self._worker
        assert worker is not None
        self._worker = None
        QApplication.instance().aboutToQuit.disconnect(self.shutdown)
        worker.deleteLater()
        assert self._dialog is not None
        if self._close_pending or worker.cancelled.is_set():
            self._dialog.done(QDialog.Rejected)
        elif worker.error:
            self._dialog.show_state("error", worker.error)
        elif worker.operation == "check":
            self._release = worker.result
            if self._release is None:
                self._dialog.show_state("current", "当前已是最新版本。")
            else:
                self._next_operation = "download"
                self._dialog.notes.setPlainText(
                    self._release.notes or "此版本未提供更新说明。"
                )
                self._dialog.notes.show()
                self._dialog.show_state(
                    "available", f"发现新版本 {self._release.version}"
                )
        elif worker.operation == "download":
            self._prepared = worker.result
            self._next_operation = "install"
            self._dialog.show_state(
                "ready", "下载与校验完成。安装时将关闭助手，完成后重新打开。"
            )
        else:
            assert worker.operation == "install"
            self._dialog.accept()
            QApplication.instance().quit()

    @Slot()
    def _close(self):
        assert self._dialog is not None
        if self._worker is None:
            self._dialog.done(QDialog.Rejected)
        elif self._worker.operation != "install":
            self._close_pending = True
            self._worker.cancelled.set()
            self._dialog.show_state("cancelling", "正在取消，请等待当前操作结束…")

    @Slot()
    def shutdown(self):
        """应用退出时等工作线程结束；不销毁仍在运行的 QThread。"""
        if self._worker is not None:
            self._worker.cancelled.set()
            self._worker.wait()

    @Slot()
    def _dialog_finished(self):
        assert self._worker is None
        dialog = self._dialog
        self._dialog = None
        assert dialog is not None
        dialog.deleteLater()

    @Slot()
    def _open_releases(self):
        if not QDesktopServices.openUrl(QUrl(RELEASES_URL)):
            assert self._dialog is not None
            self._dialog.status_label.setText("无法打开浏览器，请稍后重试。")
