"""同一安装目录的运行共享锁和更新独占锁。"""

import contextlib
import ctypes
import logging
import os
import time
from pathlib import Path

import psutil

from src.update.package import APP_EXE, RUNNER_EXE, UpdateError

logger = logging.getLogger(__name__)


class UpdateBusyError(UpdateError):
    """更新或脚本运行尚未结束。"""


class FileLease:
    """进程退出后由系统释放；Windows 使用 LockFileEx，Linux 用 flock。"""

    def __init__(self, path: Path, *, shared: bool = False, timeout: float = 0):
        self.path = path
        self.shared = shared
        self.timeout = timeout
        self.stream = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open("a+b")
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                self._lock()
                return self
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    self.stream.close()
                    raise UpdateBusyError("助手正在运行任务或更新，请稍后重试") from exc
                time.sleep(0.1)
            except OSError:
                self.stream.close()
                raise

    def _lock(self):
        assert self.stream is not None
        if os.name == "nt":
            import msvcrt
            from ctypes import wintypes

            class Overlapped(ctypes.Structure):
                _fields_ = [
                    ("Internal", ctypes.c_size_t),
                    ("InternalHigh", ctypes.c_size_t),
                    ("Offset", wintypes.DWORD),
                    ("OffsetHigh", wintypes.DWORD),
                    ("hEvent", wintypes.HANDLE),
                ]

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.LockFileEx.argtypes = [
                wintypes.HANDLE,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.DWORD,
                ctypes.POINTER(Overlapped),
            ]
            kernel.LockFileEx.restype = wintypes.BOOL
            flags = 1 | (0 if self.shared else 2)
            overlap = Overlapped()
            if not kernel.LockFileEx(
                msvcrt.get_osfhandle(self.stream.fileno()),
                flags,
                0,
                1,
                0,
                ctypes.byref(overlap),
            ):
                error = ctypes.get_last_error()
                if error in (33, 32):
                    raise BlockingIOError(error, "安装目录被占用")
                raise ctypes.WinError(error)
        else:
            import fcntl

            fcntl.flock(
                self.stream,
                (fcntl.LOCK_SH if self.shared else fcntl.LOCK_EX) | fcntl.LOCK_NB,
            )

    def __exit__(self, *_args):
        assert self.stream is not None
        self.stream.close()


def update_directory(root: Path) -> Path:
    directory = root / ".update"
    if directory.is_symlink() or (
        directory.exists()
        and getattr(directory.lstat(), "st_file_attributes", 0) & 0x400
    ):
        raise UpdateError("更新工作目录不能是链接")
    directory.mkdir(exist_ok=True)
    return directory


@contextlib.contextmanager
def application_lease(root: Path):
    """启动先通过更新闸门，再持有运行共享锁，覆盖 GUI 与所有 CLI 入口。"""
    directory = update_directory(root)
    with contextlib.ExitStack() as stack:
        with FileLease(directory / "intent.lock", shared=True):
            stack.enter_context(FileLease(directory / "runtime.lock", shared=True))
            journal = directory / "transaction.json"
            if journal.exists():
                import json

                data = json.loads(journal.read_text(encoding="utf-8"))
                if (
                    not isinstance(data, dict)
                    or "phase" not in data
                    or data["phase"] not in ("committed", "rolled_back")
                ):
                    raise UpdateError(
                        "上次更新未完成，请运行更新器 --recover 恢复后再启动"
                    )
        yield


def helper_processes(root: Path, excluded: set[int] | None = None) -> list[int]:
    """按 EXE 完整路径识别当前安装的 GUI、调度和 Runner，不按名称误杀其他安装。"""
    excluded = excluded or set()
    targets = {
        os.path.normcase(str((root / name).resolve())) for name in (APP_EXE, RUNNER_EXE)
    }
    found = []
    for process in psutil.process_iter():
        if process.pid in excluded:
            continue
        try:
            executable = process.exe()
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
        except psutil.AccessDenied:
            # 无权限的系统进程不是当前管理员用户启动的 Helper。
            logger.debug("无法读取进程路径: pid=%s", process.pid)
            continue
        if executable and os.path.normcase(str(Path(executable).resolve())) in targets:
            found.append(process.pid)
    return found


def child_environment() -> dict[str, str]:
    """启动独立冻结程序，不复用父进程的 PyInstaller 解压目录。"""
    env = dict(os.environ)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env
