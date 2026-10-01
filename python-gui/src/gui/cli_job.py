"""当前会话内的后台任务：串行轮询、取消确认、严格身份与状态校验。"""

from PySide6.QtCore import QObject, QTimer, Signal

from gui.cli_client import CliFailure


class CliJob(QObject):
    progress = Signal(object, object)
    succeeded = Signal(object)
    failed = Signal(object)
    cancelled = Signal()

    def __init__(self, session, parent=None, interval_ms=400):
        super().__init__(parent)
        self.session = session
        self.active = False
        self.kind = ""
        self.job_id = None
        self._generation = 0
        self._cancel_requested = False
        self._cancel_sent = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._poll)

    def start(self, method, params=None):
        """只提交一次；开始响应丢失也不重放任务。"""
        if self.active:
            return
        if not self.session.hold():
            self.failed.emit(
                CliFailure("busy", "已有后台操作，或会话已失效，请刷新后重试", False)
            )
            return
        self.active = True
        self.kind = method.removesuffix(".start")
        self.job_id = None
        self._generation += 1
        generation = self._generation
        self._cancel_requested = self._cancel_sent = False

        def started(value):
            if generation != self._generation or not self.active:
                return
            if (
                not isinstance(value, dict)
                or "id" not in value
                or not isinstance(value["id"], str)
                or not value["id"]
            ):
                raise ValueError("后台任务编号无效")
            self.job_id = value["id"]
            if self._cancel_requested:
                self.cancel()
            self._timer.start(0)

        self.session.call(
            method, {} if params is None else params, started, self._reject(generation)
        )

    def _poll(self):
        if not self.active or self.job_id is None:
            return
        generation = self._generation

        def received(value):
            if generation != self._generation or not self.active:
                return
            validate_job(value, self.job_id, self.kind)
            if "progress" in value:
                self.progress.emit(
                    value["progress"]["received"], value["progress"]["total"]
                )
            state = value["state"]
            if state == "running":
                self._timer.start()
            elif state == "succeeded":
                self._finish()
                self.succeeded.emit(value["result"])
            elif state == "cancelled":
                self._finish()
                self.cancelled.emit()
            else:
                self._failure(CliFailure("job_failed", value["error"]))

        self.session.call(
            "job.poll", {"job_id": self.job_id}, received, self._reject(generation)
        )

    def cancel(self):
        """取消只用于检查/下载；开始回包前关闭窗口也会在拿到编号后取消。"""
        if not self.active or self.kind not in {"update.check", "update.download"}:
            return False
        self._cancel_requested = True
        if self.job_id is None or self._cancel_sent:
            return True
        self._cancel_sent = True
        generation = self._generation

        def acknowledged(value):
            if generation != self._generation or not self.active:
                return
            if type(value) is not bool:
                raise ValueError("取消响应无效")

        self.session.call(
            "job.cancel",
            {"job_id": self.job_id},
            acknowledged,
            self._reject(generation),
        )
        return True

    def _finish(self):
        self._timer.stop()
        self.active = False
        self.session.release()

    def _failure(self, failure):
        if not self.active:
            return
        if failure.code in {"transport_failed", "invalid_response"}:
            self.session.retire()
        self._finish()
        self.failed.emit(failure)

    def _reject(self, generation):
        def rejected(failure):
            if generation == self._generation:
                self._failure(failure)

        return rejected


def validate_job(value, job_id, kind):
    if (
        not isinstance(value, dict)
        or not all(key in value for key in ("id", "kind", "state"))
        or value["id"] != job_id
        or value["kind"] != kind
        or not isinstance(value["state"], str)
        or value["state"] not in {"running", "succeeded", "failed", "cancelled"}
    ):
        raise ValueError("后台任务身份或状态无效")
    if "progress" in value:
        progress = value["progress"]
        if not isinstance(progress, dict) or not all(
            key in progress and type(progress[key]) is int and progress[key] >= 0
            for key in ("received", "total")
        ):
            raise ValueError("后台任务进度无效")
    if value["state"] == "succeeded" and "result" not in value:
        raise ValueError("后台任务结果缺失")
    if value["state"] == "failed" and (
        "error" not in value or not isinstance(value["error"], str)
    ):
        raise ValueError("后台任务失败信息缺失")
    if value["state"] == "cancelled" and kind not in {
        "update.check",
        "update.download",
    }:
        raise ValueError("此后台操作不能取消")
