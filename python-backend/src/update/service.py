"""助手更新会话与应用默认参数；安装和下载由独立 updater 包提供。"""

from dataclasses import asdict
from pathlib import Path
from threading import Event

from updater.package import UpdateCancelled, UpdateError
from updater.service import (
    PreparedUpdate as PreparedUpdate,
)
from updater.service import (
    ReleaseUpdate as ReleaseUpdate,
)
from updater.service import (
    UpdateInfo as UpdateInfo,
)
from updater.service import (
    UpdateService as CoreUpdateService,
)

from src.update.policy import POLICY
from src.utils import get_root_dir
from src.utils.utils_job import InvalidJob, JobExecutor

RELEASES_URL = POLICY.releases_url


class UpdateService(CoreUpdateService):
    def __init__(self, root: Path | None = None, *, frontend: str = "qt"):
        super().__init__(
            (root or Path(get_root_dir())), policy=POLICY, frontend=frontend
        )


class UpdateSession:
    """更新会话保留发布和待安装状态，耗时操作交给共享任务执行器。"""

    def __init__(self, service: UpdateService, jobs: JobExecutor):
        self._service = service
        self._jobs = jobs
        self._release: ReleaseUpdate | None = None
        self._prepared: PreparedUpdate | None = None
        self._handed_off = False

    def view(self) -> dict:
        """只读本地状态；进入弹窗不触发网络。"""
        return {
            **asdict(self._service.get_update_info()),
            "releases_url": RELEASES_URL,
            "release": self._release_view(),
            "prepared_version": self._prepared.version if self._prepared else None,
            "handoff_ready": self._handed_off,
        }

    def _release_view(self) -> dict | None:
        if self._release is None:
            return None
        return {
            "version": self._release.version,
            "notes": self._release.notes,
            "size": self._release.size,
        }

    def check(self) -> dict:
        """显式检查，结果保留在当前会话，不接受客户端指定下载地址。"""
        if self._jobs.running:
            raise InvalidJob("已有操作进行中，请等待完成")
        if self._handed_off:
            raise UpdateError("安装交接已就绪，请退出窗口")
        info = self._service.get_update_info()
        if info.unavailable_reason:
            raise UpdateError(info.unavailable_reason)
        self._release = None
        self._prepared = None
        cancelled = Event()

        def operation():
            release = self._service.check_update()
            if cancelled.is_set():
                raise UpdateCancelled("检查已取消")
            self._release = release
            return {"release": self._release_view()}

        return self._jobs.start("update.check", operation, cancelled=cancelled)

    def download(self) -> dict:
        """下载当前会话检查到的版本，进度与取消复用更新服务。"""
        if self._handed_off:
            raise UpdateError("安装交接已就绪，请退出窗口")
        if self._release is None:
            raise UpdateError("请先检查更新")
        release = self._release
        cancelled = Event()

        def operation():
            prepared = self._service.prepare_update(
                release, progress=self._jobs.progress, cancelled=cancelled
            )
            if cancelled.is_set():
                raise UpdateCancelled("下载已取消")
            self._prepared = prepared
            return {"version": prepared.version}

        return self._jobs.start("update.download", operation, cancelled=cancelled)

    def install(self) -> dict:
        """只安装本会话校验过的包；就绪后客户端关闭，安装器独立执行。"""
        if self._handed_off:
            raise UpdateError("安装交接已就绪，请退出窗口")
        if self._prepared is None:
            raise UpdateError("请先下载并校验更新")
        prepared = self._prepared

        def operation():
            self._service.start_update(prepared)
            self._handed_off = True
            return {"version": prepared.version, "ready": True}

        return self._jobs.start("update.install", operation)
