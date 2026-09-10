"""跨进程运行互斥；进程退出后系统自动释放锁，不遗留忙碌状态。"""

import errno
import os
from contextlib import contextmanager
from pathlib import Path

from src.utils import get_root_dir


@contextmanager
def run_lock(root_dir: str | None = None):
    """尝试获得当前安装的运行锁，返回是否成功；覆盖运行及收尾全过程。"""
    path = Path(root_dir or get_root_dir()) / "config" / "run.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            def lock():
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)

            def unlock():
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            def lock():
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)

            def unlock():
                fcntl.flock(handle, fcntl.LOCK_UN)

        acquired = False
        try:
            try:
                lock()
                acquired = True
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
            yield acquired
        finally:
            if acquired:
                unlock()
