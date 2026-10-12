"""更新测试的普通 ZIP 夹具；不依赖真实配置或发布清单。"""

import json
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from updater import GitHubRelease, GitHubUpdater
from updater.utils import file_digest

from src.update import (
    APP_EXE,
    ARCHIVES,
    CLI_EXE,
    QT_CLI_EXE,
    REPOSITORY,
    RUNNER_EXE,
    UPDATER_EXE,
)


def make_package(root: Path, version="1.0.0", extra=None, *, frontend="qt"):
    root.mkdir(parents=True, exist_ok=True)
    names = {
        APP_EXE,
        RUNNER_EXE,
        UPDATER_EXE,
        "config/config.example.yml",
        "config/schedule.example.yml",
        "config/weekly.example.yml",
        "_internal/python.dll",
    }
    names.update(
        {CLI_EXE, "vcruntime140.dll"}
        if frontend == "rust"
        else {QT_CLI_EXE, "src/gui/qml/main.qml"}
    )
    content = {name: f"program {version}".encode() for name in names}
    content["version.json"] = json.dumps(
        {"version": version, "frontend": frontend}
    ).encode()
    content.update(extra or {})
    for name, body in content.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
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
    inventory = root / ".update/github-installed.json"
    if inventory.is_file():
        data = json.loads(inventory.read_text(encoding="utf-8"))
        assert "files" in data
        names = data["files"]
    else:
        names = [
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file() and ".update" not in path.relative_to(root).parts
        ]
    return {name: file_digest(root / name) for name in names}


def release(version="2.0.0", *, frontend="qt", size=100, sha256=None):
    tag = "v" + version
    return GitHubRelease(
        tag,
        version,
        "notes",
        1,
        f"https://github.com/{REPOSITORY}/releases/download/{tag}/{ARCHIVES[frontend]}",
        size,
        sha256,
    )


def prepare_package(install: Path, package: Path, version: str, frontend: str):
    """通过真实下载接口暂存普通 ZIP，HTTP 使用本地字节流。"""
    with tempfile.TemporaryDirectory() as temporary:
        archive = archive_package(package, Path(temporary) / "package.zip")
        size = archive.stat().st_size
        target = release(
            version, frontend=frontend, size=size, sha256=file_digest(archive)
        )
        response = MagicMock()
        response.__enter__.return_value = response
        response.status_code = 200
        response.headers = {"Content-Length": str(size)}
        updater = GitHubUpdater(
            REPOSITORY,
            ARCHIVES[frontend],
            install,
            "0",
            archive_prefix="OneDragon-Helper/",
        )
        with archive.open("rb") as source, patch("requests.get", return_value=response):
            response.iter_content.return_value = iter(lambda: source.read(65536), b"")
            return updater.download(target)
