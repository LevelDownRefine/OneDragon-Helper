"""会话内单个后台操作；结果保留到下一次显式启动，不自动重试。"""

import logging
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Event, Lock
from uuid import uuid4

from src.update.package import UpdateCancelled

logger = logging.getLogger(__name__)


class InvalidBackgroundJob(ValueError):
    """尚有操作进行中，或请求引用了过期任务。"""


class BackgroundJob:
    def __init__(self):
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="odh-job")
        self._future: Future | None = None
        self._id: str | None = None
        self._kind: str | None = None
        self._cancelled: Event | None = None
        self._progress: tuple[int, int] | None = None
        self._lock = Lock()

    @property
    def running(self) -> bool:
        return self._future is not None and not self._future.done()

    def start(
        self,
        kind: str,
        operation: Callable[[], dict],
        *,
        cancelled: Event | None = None,
    ) -> dict:
        if self.running:
            raise InvalidBackgroundJob("已有操作进行中，请等待完成")
        self._id = uuid4().hex
        self._kind = kind
        self._cancelled = cancelled
        with self._lock:
            self._progress = None
        self._future = self._pool.submit(self._execute, operation)
        return {"id": self._id}

    @staticmethod
    def _execute(operation: Callable[[], dict]) -> dict:
        try:
            return {"state": "succeeded", "result": operation()}
        except UpdateCancelled:
            logger.info("用户已取消更新操作")
            return {"state": "cancelled"}
        except Exception as exc:  # noqa: BLE001 -- 后台边界保存失败结果，禁止丢失异常。
            logger.exception("后台操作失败")
            return {"state": "failed", "error": f"{type(exc).__name__}: {exc}"}

    def poll(self, job_id: str) -> dict:
        if not isinstance(job_id, str) or not job_id or job_id != self._id:
            raise InvalidBackgroundJob("后台操作已不存在，请核对结果后重新操作")
        assert self._future is not None
        result = {"state": "running"} if self.running else self._future.result()
        snapshot = {"id": self._id, "kind": self._kind, **result}
        with self._lock:
            if self._progress is not None:
                received, total = self._progress
                snapshot["progress"] = {"received": received, "total": total}
        return snapshot

    def progress(self, received: int, total: int) -> None:
        """工作线程只替换一份进度快照，主线程轮询时读取。"""
        assert type(received) is int and type(total) is int
        assert received >= 0 and total >= 0
        with self._lock:
            self._progress = (received, total)

    def cancel(self, job_id: str) -> bool:
        self.poll(job_id)
        if self._cancelled is None:
            raise InvalidBackgroundJob("此操作不支持中途取消")
        if not self.running:
            return False
        self._cancelled.set()
        return True

    def close(self) -> None:
        if self._cancelled is not None:
            self._cancelled.set()
        # EOF 不能让后台写入跑出 application_lease；恢复不可在半途安全取消。
        self._pool.shutdown(wait=True)
