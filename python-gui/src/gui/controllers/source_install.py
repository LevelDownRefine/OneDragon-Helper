"""源码应用安装界面及后台任务编排。"""

from pathlib import Path

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QFileDialog, QInputDialog

from gui.cli_job import CliJob
from gui.controllers.cli_backup import JobDialog


class SourceInstallController(QObject):
    def __init__(self, service, session, toast, reload_games, parent=None):
        super().__init__(parent)
        self.service = service
        self.session = session
        self.toast = toast
        self.reload_games = reload_games
        self.dialog = None
        self.job = None
        self.timer = None

    def start(self):
        if self.dialog is not None or (self.session is not None and self.session.busy):
            self.toast("已有后台操作，请稍候")
            return
        if self.session is None:
            try:
                self._choose(self.service.source_catalog())
            except (OSError, ValueError) as exc:
                self.toast(str(exc))
        else:
            self.session.call("source.catalog", {}, self._choose, self._failure)

    def _choose(self, catalog):
        if not isinstance(catalog, dict) or not catalog:
            raise ValueError("源码应用列表为空或无效")
        names = list(catalog)
        labels = [catalog[name]["display_name"] for name in names]
        selected, accepted = QInputDialog.getItem(
            None, "安装源码应用", "选择应用", labels, 0, False
        )
        if not accepted:
            return
        application_id = names[labels.index(selected)]
        directory = QFileDialog.getExistingDirectory(None, "选择安装目录")
        if not directory:
            return
        definition = catalog[application_id]
        self.dialog = JobDialog("正在安装源码应用")
        self.dialog.show()
        if self.session is not None:
            self.job = CliJob(self.session, self)
            self.job.message.connect(self._message)
            self.job.failed.connect(self._failure)
            self.job.succeeded.connect(
                lambda result: self._installed(application_id, definition, result)
            )
            self.job.start(
                "source.install_catalog",
                {"application_id": application_id, "directory": directory},
                kind="source_install",
            )
        else:
            try:
                job_id = self.service.start_catalog_source_install(
                    application_id, directory
                )["id"]
            except (OSError, ValueError) as exc:
                self._failure(exc)
                return
            self.timer = QTimer(self)
            self.timer.setInterval(400)

            def poll():
                snapshot = self.service.jobs.poll(job_id)
                if "message" in snapshot:
                    self._message(snapshot["message"])
                if snapshot["state"] != "running":
                    self.timer.stop()
                    if snapshot["state"] == "succeeded":
                        self._installed(application_id, definition, snapshot["result"])
                    else:
                        self._failure(ValueError(snapshot.get("error", "安装失败")))

            self.timer.timeout.connect(poll)
            self.timer.start()

    def _message(self, message):
        if self.dialog is not None:
            self.dialog.label.setText(message[-500:])

    def _installed(self, application_id, definition, result):
        if not isinstance(result, dict) or not isinstance(result.get("source"), str):
            self._failure(ValueError("安装结果无效"))
            return
        source = result["source"]
        params = {
            "application_id": application_id,
            "display_name": definition["display_name"],
            "source_root": source,
            "script_path": str(Path(source) / definition["entry"]),
            "manual_arguments": definition["manual_arguments"],
            "run_arguments": definition["run_arguments"],
        }
        if self.session is not None:
            self.session.call(
                "source.register", params, self._registered, self._failure
            )
        else:
            try:
                self._registered(self.service.register_source_application(**params))
            except (OSError, ValueError) as exc:
                self._failure(exc)

    def _registered(self, result):
        self._close()
        self.reload_games()
        self.toast("源码应用安装完成")

    def _failure(self, failure):
        self._close()
        self.toast(getattr(failure, "message", str(failure)))

    def _close(self):
        if self.dialog is not None:
            self.dialog.set_pending(False)
            self.dialog.close()
            self.dialog.deleteLater()
            self.dialog = None
        if self.job is not None:
            self.job.deleteLater()
            self.job = None
        if self.timer is not None:
            self.timer.deleteLater()
            self.timer = None
