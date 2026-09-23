"""独立更新器入口，不依赖 Qt；从安装目录之外的副本运行。"""

import argparse
import logging
import os
import subprocess
from pathlib import Path

import psutil

from src.service.update_installer import (
    install_package,
    recover_installation,
    write_json,
)
from src.service.update_package import APP_EXE
from src.service.update_runtime import (
    FileLease,
    UpdateBusyError,
    child_environment,
    helper_processes,
    update_directory,
)

logger = logging.getLogger(__name__)


def run_update(
    root: Path,
    package: Path | None,
    *,
    parent_pid: int = 0,
    parent_created: float = 0,
    ready: Path | None = None,
    cancel: Path | None = None,
    recover: bool = False,
) -> None:
    """先关闭启动闸门，再等待调用窗口释放运行锁；不终止任何已有任务。"""
    directory = update_directory(root)
    with FileLease(directory / "intent.lock"):
        parent = None
        if parent_pid:
            try:
                parent = psutil.Process(parent_pid)
                if parent.create_time() != parent_created:
                    raise UpdateBusyError("调用进程已变化，取消更新")
            except psutil.NoSuchProcess:
                parent = None
                logger.info("调用进程已经退出")
        occupied = helper_processes(root, {os.getpid(), parent_pid})
        if occupied:
            raise UpdateBusyError(f"当前安装仍有运行中的进程: {occupied}")
        if ready is not None:
            write_json(ready, {"status": "ready"})
        if parent is not None:
            try:
                parent.wait(timeout=30)
            except psutil.TimeoutExpired as exc:
                raise UpdateBusyError("窗口未退出，已取消安装") from exc
        with FileLease(directory / "runtime.lock", timeout=10):
            if cancel is not None and cancel.exists():
                raise UpdateBusyError("调用方已取消更新")
            occupied = helper_processes(root, {os.getpid()})
            if occupied:
                raise UpdateBusyError(f"当前安装仍有运行中的进程: {occupied}")
            if recover:
                recover_installation(root)
            else:
                assert package is not None
                install_package(root, package)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--package", type=Path)
    action.add_argument("--recover", action="store_true")
    parser.add_argument("--parent-pid", type=int, default=0)
    parser.add_argument("--parent-created", type=float, default=0)
    parser.add_argument("--ready", type=Path)
    parser.add_argument("--result", type=Path)
    parser.add_argument("--cancel", type=Path)
    parser.add_argument("--restart", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    directory = update_directory(root)
    logging.basicConfig(
        filename=directory / "update.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )
    result = args.result or directory / "result.json"

    def record_result(data):
        write_json(directory / "result.json", data)
        if result != directory / "result.json":
            write_json(result, data)

    try:
        run_update(
            root,
            args.package,
            parent_pid=args.parent_pid,
            parent_created=args.parent_created,
            ready=args.ready,
            cancel=args.cancel,
            recover=args.recover,
        )
    except (OSError, ValueError, psutil.Error) as exc:
        logger.exception("更新失败")
        record_result({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
        return 1
    record_result({"status": "recovered" if args.recover else "installed"})
    if args.restart:
        try:
            subprocess.Popen(
                [str(root / APP_EXE), "--after-update"],
                cwd=root,
                env=child_environment(),
            )
        except OSError as exc:
            logger.exception("更新完成但重启失败")
            record_result(
                {"status": "restart_failed", "error": f"{type(exc).__name__}: {exc}"},
            )
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
