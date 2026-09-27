"""用有界命名管道暂停真实 CLI 输出，测试更新等待，无业务测试钩子。"""

import time
import uuid


class PipeOutput:
    def __enter__(self):
        import pywintypes
        import win32event
        import win32file
        import win32pipe

        self.name = rf"\\.\pipe\odh-exe-test-{uuid.uuid4().hex}"
        self.handle = win32pipe.CreateNamedPipe(
            self.name,
            win32pipe.PIPE_ACCESS_INBOUND | win32file.FILE_FLAG_OVERLAPPED,
            win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_WAIT,
            1,
            4096,
            4096,
            0,
            None,
        )
        self.overlap = pywintypes.OVERLAPPED()
        self.event = win32event.CreateEvent(None, True, False, None)
        self.overlap.hEvent = self.event
        self.buffer = None
        self.pending = False
        return self

    def connect(self):
        import pywintypes
        import win32event
        import win32pipe

        try:
            self.pending = True
            win32pipe.ConnectNamedPipe(self.handle, self.overlap)
        except pywintypes.error as exc:
            if exc.winerror != 535:  # Client connected before ConnectNamedPipe.
                raise
            win32event.SetEvent(self.event)
        if (
            win32event.WaitForSingleObject(self.event, 60_000)
            != win32event.WAIT_OBJECT_0
        ):
            raise TimeoutError("CLI 未连接测试输出管道")
        self.pending = False

    def read(self) -> bytes:
        import pywintypes
        import win32event
        import win32file

        deadline = time.monotonic() + 60
        output = bytearray()
        while True:
            win32event.ResetEvent(self.event)
            try:
                self.pending = True
                _status, self.buffer = win32file.ReadFile(
                    self.handle, 65536, self.overlap
                )
                remaining = max(0, int((deadline - time.monotonic()) * 1000))
                if (
                    win32event.WaitForSingleObject(self.event, remaining)
                    != win32event.WAIT_OBJECT_0
                ):
                    raise TimeoutError("CLI 输出超时")
                count = win32file.GetOverlappedResult(self.handle, self.overlap, False)
                self.pending = False
            except pywintypes.error as exc:
                if exc.winerror == 109:  # Normal EOF after CLI closes the pipe.
                    self.pending = False
                    return bytes(output)
                raise
            output.extend(self.buffer[:count])
            if len(output) > 8 * 1024**2:
                raise ValueError("测试输出超出 8 MiB")

    def __exit__(self, *_error):
        import win32event
        import win32file

        try:
            if self.pending:
                win32file.CancelIo(self.handle)  # All IO was issued by this thread.
                if (
                    win32event.WaitForSingleObject(self.event, 5000)
                    != win32event.WAIT_OBJECT_0
                ):
                    raise TimeoutError("测试输出管道取消超时")
        finally:
            self.handle.Close()
            self.event.Close()
