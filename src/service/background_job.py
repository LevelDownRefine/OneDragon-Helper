"""会话内单个后台操作；结果保留到下一次显式启动，不自动重试。"""

import logging
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from uuid import uuid4

logger = logging.getLogger(__name__)


class InvalidBackgroundJob(ValueError):
    """尚有操作进行中，或请求引用了过期任务。"""


class BackgroundJob:
    def __init__(self):
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="odh-job")
        self._future: Future | None = None
        self._id: str | None = None
        self._kind: str | None = None

    @property
    def running(self) -> bool:
        return self._future is not None and not self._future.done()

    def start(self, kind: str, operation: Callable[[], dict]) -> dict:
        if self.running:
            raise InvalidBackgroundJob("已有操作进行中，请等待完成")
        self._id = uuid4().hex
        self._kind = kind
        self._future = self._pool.submit(self._execute, operation)
        return {"id": self._id}

    @staticmethod
    def _execute(operation: Callable[[], dict]) -> dict:
        try:
            return {"state": "succeeded", "result": operation()}
        except Exception as exc:  # noqa: BLE001 -- 后台边界保存失败结果，禁止丢失异常。
            logger.exception("后台操作失败")
            return {"state": "failed", "error": f"{type(exc).__name__}: {exc}"}

    def poll(self, job_id: str) -> dict:
        if not isinstance(job_id, str) or not job_id or job_id != self._id:
            raise InvalidBackgroundJob("后台操作已不存在，请核对结果后重新操作")
        assert self._future is not None
        result = {"state": "running"} if self.running else self._future.result()
        return {"id": self._id, "kind": self._kind, **result}

    def close(self) -> None:
        # EOF 不能让后台写入跑出 application_lease；恢复不可在半途安全取消。
        self._pool.shutdown(wait=True)
