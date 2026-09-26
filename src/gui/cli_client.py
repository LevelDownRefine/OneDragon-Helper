"""异步 stdio 客户端；只负责进程与协议，不承载业务或写盘。"""

import json
import logging
import sys
from collections.abc import Callable

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from src.utils import get_root_dir

logger = logging.getLogger(__name__)


class CliClient(QObject):
    failed = Signal(str)

    def __init__(self, parent=None, *, command=None, timeout_ms=15000):
        super().__init__(parent)
        self._command = command or [
            sys.executable,
            "-m",
            "src.headless",
            "serve",
            "--stdio",
        ]
        self._timeout_ms = timeout_ms
        self._process = QProcess(self)
        self._process.setWorkingDirectory(get_root_dir())
        self._process.started.connect(self._flush)
        self._process.readyReadStandardOutput.connect(self._read_stdout)
        self._process.readyReadStandardError.connect(self._read_stderr)
        self._process.errorOccurred.connect(self._process_error)
        self._process.finished.connect(self._finished)
        self._pending: dict[int, tuple[Callable, QTimer]] = {}
        self._outgoing: list[bytes] = []
        self._buffer = b""
        self._next_id = 0
        self._closing = False
        self._broken = False

    def request(self, method: str, params: dict, callback: Callable) -> int:
        """回调参数为 (result, error)；失败的写操作绝不自动重放。"""
        assert not self._closing, "已关闭的 CLI 客户端不能接收请求"
        if self._broken and self._process.state() != QProcess.NotRunning:
            callback(
                None,
                {
                    "code": "transport_failed",
                    "message": "CLI 正在退出，请稍后刷新",
                    "refresh_required": True,
                },
            )
            return 0
        self._next_id += 1
        request_id = self._next_id
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self._fail("CLI 响应超时，请刷新后确认实际状态"))
        self._pending[request_id] = callback, timer
        timer.start(self._timeout_ms)
        self._outgoing.append(
            (
                json.dumps(
                    {
                        "protocol_version": 1,
                        "id": request_id,
                        "method": method,
                        "params": params,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            ).encode("utf-8")
        )
        if self._process.state() == QProcess.NotRunning:
            self._broken = False
            self._buffer = b""
            self._process.start(self._command[0], self._command[1:])
        elif self._process.state() == QProcess.Running:
            self._flush()
        return request_id

    def _flush(self):
        outgoing, self._outgoing = self._outgoing, []
        for payload in outgoing:
            if self._process.write(payload) < 0:
                self._fail("无法向 CLI 发送请求")
                return

    def _read_stdout(self):
        self._buffer += bytes(self._process.readAllStandardOutput())
        while b"\n" in self._buffer and not self._closing and not self._broken:
            line, self._buffer = self._buffer.split(b"\n", 1)
            try:
                response = json.loads(line.decode("utf-8"))
            except (ValueError, UnicodeError) as exc:
                logger.error("CLI 协议解析失败：%s: %s", type(exc).__name__, exc)
                self._fail("CLI 返回了无效数据，请刷新重连")
                return
            if (
                not isinstance(response, dict)
                or not {"protocol_version", "id"} <= response.keys()
            ):
                self._fail("CLI 响应缺少协议字段")
                return
            assert "protocol_version" in response and "id" in response
            request_id = response["id"]
            if (
                type(response["protocol_version"]) is not int
                or response["protocol_version"] != 1
                or type(request_id) is not int
                or request_id not in self._pending
                or ("result" in response) == ("error" in response)
            ):
                self._fail("CLI 会话中断或响应身份不匹配，请刷新确认状态")
                return
            result = response["result"] if "result" in response else None  # noqa: SIM401
            error = response["error"] if "error" in response else None  # noqa: SIM401
            if (error is None and not isinstance(result, dict)) or (
                error is not None
                and (
                    not isinstance(error, dict)
                    or not {"code", "message", "refresh_required"} <= error.keys()
                )
            ):
                self._fail("CLI 返回了无效结果")
                return
            if error is not None:
                assert (
                    "message" in error
                    and "code" in error
                    and "refresh_required" in error
                )
                if (
                    not isinstance(error["message"], str)
                    or not isinstance(error["code"], str)
                    or type(error["refresh_required"]) is not bool
                ):
                    self._fail("CLI 返回了无效错误信息")
                    return
            assert request_id in self._pending
            callback, timer = self._pending.pop(request_id)
            timer.stop()
            timer.deleteLater()
            callback(result, error)

    def _read_stderr(self):
        message = (
            bytes(self._process.readAllStandardError())
            .decode("utf-8", errors="replace")
            .strip()
        )
        if message:
            logger.info("[headless] %s", message)

    def _process_error(self, _error):
        if not self._closing:
            self._fail(f"CLI 进程错误：{self._process.errorString()}")

    def _finished(self, _exit_code, _exit_status):
        if not self._closing:
            self._fail("CLI 进程已退出，请刷新重连并确认实际状态")

    def _fail(self, message: str):
        if self._broken or self._closing:
            return
        self._broken = True
        logger.error("%s", message)
        pending, self._pending = self._pending, {}
        self._outgoing.clear()
        if self._process.state() != QProcess.NotRunning:
            self._process.kill()
        error = {
            "code": "transport_failed",
            "message": message,
            "refresh_required": True,
        }
        for callback, timer in pending.values():
            timer.stop()
            timer.deleteLater()
            callback(None, error)
        self.failed.emit(message)

    def close(self):
        """窗口退出时关闭 stdin；有界等待后只终止所属后端。"""
        if self._closing:
            return
        self._closing = True
        for _, timer in self._pending.values():
            timer.stop()
            timer.deleteLater()
        self._pending.clear()
        self._outgoing.clear()
        self._process.closeWriteChannel()
        if (
            self._process.state() != QProcess.NotRunning
            and not self._process.waitForFinished(1500)
        ):
            self._process.kill()
            self._process.waitForFinished(1000)
