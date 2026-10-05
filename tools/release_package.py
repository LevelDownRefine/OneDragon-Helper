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
import tomllib
import zipfile
from pathlib import Path

# 作为独立脚本从 deploy/ 调用时，定位共享的纯 Python 更新包协议。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python-backend"))

from src.update.package import (  # noqa: E402
    CLI_EXE,
    MANIFEST,
    RUST_RUNTIME,
    UPDATER_EXE,
    load_manifest,
    managed_path,
    manifest_frontend,
    write_manifest,
)

EXE_NAME = "OneDragon-Helper.exe"
RUNNER_NAME = "OneDragon-Helper-Runner.exe"
VERSION_FILE = "version.json"
logger = logging.getLogger(__name__)


def resource_files(root: Path, frontend: str = "qt") -> list[str]:
    """收集 Git 跟踪的运行资源，拒绝误跟踪的用户配置与备份。"""
    manifest_frontend({"frontend": frontend})
    resources = ["config", "assets", "README.md"]
    if frontend == "qt":
        resources.append("python-gui/src/gui/qml")
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", *resources],
        cwd=root,
        check=True,
        capture_output=True,
    )
    names = sorted(result.stdout.decode("utf-8").split("\0")[:-1])
    packaged_names = [
        name.removeprefix("python-gui/")
        if name.startswith("python-gui/src/gui/qml/")
        else name
        for name in names
    ]
    for source_name, name in zip(names, packaged_names, strict=True):
        if not managed_path(name):
            raise ValueError(f"用户文件不能作为发布资源: {name}")
        if (root / source_name).is_symlink():
            raise ValueError(f"发布资源不能是符号链接: {source_name}")
    # PNG 图标已编译进 Rust EXE；Qt 使用矢量图标源，发布包无需再拷贝。
    return [name for name in packaged_names if not name.startswith("assets/icons/")]


def prepare_package(
    root: Path, package: Path, tag: str = "", *, frontend: str = "qt"
) -> None:
    """拷贝内置资源并写入构建版本；正式版本来自发布 tag。"""
    names = resource_files(root, frontend)
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
        with (root / "python-backend/pyproject.toml").open("rb") as source:
            project = tomllib.load(source)
        assert "project" in project and "version" in project["project"]
        version = f"{project['project']['version']}+dev.{commit[:7]}"
    for name in names:
        destination = package / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = root / (
            "python-gui/" + name if name.startswith("src/gui/qml/") else name
        )
        shutil.copy2(source, destination)
    metadata = {"version": version, "tag": tag, "commit": commit}
    if frontend == "rust":
        metadata["frontend"] = frontend
    (package / VERSION_FILE).write_text(
        json.dumps(metadata, indent=2) + "\n",
        encoding="utf-8",
    )
    files = names + [EXE_NAME, RUNNER_NAME, UPDATER_EXE, VERSION_FILE]
    if frontend == "rust":
        files.extend((CLI_EXE, RUST_RUNTIME))
    files += [
        path.relative_to(package).as_posix()
        for path in (package / "_internal").rglob("*")
        if path.is_file()
    ]
    write_manifest(package, files, version, frontend=frontend)
    validate_package(root, package)


def validate_package(root: Path, package: Path) -> list[Path]:
    """检查完整发布目录；清单外文件直接报错，避免发布个人数据或测试残留。"""
    frontend = manifest_frontend(load_manifest(package))
    expected = set(resource_files(root, frontend)) | {
        EXE_NAME,
        RUNNER_NAME,
        UPDATER_EXE,
        VERSION_FILE,
        MANIFEST,
    }
    if frontend == "rust":
        expected.update((CLI_EXE, RUST_RUNTIME))
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


def test_package(root: Path, package: Path) -> int:
    """只在临时副本运行 exe 集成测试，原发布目录始终保持干净。"""
    validate_package(root, package)
    directory = tempfile.TemporaryDirectory(prefix="odh_package_tests_")
    try:
        sandbox = Path(directory.name) / package.name
        shutil.copytree(package, sandbox)
        env = dict(os.environ)
        env.update(
            PYTHONPATH=os.pathsep.join(
                (
                    str(root / "python-gui/src"),
                    str(root / "python-backend"),
                    str(root / "python-backend/src"),
                    str(root),
                )
            ),
            ODH_PACKAGE_DIR=str(sandbox),
            ODH_GUI_EXE=str(sandbox / EXE_NAME),
            ODH_RUNNER_EXE=str(sandbox / RUNNER_NAME),
            ODH_CLI_EXE=str(sandbox / CLI_EXE),
        )
        result_code = 0
        for project in ("python-backend", "python-gui"):
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "unittest",
                    "discover",
                    "-s",
                    f"{project}/tests",
                    "-t",
                    project,
                    "-p",
                    "test_*_exe.py",
                    "-v",
                ],
                cwd=root,
                env=env,
                check=False,
            )
            result_code = result_code or result.returncode
    finally:
        try:
            directory.cleanup()
        except OSError as exc:
            logger.warning(
                "测试副本清理失败（%s）：%s；残留目录：%s。不影响测试结果。",
                type(exc).__name__,
                exc,
                directory.name,
            )
    validate_package(root, package)
    return result_code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "check", "archive", "test"))
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--tag", default=os.environ.get("ODH_RELEASE_TAG", ""))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--frontend", choices=("qt", "rust"), default="qt")
    args = parser.parse_args()
    root, package = args.root.resolve(), args.package.resolve()
    if args.action == "prepare":
        prepare_package(root, package, args.tag, frontend=args.frontend)
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
