"""更新包协议与路径边界；构建工具、下载服务、独立安装器共用。"""

import hashlib
import json
import re
import shutil
import stat
import zipfile
from collections.abc import Callable
from concurrent.futures import CancelledError
from contextlib import nullcontext
from pathlib import Path, PureWindowsPath
from threading import Event

from packaging.version import InvalidVersion, Version

APP_EXE = "OneDragon-Helper.exe"
CLI_EXE = "OneDragon-Helper-CLI.exe"
RUST_RUNTIME = "vcruntime140.dll"
RUNNER_EXE = "OneDragon-Helper-Runner.exe"
UPDATER_EXE = "OneDragon-Helper-Updater.exe"
MANIFEST = "update-manifest.json"
VERSION_FILE = "version.json"
REQUIRED_FILES = {
    APP_EXE,
    RUNNER_EXE,
    UPDATER_EXE,
    VERSION_FILE,
    "config/config.example.yml",
    "config/schedule.example.yml",
    "config/weekly.example.yml",
    "src/gui/qml/main.qml",
}
RUST_REQUIRED_FILES = (REQUIRED_FILES - {"src/gui/qml/main.qml"}) | {
    CLI_EXE,
    RUST_RUNTIME,
}
USER_CONFIG = {
    "config.yml",
    "schedule.yml",
    "weekly.yml",
    "notify_mail.yml",
    "wallpaper.json",
    "gui_state.json",
}
MAX_PACKAGE_BYTES = 4 * 1024**3


class UpdateError(ValueError):
    """可恢复的更新输入或状态错误。"""


class UpdateCancelled(UpdateError, CancelledError):
    """用户中断下载；已下载的部分保留，供下次续传。"""


def check_cancelled(cancelled: Event | None) -> None:
    if cancelled is not None and cancelled.is_set():
        raise UpdateCancelled("下载已取消")


def version_number(value: str) -> Version:
    """按版本语义比较，不按字符串比较。"""
    try:
        return Version(value)
    except InvalidVersion as exc:
        raise UpdateError(f"无法识别版本号: {value}") from exc


def managed_path(name: str) -> bool:
    """只允许程序文件，拒绝 Windows 路径别名和用户数据。"""
    if not isinstance(name, str) or not name:
        return False
    parts = name.split("/")
    if any(
        not part
        or part in (".", "..")
        or part.endswith((".", " "))
        or PureWindowsPath(part).is_reserved()
        or any(char in part for char in '\\:*?"<>|')
        or any(ord(char) < 32 for char in part)
        or re.search(r"\.bak\d*$", part, re.IGNORECASE)
        or part.casefold()
        in {"logs", ".log", "backups", "wallpaper_cache", "script_chain", ".update"}
        for part in parts
    ):
        return False
    if name in {
        APP_EXE,
        CLI_EXE,
        RUST_RUNTIME,
        RUNNER_EXE,
        UPDATER_EXE,
        VERSION_FILE,
        MANIFEST,
        "README.md",
    }:
        return True
    if parts[0] == "config":
        return len(parts) >= 2 and parts[1].casefold() not in USER_CONFIG
    if name.casefold() == "assets/banner.jpg":
        return False
    return name.startswith(("_internal/", "assets/", "src/gui/qml/"))


def linked_path(path: Path) -> bool:
    """符号链接或 Windows junction；更新路径不允许落在链接后面。"""
    return path.is_symlink() or bool(
        path.exists() and getattr(path.lstat(), "st_file_attributes", 0) & 0x400
    )


def safe_target(root: Path, name: str) -> Path:
    """拒绝用户目录、符号链接和 Windows junction 造成的路径逃逸。

    root 自身不查链接：安装目录本来就是用户挑的，挪到 junction 后面是合理用法。
    """
    if not managed_path(name):
        raise UpdateError(f"更新包包含非程序路径: {name}")
    target = root / name
    for item in (target, *target.parents):
        if item == root:
            break
        if linked_path(item):
            raise UpdateError(f"更新路径不能经过链接: {name}")
    if not target.resolve().is_relative_to(root.resolve()):
        raise UpdateError(f"更新路径越界: {name}")
    return target


def file_digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def manifest_frontend(data: dict) -> str:
    """旧清单缺省 Qt；未知外部包类型明确拒绝。"""
    frontend = "qt"
    if "frontend" in data:
        frontend = data["frontend"]
    if not isinstance(frontend, str) or frontend not in {"qt", "rust"}:
        raise UpdateError("不支持的前端类型")
    return frontend


def parse_manifest(data: object) -> dict:
    """校验文件清单，包含大小写重名及文件/目录冲突。"""
    if not isinstance(data, dict) or not {"schema", "version", "files"} <= data.keys():
        raise UpdateError("更新清单缺少 schema/version/files")
    if data["schema"] != 1 or not isinstance(data["version"], str):
        raise UpdateError("不支持的更新清单版本")
    version_number(data["version"])
    required = (
        RUST_REQUIRED_FILES if manifest_frontend(data) == "rust" else REQUIRED_FILES
    )
    files = data["files"]
    if (
        not isinstance(files, dict)
        or not files.keys() >= required
        or not any(name.startswith("_internal/") for name in files)
    ):
        raise UpdateError("更新清单缺少必要程序文件")
    names = set()
    for name, digest in files.items():
        if name == MANIFEST or not managed_path(name):
            raise UpdateError(f"更新清单包含非程序文件: {name}")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise UpdateError(f"文件校验值无效: {name}")
        folded = name.casefold()
        if folded in names:
            raise UpdateError(f"更新清单路径重复: {name}")
        names.add(folded)
    for name in names:
        if any(parent.as_posix() in names for parent in Path(name).parents):
            raise UpdateError(f"更新清单文件与目录冲突: {name}")
    return data


