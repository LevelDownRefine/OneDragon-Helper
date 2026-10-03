"""手动更新服务；构造和读取本地状态不发起网络请求。"""

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
import zipfile
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Event

import psutil

from src.update.package import (
    APP_EXE,
    CLI_EXE,
    MAX_PACKAGE_BYTES,
    QT_CLI_EXE,
    UPDATER_EXE,
    VERSION_FILE,
    UpdateCancelled,
    UpdateError,
    file_digest,
    load_manifest,
    manifest_frontend,
    unpack_package,
    version_number,
)
from src.update.remote import RemoteUnavailable, open_archive
from src.update.runtime import (
    child_environment,
    helper_processes,
    update_directory,
)
from src.utils import get_root_dir
from src.utils.utils_job import InvalidJob, JobExecutor

logger = logging.getLogger(__name__)
REPOSITORY = "LevelDownRefine/OneDragon-Helper"
RELEASES_URL = f"https://github.com/{REPOSITORY}/releases"
ZIP_NAME = "OneDragon-Helper.zip"
RUST_ZIP_NAME = "OneDragon-Helper-Rust.zip"


@dataclass(frozen=True)
class ReleaseUpdate:
    version: str
    notes: str
    archive_url: str
    checksum_url: str
    size: int


@dataclass(frozen=True)
class PreparedUpdate:
    directory: Path
    version: str


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    unavailable_reason: str = ""
    previous_result: dict | None = None


