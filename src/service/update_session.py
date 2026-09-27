"""无 Qt 更新会话；发布对象和待安装目录只留在 Python 服务内。"""

from dataclasses import asdict
from threading import Event

from src.service.background_job import BackgroundJob, InvalidBackgroundJob
from src.update.package import UpdateCancelled, UpdateError
from src.update.service import (
    RELEASES_URL,
    PreparedUpdate,
    ReleaseUpdate,
    UpdateService,
)


class UpdateSession:
    def __init__(self, service: UpdateService, background: BackgroundJob):
        self._service = service
        self._background = background
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
        if self._background.running:
            raise InvalidBackgroundJob("已有操作进行中，请等待完成")
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

        return self._background.start("update.check", operation, cancelled=cancelled)

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
                release, progress=self._background.progress, cancelled=cancelled
            )
            if cancelled.is_set():
                raise UpdateCancelled("下载已取消")
            self._prepared = prepared
            return {"version": prepared.version}

        return self._background.start("update.download", operation, cancelled=cancelled)

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

        return self._background.start("update.install", operation)
