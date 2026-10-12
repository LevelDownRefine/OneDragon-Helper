"""助手的更新适配与独立安装入口；下载和安装事务归 updater 库。"""

import argparse
import contextlib
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Event

import psutil
from updater import (
    GitHubRelease,
    GitHubUpdater,
    PreparedUpdate,
    UpdateCancelled,
    UpdateError,
)
from updater.utils import (
    FileLease,
    UpdateBusyError,
    linked_path,
    remove_directory,
    update_directory,
    version_number,
    write_json,
)

from src.utils.utils_io import load_data
from src.utils.utils_job import InvalidJob, JobExecutor

logger = logging.getLogger(__name__)
REPOSITORY = "LevelDownRefine/OneDragon-Helper"
RELEASES_URL = f"https://github.com/{REPOSITORY}/releases/latest"
APP_EXE = "OneDragon-Helper.exe"
CLI_EXE = "OneDragon-Helper-CLI.exe"
QT_CLI_EXE = "_internal/cli/" + CLI_EXE
RUNNER_EXE = "OneDragon-Helper-Runner.exe"
UPDATER_EXE = "OneDragon-Helper-Updater.exe"
VERSION_FILE = "version.json"
ARCHIVES = {"qt": "OneDragon-Helper.zip", "rust": "OneDragon-Helper-Rust.zip"}


def read_version(root: Path) -> dict:
    """读取助手构建元数据，未声明前端的旧版按 Qt 处理。"""
    if not (root / VERSION_FILE).is_file():
        raise UpdateError("缺少本地版本信息")
    data = load_data(root / VERSION_FILE, file_format="json")
    if (
        not isinstance(data, dict)
        or "version" not in data
        or not isinstance(data["version"], str)
    ):
        raise UpdateError("本地版本信息无效")
    version_number(data["version"])
    if "frontend" not in data:
        data["frontend"] = "qt"
    if not isinstance(data["frontend"], str) or data["frontend"] not in ARCHIVES:
        raise UpdateError("前端类型无效")
    return data


def client(root: Path, version: str, frontend: str) -> GitHubUpdater:
    assert frontend in ARCHIVES
    return GitHubUpdater(
        REPOSITORY,
        ARCHIVES[frontend],
        root,
        version,
        archive_prefix="OneDragon-Helper/",
    )


def child_environment() -> dict[str, str]:
    env = dict(os.environ)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def application_processes(root: Path, excluded: set[int] | None = None) -> list[int]:
    """按完整路径识别本安装的窗口、CLI 和 Runner。"""
    targets = {
        os.path.normcase(str((root / name).resolve()))
        for name in (APP_EXE, CLI_EXE, QT_CLI_EXE, RUNNER_EXE)
    }
    found = []
    for process in psutil.process_iter():
        if excluded is not None and process.pid in excluded:
            continue
        try:
            executable = process.exe()
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
        except psutil.AccessDenied:
            logger.debug("无法读取进程路径: pid=%s", process.pid)
            continue
        if executable and os.path.normcase(str(Path(executable).resolve())) in targets:
            found.append(process.pid)
    return found


@contextlib.contextmanager
def application_lease(root: Path):
    """配置初始化前通过更新闸门，整个应用进程持有共享运行锁。"""
    directory = update_directory(root)
    with contextlib.ExitStack() as stack:
        with FileLease(directory / "intent.lock"):
            journal = directory / "github-transaction.json"
            if journal.is_file():
                data = load_data(journal, file_format="json")
                if (
                    not isinstance(data, dict)
                    or "phase" not in data
                    or not isinstance(data["phase"], str)
                ):
                    raise UpdateError("安装事务信息无效")
                if data["phase"] == "installing":
                    with FileLease(directory / "runtime.lock"):
                        if application_processes(root, {os.getpid()}):
                            raise UpdateBusyError("仍有应用进程运行，不能恢复更新")
                        client(root, "0", "qt").recover()
                        write_json(directory / "result.json", {"status": "recovered"})
                elif data["phase"] not in {"committed", "rolled_back"}:
                    raise UpdateError("安装事务状态无效")
            stack.enter_context(FileLease(directory / "runtime.lock", shared=True))
        yield


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    unavailable_reason: str = ""
    previous_result: dict | None = None


