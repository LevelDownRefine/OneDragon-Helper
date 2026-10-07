"""更新测试的最小程序包；不依赖真实用户配置。"""

import json
import shutil
import zipfile
from pathlib import Path

from src.update.package import (
    MANIFEST,
    REQUIRED_FILES,
    RUST_REQUIRED_FILES,
    VERSION_FILE,
    file_digest,
    load_manifest,
    write_manifest,
)


def make_package(root: Path, version="1.0.0", extra=None, *, frontend="qt"):
    root.mkdir(parents=True, exist_ok=True)
    required = RUST_REQUIRED_FILES if frontend == "rust" else REQUIRED_FILES
    content = {name: f"program {version}".encode() for name in required}
    content["_internal/python.dll"] = b"runtime"
    info = {"version": version}
    if frontend == "rust":
        info["frontend"] = frontend
    content["version.json"] = json.dumps(info).encode()
    content.update(extra or {})
    for name, body in content.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    write_manifest(root, list(content), version, frontend=frontend)
    return root


def archive_package(root: Path, output: Path):
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in root.rglob("*"):
            if path.is_file():
                archive.write(
                    path, "OneDragon-Helper/" + path.relative_to(root).as_posix()
                )
    return output


def program_snapshot(root: Path):
    data = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    return {
        name: (root / name).read_bytes() for name in set(data["files"]) | {MANIFEST}
    }


def stage_started_install(root: Path) -> None:
    """摆出事务已开始、但一个程序文件都还没换的现场：快照与安装目录同版本。"""
    identity = "0" * 32
    snapshot = root / ".update" / identity / "previous"
    originals = {}
    for name in (MANIFEST, VERSION_FILE):
        destination = snapshot / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / name, destination)
        originals[name] = file_digest(root / name)
    journal = root / ".update/transaction.json"
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text(
        json.dumps(
            {"phase": "installing", "transaction": identity, "originals": originals}
        ),
        encoding="utf-8",
    )


def stage_interrupted_install(root: Path, package: Path) -> None:
    """摆出中断现场：程序文件已是新版，只剩清单与版本信息还是旧版。"""
    stage_started_install(root)
    for name in load_manifest(package)["files"]:
        if name in (MANIFEST, VERSION_FILE):
            continue
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(package / name, target)
