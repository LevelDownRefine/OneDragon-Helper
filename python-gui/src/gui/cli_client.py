"""Qt 事件循环驱动的持久 JSON-RPC 客户端；不阻塞等待或重放请求。"""

import json
import logging
from collections import deque
from dataclasses import dataclass

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

logger = logging.getLogger(__name__)
MAX_LINE = 8 * 1024 * 1024


@dataclass(frozen=True)
class CliFailure:
    code: int | str
    message: str
    refresh_required: bool = True


class CliClient(QObject):
    """用信号交付结果；请求编号由客户端分配，null 结果仍表示成功。"""

    succeeded = Signal(int, object)
    failed = Signal(int, object)
    closed = Signal()

    def __init__(
        self, program, arguments, cwd, parent=None, timeout_ms=30000, environment=None
    ):
        super().__init__(parent)
        self._process = QProcess(self)
        self._process.setProgram(program)
        self._process.setArguments(arguments)
        self._process.setWorkingDirectory(cwd)
        env = QProcessEnvironment.systemEnvironment()
        if environment is not None:
            for key, value in environment.items():
                env.insert(key, value)
        self._process.setProcessEnvironment(env)
        self._process.readyReadStandardOutput.connect(self._read_stdout)
        self._process.readyReadStandardError.connect(self._read_stderr)
        self._process.started.connect(self._send_next)
        self._process.errorOccurred.connect(self._process_error)
        self._process.finished.connect(self._finished)
        self._queue = deque()
        self._active = None
        self._next_id = 1
        self._buffer = bytearray()
        self._closing = False
        self._broken = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(timeout_ms)
        self._timer.timeout.connect(lambda: self._abort("CLI 请求超时，请刷新重连"))
        self._close_timer = QTimer(self)
        self._close_timer.setSingleShot(True)
        self._close_timer.setInterval(2000)
        self._close_timer.timeout.connect(self._process.kill)

    def request(self, method: str, params: dict | None = None) -> int:
        """排队发送命名参数；返回编号供调用方关联响应。"""
        if self._closing or self._broken:
            raise RuntimeError("CLI 会话已关闭，请创建新客户端")
        request_id = self._next_id
        payload = (
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": {} if params is None else params,
                },
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
            + b"\n"
        )
        if len(payload) > MAX_LINE:
            raise ValueError("CLI 请求超过 8 MiB")
        self._next_id += 1
        self._queue.append((request_id, payload))
        # 延后一轮，保证调用方先登记编号，即使启动失败也可关联。
        QTimer.singleShot(0, self._send_next)
        return request_id

    def _send_next(self):
        if self._broken or self._active is not None:
            return
        if not self._queue:
            if self._closing:
                self._process.closeWriteChannel()
            return
        state = self._process.state()
        if state == QProcess.ProcessState.NotRunning:
            self._timer.start()
            self._process.start()
            return
        if state != QProcess.ProcessState.Running:
            return
        self._active = self._queue.popleft()
        self._timer.start()
        if self._process.write(self._active[1]) < 0:
            self._abort("无法发送 CLI 请求")

    def _read_stdout(self):
        self._buffer.extend(bytes(self._process.readAllStandardOutput()))
        while b"\n" in self._buffer and not self._broken:
            line, _, rest = self._buffer.partition(b"\n")
            self._buffer = bytearray(rest)
            if len(line) > MAX_LINE:
                self._abort("CLI 响应超过 8 MiB")
                return
            try:
                response = json.loads(line.decode("utf-8"))
                self._receive(response)
            except (UnicodeError, ValueError, TypeError) as exc:
                logger.error("CLI 响应无效：%s: %s", type(exc).__name__, exc)
                self._abort("CLI 返回了无效响应")
                return
        if len(self._buffer) > MAX_LINE:
            self._abort("CLI 响应超过 8 MiB")

    def _receive(self, response):
        if self._active is None or not isinstance(response, dict):
            raise ValueError("未请求的响应")
        request_id = self._active[0]
        if (
            set(response)
            not in ({"jsonrpc", "id", "result"}, {"jsonrpc", "id", "error"})
            or response["jsonrpc"] != "2.0"
            or type(response["id"]) is not int
            or response["id"] != request_id
        ):
            raise ValueError("响应版本或编号不匹配")
        failure = None
        if "error" in response:
            error = response["error"]
            if (
                not isinstance(error, dict)
                or "code" not in error
                or type(error["code"]) is not int
                or "message" not in error
                or not isinstance(error["message"], str)
            ):
                raise ValueError("错误信封无效")
            refresh = error["code"] not in {-32700, -32600, -32601, -32602}
            if -32004 <= error["code"] <= -32001:
                if (
                    "data" not in error
                    or not isinstance(error["data"], dict)
                    or "refresh_required" not in error["data"]
                    or type(error["data"]["refresh_required"]) is not bool
                ):
                    raise ValueError("助手错误详情无效")
                refresh = error["data"]["refresh_required"]
            failure = CliFailure(error["code"], error["message"], refresh)
        self._active = None
        self._timer.stop()
        if failure is None:
            self.succeeded.emit(request_id, response["result"])
        else:
            self.failed.emit(request_id, failure)
        QTimer.singleShot(0, self._send_next)

    def _read_stderr(self):
        text = bytes(self._process.readAllStandardError()).decode("utf-8", "replace")
        logger.debug("CLI: %s", text.rstrip())

    def _process_error(self, error):
        self._abort(f"CLI 进程失败：{error.name}")

    def _abort(self, message):
        if self._broken:
            return
        self._broken = True
        self._timer.stop()
        pending = list(self._queue)
        self._queue.clear()
        if self._active is not None:
            pending.insert(0, self._active)
        self._active = None
        for request_id, _ in pending:
            self.failed.emit(request_id, CliFailure("transport_failed", message))
        self._process.kill()

    def close(self):
        """排空已接收请求后发送 EOF；逾期结束子进程。"""
        self._closing = True
        if (
            self._process.state() == QProcess.ProcessState.NotRunning
            and not self._queue
        ):
            self.closed.emit()
            return
        self._close_timer.start()
        self._send_next()

    @property
    def running(self):
        return self._process.state() != QProcess.ProcessState.NotRunning

    def _finished(self, exit_code, exit_status):
        self._read_stdout()
        self._read_stderr()
        self._close_timer.stop()
        if self._active is not None or self._queue or self._buffer or not self._closing:
            self._abort(f"CLI 已退出（{exit_code}，{exit_status.name}）")
        self.closed.emit()
