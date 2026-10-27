"""GUI 测试的内存传输：使用真实 CliSession，响应由测试显式交付。"""

from PySide6.QtCore import QObject, Signal

from gui.cli_client import CliFailure, CliSession


class RecordingTransport(QObject):
    succeeded = Signal(int, object)
    failed = Signal(int, object)
    closed = Signal()

    def __init__(self):
        super().__init__()
        self.usable = True
        self.running = True
        self.protected = False
        self.requests = []

    def request(self, method, params):
        self.requests.append((method, params))
        return len(self.requests)

    def protect(self):
        self.protected = True

    def unprotect(self):
        self.protected = False

    def close(self):
        self.usable = False


class RpcHarness:
    def __init__(self):
        self.transport = RecordingTransport()
        self.session = CliSession(self.transport, None)

    @property
    def requests(self):
        return self.transport.requests

    def reply(self, value, request_id=None):
        self.transport.succeeded.emit(
            len(self.requests) if request_id is None else request_id, value
        )

    def fail(self, message, request_id=None):
        self.transport.failed.emit(
            len(self.requests) if request_id is None else request_id,
            CliFailure("job_failed", message),
        )