class UpdateService:
    def __init__(self, root: Path | None = None, *, frontend: str = "qt"):
        assert frontend in {"qt", "rust"}
        self.root = (root or Path(get_root_dir())).resolve()
        self.frontend = frontend
        self.zip_name = RUST_ZIP_NAME if frontend == "rust" else ZIP_NAME

    def get_update_info(self) -> UpdateInfo:
        """读取当前版本、可用性与上次安装结果，不创建目录或请求网络。"""
        previous = None
        result = self.root / ".update/result.json"
        if result.is_file():
            previous = json.loads(result.read_text(encoding="utf-8"))
            if (
                not isinstance(previous, dict)
                or "status" not in previous
                or not isinstance(previous["status"], str)
                or previous["status"]
                not in {"installed", "failed", "restart_failed", "recovered"}
                or ("error" in previous and not isinstance(previous["error"], str))
            ):
                raise UpdateError("无法读取上次更新结果")
        if not getattr(sys, "frozen", False):
            return UpdateInfo(
                "源码运行", "当前从源码运行，请前往发布页面下载正式版。", previous
            )
        version = "未知版本"
        path = self.root / VERSION_FILE
        if path.is_file():
            info = json.loads(path.read_text(encoding="utf-8"))
            if (
                not isinstance(info, dict)
                or "version" not in info
                or not isinstance(info["version"], str)
            ):
                raise UpdateError("本地版本信息无效")
            version = info["version"]
        try:
            self._installed()
        except UpdateError as exc:
            return UpdateInfo(
                version, str(exc).replace(f": {RELEASES_URL}", ""), previous
            )
        return UpdateInfo(version, previous_result=previous)

    def _installed(self) -> dict:
        if not getattr(sys, "frozen", False):
            raise UpdateError(f"源码运行不支持替换安装，请使用发布版: {RELEASES_URL}")
        data = load_manifest(self.root)
        if manifest_frontend(data) != self.frontend:
            raise UpdateError(
                f"当前安装不是 {self.frontend} 发行版，请手动安装对应发布包"
            )
        version = version_number(data["version"])
        if version.local is not None or version.is_devrelease:
            raise UpdateError(
                f"开发构建不支持在线更新，请使用正式发布版: {RELEASES_URL}"
            )
        return data

    def check_update(self) -> ReleaseUpdate | None:
        """仅显式调用时查询稳定 Release；没有更高版本时返回 None。"""
        installed = self._installed()
        # 网络库仅在更新操作中加载，避免占用 GUI 启动路径。
        import requests

        with requests.get(
            f"https://api.github.com/repos/{REPOSITORY}/releases/latest",
            headers={"Accept": "application/vnd.github+json"},
            timeout=(10, 30),
        ) as response:
            response.raise_for_status()
            data = response.json()
        required = {"tag_name", "draft", "prerelease", "assets", "body"}
        if not isinstance(data, dict) or not required <= data.keys():
            raise UpdateError("Release 信息不完整")
        tag = data["tag_name"]
        if (
            not isinstance(tag, str)
            or not re.fullmatch(r"v\d+\.\d+\.\d+", tag)
            or data["draft"]
            or data["prerelease"]
        ):
            raise UpdateError("更新目标不是正式稳定版本")
        version = tag[1:]
        if version_number(version) <= version_number(installed["version"]):
            return None
        assets = {}
        if not isinstance(data["assets"], list):
            raise UpdateError("Release 附件列表无效")
        for asset in data["assets"]:
            if (
                not isinstance(asset, dict)
                or not {"name", "browser_download_url", "size"} <= asset.keys()
            ):
                raise UpdateError("Release 附件信息无效")
            if asset["name"] in (self.zip_name, self.zip_name + ".sha256"):
                if asset["name"] in assets:
                    raise UpdateError("Release 附件重复")
                expected = f"https://github.com/{REPOSITORY}/releases/download/{tag}/{asset['name']}"
                if asset["browser_download_url"] != expected:
                    raise UpdateError("Release 附件地址不属于当前发布")
                assets[asset["name"]] = asset
        if not {self.zip_name, self.zip_name + ".sha256"} <= assets.keys():
            raise UpdateError(f"新版缺少 {self.zip_name} 或 SHA-256 校验文件")
        size = assets[self.zip_name]["size"]
        if type(size) is not int or not 0 < size <= MAX_PACKAGE_BYTES:
            raise UpdateError("更新包大小无效")
        notes = data["body"]
        if notes is not None and not isinstance(notes, str):
            raise UpdateError("更新说明无效")
        return ReleaseUpdate(
            version,
            notes or "",
            assets[self.zip_name]["browser_download_url"],
            assets[self.zip_name + ".sha256"]["browser_download_url"],
            size,
        )

    def prepare_update(
        self,
        release: ReleaseUpdate,
        *,
        progress: Callable[[int, int], None] | None = None,
        cancelled: Event | None = None,
    ) -> PreparedUpdate:
        """下载到独立工作目录，校验成功后解包；不改当前程序和用户文件。"""
        installed = self._installed()
        if version_number(release.version) <= version_number(installed["version"]):
            raise UpdateError("目标版本没有高于当前版本")
        prefix = (
            f"https://github.com/{REPOSITORY}/releases/download/v{release.version}/"
        )
        if (
            release.archive_url != prefix + self.zip_name
            or release.checksum_url != prefix + self.zip_name + ".sha256"
        ):
            raise UpdateError("更新附件地址不属于当前发布")
        if type(release.size) is not int or not 0 < release.size <= MAX_PACKAGE_BYTES:
            raise UpdateError("更新包大小无效")
        import requests

        work = update_directory(self.root) / ("download-" + uuid.uuid4().hex)
        work.mkdir()
        try:
            if not self._prepare_incremental(release, work, progress, cancelled):
                checksum = work / (self.zip_name + ".sha256")
                self._download(release.checksum_url, checksum, 512, None, cancelled)
                match = re.fullmatch(
                    rf"([0-9a-fA-F]{{64}})  {re.escape(self.zip_name)}\s*",
                    checksum.read_text(encoding="ascii"),
                )
                if match is None:
                    raise UpdateError("SHA-256 文件格式无效")
                archive = work / self.zip_name
                self._download(
                    release.archive_url, archive, release.size, progress, cancelled
                )
                if (
                    archive.stat().st_size != release.size
                    or file_digest(archive) != match[1].lower()
                ):
                    raise UpdateError("下载包大小或 SHA-256 校验失败")
                unpack_package(
                    archive, work / "package", release.version, cancelled=cancelled
                )
            if manifest_frontend(load_manifest(work / "package")) != self.frontend:
                raise UpdateError("下载包与当前安装的前端类型不一致")
            if cancelled is not None and cancelled.is_set():
                raise UpdateCancelled("下载已取消")
        except (OSError, ValueError, requests.RequestException, zipfile.BadZipFile):
            logger.exception("准备更新失败")
            shutil.rmtree(work)
            raise
        return PreparedUpdate(work, release.version)

    def _prepare_incremental(
        self,
        release: ReleaseUpdate,
        work: Path,
        progress: Callable[[int, int], None] | None,
        cancelled: Event | None,
    ) -> bool:
        """复用统一解包流程，哈希一致的文件从当前安装补齐。

        远端不支持范围读取或目录损坏时返回 False，由调用方走全量下载；此时
        工作目录已恢复为刚创建的状态。清单校验失败不回退，避免重复下载。
        """
        package = work / "package"
        try:
            with open_archive(release.archive_url, cancelled=cancelled) as archive:
                if archive.size() != release.size:
                    raise UpdateError("远端归档大小与 Release 记录不符")
                unpack_package(
                    archive,
                    package,
                    release.version,
                    reuse_root=self.root,
                    progress=progress,
                    cancelled=cancelled,
                )
        except RemoteUnavailable as exc:
            logger.info("增量更新不可用，改用全量下载：%s", exc)
            if package.exists():
                shutil.rmtree(package)
            return False
        return True

    @staticmethod
    def _download(
        url: str,
        destination: Path,
        limit: int,
        progress: Callable | None,
        cancelled: Event | None,
    ) -> None:
        import requests

        with requests.get(url, stream=True, timeout=(10, 30)) as response:
            response.raise_for_status()
            received = 0
            with destination.open("xb") as output:
                for chunk in response.iter_content(1024**2):
                    if cancelled is not None and cancelled.is_set():
                        raise UpdateCancelled("下载已取消")
                    received += len(chunk)
                    if received > limit:
                        raise UpdateError("下载数据超出预期大小")
                    output.write(chunk)
                    if progress is not None:
                        progress(received, limit)

    def start_update(self, prepared: PreparedUpdate) -> Path:
        """启动独立安装器并等待 ready；返回后调用方应立即退出 GUI。"""
        self._installed()
        work = prepared.directory.resolve()
        if work.parent != update_directory(self.root) or not work.name.startswith(
            "download-"
        ):
            raise UpdateError("更新工作目录不属于当前安装")
        data = load_manifest(work / "package", verify=True)
        if data["version"] != prepared.version:
            raise UpdateError("待安装版本不一致")
        if manifest_frontend(data) != self.frontend:
            raise UpdateError("待安装包与当前安装的前端类型不一致")
        caller = psutil.Process()
        frontend = None
        if self.frontend == "rust" or Path(caller.exe()).resolve() in {
            self.root / CLI_EXE,
            self.root / QT_CLI_EXE,
        }:
            frontend = caller.parent()
            if (
                Path(caller.exe()).resolve()
                not in (
                    {self.root / CLI_EXE}
                    if self.frontend == "rust"
                    else {self.root / CLI_EXE, self.root / QT_CLI_EXE}
                )
                or frontend is None
                or Path(frontend.exe()).resolve() != self.root / APP_EXE
            ):
                raise UpdateError("安装更新须从当前助手窗口发起")
        excluded = {os.getpid()}
        if frontend is not None:
            excluded.add(frontend.pid)
        if helper_processes(self.root, excluded):
            raise UpdateError("当前仍有任务或其他窗口运行，请结束后重试")
        installed = load_manifest(self.root)
        worker_dir = work / ("worker-" + uuid.uuid4().hex)
        worker_dir.mkdir()
        worker = worker_dir / UPDATER_EXE
        source = self.root / UPDATER_EXE
        if file_digest(source) != installed["files"][UPDATER_EXE]:
            raise UpdateError("本地更新器校验失败")
        shutil.copy2(source, worker)
        ready, result = worker_dir / "ready.json", worker_dir / "result.json"
        cancel = worker_dir / "cancel"
        command = [
            str(worker),
            "--root",
            str(self.root),
            "--package",
            str(work / "package"),
            "--parent-pid",
            str(os.getpid()),
            "--parent-created",
            str(caller.create_time()),
            "--ready",
            str(ready),
            "--result",
            str(result),
            "--cancel",
            str(cancel),
            "--restart",
        ]
        if frontend is not None:
            command += [
                "--frontend-pid",
                str(frontend.pid),
                "--frontend-created",
                str(frontend.create_time()),
            ]
        process = subprocess.Popen(command, cwd=work, env=child_environment())
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if ready.exists():
                return result
            if process.poll() is not None:
                detail = (
                    result.read_text(encoding="utf-8")
                    if result.exists()
                    else str(process.returncode)
                )
                raise UpdateError(f"更新器启动失败: {detail}")
            time.sleep(0.1)
        # 只终止本次创建、尚未进入安装的工作进程；主程序仍持有运行共享锁。
        # onefile 子进程可能恰在枚举后启动；取消标记防止遗漏进程稍后安装。
        cancel.touch()
        try:
            children = psutil.Process(process.pid).children(recursive=True)
        except psutil.NoSuchProcess:
            children = []
        for child in children:
            try:
                child.kill()
            except psutil.NoSuchProcess:
                logger.debug("更新工作进程已退出: pid=%s", child.pid)
        process.kill()
        process.wait(timeout=10)
        psutil.wait_procs(children, timeout=10)
        raise UpdateError("更新器启动超时，当前版本未改变")


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
