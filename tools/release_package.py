"""发布包准备、检查与归档；用户文件不属于发布资源。"""

import argparse
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import zipfile
from pathlib import Path

# 作为独立脚本从 deploy/ 调用时，定位共享的纯 Python 更新包协议。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.service.update_package import (  # noqa: E402
    MANIFEST,
    UPDATER_EXE,
    load_manifest,
    managed_path,
    write_manifest,
)

EXE_NAME = "OneDragon-Helper.exe"
RUNNER_NAME = "OneDragon-Helper-Runner.exe"
VERSION_FILE = "version.json"
logger = logging.getLogger(__name__)
_CLEANUP_DELAYS = (0.1, 0.2, 0.4, 0.8, 1.5, 2.0)


def resource_files(root: Path) -> list[str]:
    """仅收集 Git 跟踪的内置资源，拒绝误跟踪的用户配置与备份。"""
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", "config", "assets", "src/gui/qml", "README.md"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    names = sorted(result.stdout.decode("utf-8").split("\0")[:-1])
    for name in names:
        if not managed_path(name):
            raise ValueError(f"用户文件不能作为发布资源: {name}")
        if (root / name).is_symlink():
            raise ValueError(f"发布资源不能是符号链接: {name}")
    return names


def prepare_package(root: Path, package: Path, tag: str = "") -> None:
    """拷贝内置资源并写入构建版本；正式版本来自发布 tag。"""
    names = resource_files(root)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if tag:
        if not re.fullmatch(r"v\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", tag):
            raise ValueError(f"发布 tag 必须是 v主版本.次版本.修订版本: {tag}")
        version = tag[1:]
    else:
        with (root / "pyproject.toml").open("rb") as source:
            project = tomllib.load(source)
        assert "project" in project and "version" in project["project"]
        version = f"{project['project']['version']}+dev.{commit[:7]}"
    for name in names:
        destination = package / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / name, destination)
    (package / VERSION_FILE).write_text(
        json.dumps({"version": version, "tag": tag, "commit": commit}, indent=2) + "\n",
        encoding="utf-8",
    )
    files = names + [EXE_NAME, RUNNER_NAME, UPDATER_EXE, VERSION_FILE]
    files += [
        path.relative_to(package).as_posix()
        for path in (package / "_internal").rglob("*")
        if path.is_file()
    ]
    write_manifest(package, files, version)
    validate_package(root, package)


def validate_package(root: Path, package: Path) -> list[Path]:
    """检查完整发布目录；清单外文件直接报错，避免发布个人数据或测试残留。"""
    expected = set(resource_files(root)) | {
        EXE_NAME,
        RUNNER_NAME,
        UPDATER_EXE,
        VERSION_FILE,
        MANIFEST,
    }
    allowed_dirs = {"_internal"}
    for name in expected:
        allowed_dirs.update(
            str(parent) for parent in Path(name).parents if str(parent) != "."
        )
    found: set[str] = set()
    files = []
    for path in sorted(package.rglob("*")):
        name = path.relative_to(package).as_posix()
        if path.is_symlink():
            raise ValueError(f"发布包不能包含符号链接: {name}")
        if path.is_dir():
            if (
                path.parts[len(package.parts)] != "_internal"
                and str(Path(name)) not in allowed_dirs
            ):
                raise ValueError(f"发布包包含非程序目录: {name}")
            continue
        if name not in expected and not name.startswith("_internal/"):
            raise ValueError(f"发布包包含非程序文件: {name}")
        found.add(name)
        files.append(path)
    missing = expected - found
    if missing:
        raise ValueError(f"发布包缺少文件: {', '.join(sorted(missing))}")
    if not any(name.startswith("_internal/") for name in found):
        raise ValueError("发布包缺少 _internal 运行库")
    manifest = load_manifest(package, verify=True)
    if found != set(manifest["files"]) | {MANIFEST}:
        raise ValueError("发布包文件与更新清单不一致")
    return files


def archive_package(root: Path, package: Path, output: Path) -> None:
    """校验后生成 ZIP 与 SHA-256 文件，ZIP 中保留顶层程序目录。"""
    files = validate_package(root, package)
    if output.resolve().is_relative_to(package.resolve()):
        raise ValueError("ZIP 输出不能位于发布目录内")
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, Path(package.name) / path.relative_to(package))
    with output.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    output.with_suffix(output.suffix + ".sha256").write_text(
        f"{digest}  {output.name}\n", encoding="ascii"
    )


def cleanup_test_directory(directory: tempfile.TemporaryDirectory) -> None:
    """等待 Windows 短暂 DLL 占用解除；持续失败仍使构建失败。"""
    path = Path(directory.name).resolve()
    assert path.parent == Path(tempfile.gettempdir()).resolve()
    assert path.name.startswith("odh_package_tests_")
    for delay in (*_CLEANUP_DELAYS, None):
        try:
            directory.cleanup()
            return
        except PermissionError:
            if delay is None:
                logger.exception(
                    "测试副本仍被占用，无法清理，请关闭占用进程后重试：%s", path
                )
                raise
            logger.warning(
                "测试副本清理遇到 PermissionError，%.1f 秒后重试：%s", delay, path
            )
            time.sleep(delay)


def test_package(root: Path, package: Path) -> int:
    """只在临时副本运行 exe 集成测试，原发布目录始终保持干净。"""
    validate_package(root, package)
    directory = tempfile.TemporaryDirectory(prefix="odh_package_tests_")
    try:
        sandbox = Path(directory.name) / package.name
        shutil.copytree(package, sandbox)
        env = dict(os.environ)
        env.update(
            ODH_PACKAGE_DIR=str(sandbox),
            ODH_GUI_EXE=str(sandbox / EXE_NAME),
            ODH_RUNNER_EXE=str(sandbox / RUNNER_NAME),
        )
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                "tests",
                "-t",
                ".",
                "-p",
                "test_*_exe.py",
            ],
            cwd=root,
            env=env,
            check=False,
        )
    finally:
        cleanup_test_directory(directory)
    validate_package(root, package)
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "check", "archive", "test"))
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--tag", default=os.environ.get("ODH_RELEASE_TAG", ""))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root, package = args.root.resolve(), args.package.resolve()
    if args.action == "prepare":
        prepare_package(root, package, args.tag)
    elif args.action == "check":
        validate_package(root, package)
    elif args.action == "archive":
        if args.output is None:
            parser.error("archive 需要 --output")
        archive_package(root, package, args.output)
    else:
        return test_package(root, package)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
