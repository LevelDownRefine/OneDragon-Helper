"""同一安装目录的运行共享锁和更新独占锁。"""

import contextlib
import logging
import os
from pathlib import Path

import portalocker
import psutil

from src.update.package import APP_EXE, CLI_EXE, RUNNER_EXE, UpdateError

logger = logging.getLogger(__name__)


class UpdateBusyError(UpdateError):
    """更新或脚本运行尚未结束。"""


class FileLease:
    """共享运行锁和独占更新锁，由 portalocker 管理跨平台加锁与释放。"""

    def __init__(self, path: Path, *, shared: bool = False, timeout: float = 0):
        self.path = path
        self.lock = portalocker.Lock(
            path,
            mode="a+b",
            timeout=timeout,
            check_interval=0.1,
            flags=(portalocker.LOCK_SH if shared else portalocker.LOCK_EX)
            | portalocker.LOCK_NB,
        )

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.lock.acquire()
        except portalocker.AlreadyLocked as exc:
            raise UpdateBusyError("助手正在运行任务或更新，请稍后重试") from exc
        except portalocker.LockException as exc:
            raise UpdateError(f"无法锁定安装目录: {exc}") from exc
        return self

    def __exit__(self, *args):
        self.lock.__exit__(*args)


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
        os.path.normcase(str((root / name).resolve()))
        for name in (APP_EXE, CLI_EXE, RUNNER_EXE)
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