def verify_installation(root: Path, data: dict) -> None:
    """安装目录须逐文件匹配清单，且版本信息与本包前端类型一致。"""
    for name, digest in data["files"].items():
        target = safe_target(root, name)
        if not target.is_file() or file_digest(target) != digest:
            raise UpdateError(f"程序文件校验失败: {name}")
    info = json.loads((root / VERSION_FILE).read_text(encoding="utf-8"))
    if (
        not isinstance(info, dict)
        or "version" not in info
        or info["version"] != data["version"]
    ):
        raise UpdateError("版本信息与更新清单不一致")
    if manifest_frontend(info) != manifest_frontend(data):
        raise UpdateError("版本信息与更新清单的前端类型不一致")


def load_manifest(root: Path, *, verify: bool = False) -> dict:
    path = safe_target(root, MANIFEST)
    if not path.is_file():
        raise UpdateError("当前安装缺少更新清单，请先手动安装支持更新的版本")
    data = parse_manifest(json.loads(path.read_text(encoding="utf-8")))
    if verify:
        verify_installation(root, data)
    return data


def write_manifest(
    root: Path, names: list[str], version: str, *, frontend: str = "qt"
) -> None:
    assert frontend in {"qt", "rust"}
    data = {
        "schema": 1,
        "version": version,
        "files": {name: file_digest(safe_target(root, name)) for name in sorted(names)},
    }
    if frontend == "rust":
        data["frontend"] = frontend
    parse_manifest(data)
    (root / MANIFEST).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def unpack_package(
    archive: Path | zipfile.ZipFile,
    destination: Path,
    expected_version: str,
    *,
    reuse_root: Path | None = None,
    progress: Callable[[int, int], None] | None = None,
    cancelled: Event | None = None,
) -> dict:
    """本地与远端 ZIP 共用校验和流式解包，允许复用哈希一致的已安装文件。

    目标目录可以已存在：哈希一致的条目视为上次已下完，只补齐其余条目。
    """
    if linked_path(destination):
        raise UpdateError("解包目录不能是链接")
    prefix = "OneDragon-Helper/"
    check_cancelled(cancelled)
    context = (
        nullcontext(archive)
        if isinstance(archive, zipfile.ZipFile)
        else zipfile.ZipFile(archive)
    )
    with context as source:
        members = source.infolist()
        if (
            len(members) > 20000
            or sum(item.file_size for item in members) > MAX_PACKAGE_BYTES
        ):
            raise UpdateError("更新包解压后过大")
        entries = {}
        for item in members:
            name = item.filename
            if item.is_dir():
                # 发布工具只写文件；拒绝其他形态，避免两套路径验证规则。
                raise UpdateError(f"更新包包含非文件条目: {name}")
            if (
                not name.startswith(prefix)
                or stat.S_ISLNK(item.external_attr >> 16)
                or item.flag_bits & 1
            ):
                raise UpdateError(f"更新包路径或文件类型无效: {name}")
            relative = name[len(prefix) :]
            if not managed_path(relative) or relative.casefold() in entries:
                raise UpdateError(f"更新包文件重复或不允许: {name}")
            entries[relative.casefold()] = (relative, item)
        manifest_key = MANIFEST.casefold()
        if manifest_key not in entries:
            raise UpdateError("下载包缺少更新清单")
        manifest_info = entries[manifest_key][1]
        if manifest_info.file_size > 4 * 1024**2:
            raise UpdateError("更新清单过大")
        manifest_bytes = source.read(manifest_info)
        data = parse_manifest(json.loads(manifest_bytes))
        if data["version"] != expected_version:
            raise UpdateError("下载包版本与所选 Release 不一致")
        expected = set(data["files"]) | {MANIFEST}
        if {name for name, _item in entries.values()} != expected:
            raise UpdateError("更新包文件与清单不一致")
        destination.mkdir(parents=True, exist_ok=True)
        sizes = {name: item.file_size for name, item in entries.values()}
        reused = {}
        resumed_names = set()
        resumed = 0
        for name, digest in data["files"].items():
            check_cancelled(cancelled)
            downloaded = safe_target(destination, name)
            if downloaded.exists() and not downloaded.is_file():
                # 同名目录会让写盘一直失败，只能当确定性失败清掉工作目录。
                raise UpdateError(f"下载目录里存在同名目录: {name}")
            if downloaded.is_file() and file_digest(downloaded) == digest:
                resumed_names.add(name)
                resumed += sizes[name]
                continue
            if reuse_root is not None:
                installed = safe_target(reuse_root, name)
                if installed.is_file() and file_digest(installed) == digest:
                    reused[name] = installed
        total = resumed + sum(
            item.file_size
            for name, item in entries.values()
            if name != MANIFEST and name not in reused and name not in resumed_names
        )
        completed = resumed
        (destination / MANIFEST).write_bytes(manifest_bytes)
        # 先报一次断点位置：整段命中缓存时下面不会再回调。
        if progress is not None:
            progress(completed, total)
        for name, item in entries.values():
            check_cancelled(cancelled)
            if name == MANIFEST or name in resumed_names:
                continue
            target = safe_target(destination, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            if name in reused:
                shutil.copy2(reused[name], target)
                continue
            with source.open(item) as reader, target.open("wb") as writer:
                while chunk := reader.read(65536):
                    check_cancelled(cancelled)
                    writer.write(chunk)
                    completed += len(chunk)
                    if progress is not None:
                        progress(completed, total)
        check_cancelled(cancelled)
    return load_manifest(destination, verify=True)