class UpdateService:
    def __init__(self, root: Path | None = None, *, frontend: str = "qt"):
        from src.utils import get_root_dir

        assert frontend in ARCHIVES
        self.root = (root if root is not None else Path(get_root_dir())).resolve()
        self.frontend = frontend

    def get_update_info(self) -> UpdateInfo:
        """只读本地状态；构造和打开更新窗口不创建目录、不联网。"""
        previous = None
        result = self.root / ".update/result.json"
        if result.is_file():
            previous = load_data(result, file_format="json")
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
        if not (self.root / VERSION_FILE).is_file():
            return UpdateInfo(
                "未知版本", "缺少本地版本信息，请手动安装正式版。", previous
            )
        data = read_version(self.root)
        version = version_number(data["version"])
        reason = ""
        if data["frontend"] != self.frontend:
            reason = f"当前安装不是 {self.frontend} 发行版，请手动安装对应发布包"
        elif version.local is not None or version.is_devrelease:
            reason = "开发构建不支持在线更新，请使用正式发布版。"
        elif not (self.root / UPDATER_EXE).is_file():
            reason = "缺少独立更新器，请手动安装正式版。"
        return UpdateInfo(data["version"], reason, previous)

    def _client(self) -> GitHubUpdater:
        info = self.get_update_info()
        if info.unavailable_reason:
            raise UpdateError(info.unavailable_reason)
        return client(self.root, info.version, self.frontend)

    def check_update(self) -> GitHubRelease | None:
        return self._client().check()

    def prepare_update(
        self, release: GitHubRelease, *, progress=None, cancelled=None
    ) -> PreparedUpdate:
        updater = self._client()
        prepared = updater.download(release, progress=progress, cancelled=cancelled)
        try:
            data = read_version(prepared.directory / "package")
        except ValueError:
            # 无效元数据不能复用，否则显式重试仍会命中同一坏包。
            updater.discard(release)
            raise
        if data["frontend"] != self.frontend or data["version"] != prepared.version:
            updater.discard(release)
            raise UpdateError("下载包的版本或前端类型不一致")
        return prepared

    def start_update(self, prepared: PreparedUpdate) -> Path:
        """交接就绪后返回；窗口退出后独立进程才安装。"""
        self._client()
        work = prepared.directory.resolve()
        if (
            linked_path(prepared.directory)
            or work.parent != update_directory(self.root)
            or not work.name.startswith("github-")
        ):
            raise UpdateError("更新工作目录不属于当前安装")
        data = read_version(work / "package")
        if data["version"] != prepared.version or data["frontend"] != self.frontend:
            raise UpdateError("待安装包的版本或前端类型不一致")
        caller = psutil.Process()
        executable = Path(caller.exe()).resolve()
        frontend = None
        cli_executable = self.root / (
            CLI_EXE if self.frontend == "rust" else QT_CLI_EXE
        )
        if executable == cli_executable:
            frontend = caller.parent()
            if (
                frontend is None
                or Path(frontend.exe()).resolve() != self.root / APP_EXE
            ):
                raise UpdateError("安装更新须从当前应用窗口发起")
        elif self.frontend == "rust" or executable != self.root / APP_EXE:
            raise UpdateError("安装更新须从当前应用窗口发起")
        excluded = {os.getpid()}
        if frontend is not None:
            excluded.add(frontend.pid)
        if application_processes(self.root, excluded):
            raise UpdateError("当前仍有任务或其他窗口运行，请结束后重试")
        worker_dir = Path(tempfile.mkdtemp(prefix="odh-updater-"))
        worker = worker_dir / UPDATER_EXE
        shutil.copy2(self.root / UPDATER_EXE, worker)
        ready, result, cancel = (
            worker_dir / name for name in ("ready.json", "result.json", "cancel")
        )
        command = [
            str(worker),
            "--root",
            str(self.root),
            "--package",
            str(work),
            "--version",
            prepared.version,
            "--frontend",
            self.frontend,
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
        process = subprocess.Popen(command, cwd=worker_dir, env=child_environment())
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if ready.is_file() and process.poll() is None:
                try:
                    receipt = load_data(ready, file_format="json")
                except (OSError, ValueError) as exc:
                    # 回执读取失败也必须撤销交接，防止窗口之后退出触发安装。
                    cancel.touch()
                    raise UpdateError("无法读取更新器就绪回执") from exc
                if receipt != {"status": "ready", "version": prepared.version}:
                    cancel.touch()
                    raise UpdateError("更新器就绪回执无效")
                return result
            if process.poll() is not None:
                detail = (
                    result.read_text(encoding="utf-8")
                    if result.is_file()
                    else str(process.returncode)
                )
                raise UpdateError(f"更新器启动失败: {detail}")
            time.sleep(0.1)
        cancel.touch()
        raise UpdateError("更新器启动超时，当前版本未改变")


def run_update(
    root: Path,
    prepared: PreparedUpdate | None,
    *,
    frontend: str = "qt",
    parent_pid: int = 0,
    parent_created: float = 0,
    frontend_pid: int = 0,
    frontend_created: float = 0,
    ready: Path | None = None,
    cancel: Path | None = None,
    recover: bool = False,
) -> None:
    """关闭启动闸门并等待窗口退出；不终止任何已有任务。"""
    root = root.resolve()
    directory = update_directory(root)
    with FileLease(directory / "intent.lock"):
        waiting = []
        for pid, created, names in (
            (
                parent_pid,
                parent_created,
                (CLI_EXE if frontend == "rust" else QT_CLI_EXE,)
                if frontend_pid
                else (APP_EXE,),
            ),
            (frontend_pid, frontend_created, (APP_EXE,)),
        ):
            if not pid:
                continue
            # 进程退出可能发生在查询之间；只处理这个系统调用竞态。
            try:
                process = psutil.Process(pid)
                if process.create_time() != created or Path(
                    process.exe()
                ).resolve() not in {root / name for name in names}:
                    raise UpdateBusyError("调用进程身份已变化，取消更新")
                if (
                    pid == parent_pid
                    and frontend_pid
                    and process.ppid() != frontend_pid
                ):
                    raise UpdateBusyError("CLI 与应用窗口的父子关系已变化")
                waiting.append(process)
            except psutil.NoSuchProcess:
                logger.info("调用进程已经退出: pid=%s", pid)
        occupied = application_processes(root, {os.getpid(), parent_pid, frontend_pid})
        if occupied:
            raise UpdateBusyError(f"当前安装仍有运行中的进程: {occupied}")
        if ready is not None:
            if prepared is None:
                raise UpdateError("安装交接缺少程序包")
            write_json(ready, {"status": "ready", "version": prepared.version})
        deadline = time.monotonic() + 30
        for process in waiting:
            try:
                process.wait(timeout=max(0, deadline - time.monotonic()))
            except psutil.TimeoutExpired as exc:
                raise UpdateBusyError("窗口未退出，已取消安装") from exc
        with FileLease(directory / "runtime.lock", timeout=10):
            if cancel is not None and cancel.exists():
                raise UpdateBusyError("调用方已取消更新")
            occupied = application_processes(root, {os.getpid()})
            if occupied:
                raise UpdateBusyError(f"当前安装仍有运行中的进程: {occupied}")
            if recover:
                client(root, "0", frontend).recover()
            else:
                assert prepared is not None
                installed = read_version(root)
                target = read_version(prepared.directory / "package")
                if (
                    installed["frontend"] != frontend
                    or target["frontend"] != frontend
                    or target["version"] != prepared.version
                ):
                    raise UpdateError("待安装包的版本或前端类型不一致")
                client(root, installed["version"], frontend).install(prepared)
                # 安装成功后不再需要断点；清理失败不把已完成的更新报成失败。
                try:
                    remove_directory(prepared.directory)
                except OSError:
                    logger.warning(
                        "更新已安装，无法清理下载缓存: %s",
                        prepared.directory,
                        exc_info=True,
                    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--package", type=Path)
    action.add_argument("--recover", action="store_true")
    parser.add_argument("--version")
    parser.add_argument("--frontend", choices=tuple(ARCHIVES), default="qt")
    parser.add_argument("--parent-pid", type=int, default=0)
    parser.add_argument("--parent-created", type=float, default=0)
    parser.add_argument("--frontend-pid", type=int, default=0)
    parser.add_argument("--frontend-created", type=float, default=0)
    parser.add_argument("--ready", type=Path)
    parser.add_argument("--result", type=Path)
    parser.add_argument("--cancel", type=Path)
    parser.add_argument("--restart", action="store_true")
    args = parser.parse_args()
    if args.package is not None and args.version is None:
        parser.error("--package 需要 --version")
    root = args.root.resolve()
    directory = update_directory(root)
    logging.basicConfig(
        filename=directory / "update.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )
    result = args.result or directory / "result.json"

    def record(data):
        write_json(directory / "result.json", data)
        if result != directory / "result.json":
            write_json(result, data)

    try:
        run_update(
            root,
            PreparedUpdate(args.package, args.version)
            if args.package is not None
            else None,
            frontend=args.frontend,
            parent_pid=args.parent_pid,
            parent_created=args.parent_created,
            frontend_pid=args.frontend_pid,
            frontend_created=args.frontend_created,
            ready=args.ready,
            cancel=args.cancel,
            recover=args.recover,
        )
    except (OSError, ValueError, psutil.Error) as exc:
        logger.exception("更新失败")
        record({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
        return 1
    record({"status": "recovered" if args.recover else "installed"})
    if args.restart:
        try:
            subprocess.Popen(
                [str(root / APP_EXE), "--after-update"],
                cwd=root,
                env=child_environment(),
            )
        except OSError as exc:
            logger.exception("更新完成但重启失败")
            record(
                {"status": "restart_failed", "error": f"{type(exc).__name__}: {exc}"}
            )
            return 1
    return 0


class UpdateSession:
    """更新会话保留发布和待安装状态，耗时操作交给共享任务执行器。"""

    def __init__(self, service: UpdateService, jobs: JobExecutor):
        self._service = service
        self._jobs = jobs
        self._release: GitHubRelease | None = None
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


if __name__ == "__main__":
    raise SystemExit(main())
