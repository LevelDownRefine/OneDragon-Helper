"""更新测试的最小程序包；不依赖真实用户配置。"""

import json
import zipfile
from pathlib import Path

from src.service.update_package import MANIFEST, REQUIRED_FILES, write_manifest


def make_package(root: Path, version="1.0.0", extra=None):
    root.mkdir(parents=True, exist_ok=True)
    content = {name: f"program {version}".encode() for name in REQUIRED_FILES}
    content["_internal/python.dll"] = b"runtime"
    content["version.json"] = json.dumps({"version": version}).encode()
    content.update(extra or {})
    for name, body in content.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    write_manifest(root, list(content), version)
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
