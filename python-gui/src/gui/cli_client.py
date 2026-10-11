"""Qt 事件循环驱动的持久 JSON-RPC 客户端；不阻塞等待或重放请求。"""

import json
import logging
from collections import deque
from dataclasses import dataclass

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

logger = logging.getLogger(__name__)
MAX_LINE = 8 * 1024 * 1024


class CliSession(QObject):
    """控制器共用的会话；外部编号不随重连重置，失效写操作不重放。"""

    succeeded = Signal(int, object)
    failed = Signal(int, object)
    recovered = Signal()
    busyChanged = Signal()

    READ_METHODS = {
        "app.snapshot",
        "script.view",
        "script.target",
        "script.icon_path",
        "script.launch_target",
        "script.edit_view",
        "settings.view",
        "startup.view",
        "wallpaper.current",
        "wallpaper.view",
        "plan.view",
        "run.view",
        "run.saved",
        "update.view",
    }

    def __init__(self, client, factory, parent=None):
        super().__init__(parent)
        self._client = client
        self._factory = factory
        self._next_id = 1
        self._pending = {}
        self._callbacks = {}
        self._recovery_pending = False
        self._closing = False
        self._held_client = None
        self._connect()
        self.succeeded.connect(self._success)
        self.failed.connect(self._failure)

    def _connect(self):
        self._client.succeeded.connect(self._received)
        self._client.failed.connect(self._rejected)

    @property
    def usable(self):
        return self._client.usable and not self._closing

    @property
    def busy(self):
        return self._held_client is not None

    def hold(self):
        """后台写入及安装交接结束前保留当前进程，禁止另起会话。"""
        if self.busy or not self.usable:
            return False
        self._held_client = self._client
        self._client.protect()
        self._client.closed.connect(self.release)
        self.busyChanged.emit()
        return True

    def release(self):
        """断线任务等旧进程完成 EOF 清理再释放，不能并发重建写入会话。"""
        client = self._held_client
        if client is None or (not client.usable and client.running):
            return
        client.closed.disconnect(self.release)
        client.unprotect()
        self._held_client = None
        self.busyChanged.emit()

    def retire(self):
        """结果不明时送 EOF 等后台操作结束，保留保护和租约直到进程退出。"""
        self._client.close()
        self.release()

    def detach(self):
        """GUI 退出后不再交付响应，底层进程仍由 launcher 排空关闭。"""
        self._closing = True
        self._pending.clear()
        self._callbacks.clear()

    def request(self, method, params=None):
        if self._closing:
            raise RuntimeError("GUI 正在退出")
        if not self.usable:
            if self.busy:
                raise RuntimeError("后台操作正在结束，请稍后刷新；不要重复提交")
            if method not in self.READ_METHODS or self._factory is None:
                raise RuntimeError("CLI 会话已失效，请刷新后再操作")
            previous = self._client
            previous.succeeded.disconnect(self._received)
            previous.failed.disconnect(self._rejected)
            # 旧会话尚未回调的请求也必须结束，不能挂在新会话上。
            pending = list(self._pending.values())
            self._pending.clear()
            for request_id in pending:
                self.failed.emit(
                    request_id, CliFailure("transport_failed", "CLI 会话已失效")
                )
            previous.close()
            self._client = self._factory()
            self._connect()
            self._recovery_pending = True
        wire_id = self._client.request(method, params)
        request_id = self._next_id
        self._next_id += 1
        self._pending[wire_id] = request_id
        return request_id

    def call(self, method, params, success, failure):
        """回调只绑定本次请求；用户重试才会产生新的写操作。"""
        try:
            request_id = self.request(method, params)
        except (RuntimeError, ValueError) as exc:
            failure(CliFailure("transport_failed", str(exc)))
            return
        self._callbacks[request_id] = success, failure

    def _received(self, wire_id, result):
        if wire_id in self._pending:
            request_id = self._pending.pop(wire_id)
            if self._recovery_pending:
                self._recovery_pending = False
                self.recovered.emit()
            self.succeeded.emit(request_id, result)

    def _rejected(self, wire_id, failure):
        if wire_id in self._pending:
            self.failed.emit(self._pending.pop(wire_id), failure)

    def _success(self, request_id, result):
        if request_id in self._callbacks:
            success, failure = self._callbacks.pop(request_id)
            try:
                success(result)
            except ValueError as exc:
                logger.error("CLI 业务响应无效：%s", exc)
                failure(CliFailure("invalid_response", "CLI 返回了无效数据，请刷新"))

    def _failure(self, request_id, failure):
        if request_id in self._callbacks:
            _, callback = self._callbacks.pop(request_id)
            callback(failure)


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
        self._protected = False
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
        # 结果槽可能打开模态弹窗，先允许其嵌套事件循环继续发送保存请求。
        QTimer.singleShot(0, self._send_next)
        if failure is None:
            self.succeeded.emit(request_id, response["result"])
        else:
            self.failed.emit(request_id, failure)

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
        if self._protected:
            self._process.closeWriteChannel()
            if not self.running:
                self.closed.emit()
        else:
            self._process.kill()

    def protect(self):
        """EOF 后允许服务完成后台写入，不强杀恢复或安装准备。"""
        self._protected = True
        self._close_timer.stop()

    def unprotect(self):
        self._protected = False

    def close(self):
        """排空已接收请求后发送 EOF；逾期结束子进程。"""
        self._closing = True
        if (
            self._process.state() == QProcess.ProcessState.NotRunning
            and not self._queue
        ):
            self.closed.emit()
            return
        if not self._protected:
            self._close_timer.start()
        self._send_next()

    @property
    def usable(self):
        """失效或关闭中的会话不能继续接受请求。"""
        return not self._broken and not self._closing

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
