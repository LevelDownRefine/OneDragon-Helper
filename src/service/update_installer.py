"""可恢复的程序文件替换；只操作新旧清单拥有的路径。"""

import json
import logging
import os
import shutil
import uuid
from pathlib import Path

from src.service.update_package import (
    MANIFEST,
    UpdateError,
    file_digest,
    load_manifest,
    safe_target,
    version_number,
)
from src.service.update_runtime import update_directory

logger = logging.getLogger(__name__)


def write_json(path: Path, data: dict) -> None:
    """临时文件与目标同目录；先 flush/fsync 再原子替换。"""
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as output:
        json.dump(data, output, ensure_ascii=False, indent=2)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


def _replace(source: Path, target: Path, temporary: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, temporary)
    with temporary.open("r+b") as stream:
        os.fsync(stream.fileno())
    os.replace(temporary, target)


def recover_installation(root: Path) -> bool:
    """按持久化记录恢复所有旧文件，重复执行也安全；调用方须持有更新锁。"""
    directory = update_directory(root)
    journal = directory / "transaction.json"
    if not journal.exists():
        return False
    data = json.loads(journal.read_text(encoding="utf-8"))
    if (
        not isinstance(data, dict)
        or not {"phase", "transaction", "originals"} <= data.keys()
    ):
        raise UpdateError("更新恢复记录损坏")
    if data["phase"] in ("committed", "rolled_back"):
        return False
    if data["phase"] != "installing":
        raise UpdateError("无法识别更新恢复状态")
    identity = data["transaction"]
    if (
        not isinstance(identity, str)
        or len(identity) != 32
        or any(c not in "0123456789abcdef" for c in identity)
    ):
        raise UpdateError("更新恢复目录无效")
    work = directory / identity
    originals = data["originals"]
    if not isinstance(originals, dict) or not originals:
        raise UpdateError("更新恢复清单无效")
    # 先检查全部快照，再开始恢复，避免损坏快照造成二次部分恢复。
    for name, digest in originals.items():
        safe_target(root, name)
        source = safe_target(work / "previous", name)
        if digest is not None and (
            not source.is_file() or file_digest(source) != digest
        ):
            raise UpdateError(f"恢复快照损坏: {name}")
    for name, digest in originals.items():
        target = safe_target(root, name)
        if digest is None:
            target.unlink(missing_ok=True)
        else:
            if target.is_file() and file_digest(target) == digest:
                continue
            _replace(safe_target(work / "previous", name), target, work / "swap.tmp")
    data["phase"] = "rolled_back"
    write_json(journal, data)
    logger.info("更新已恢复到旧版本")
    return True


def install_package(root: Path, package: Path) -> None:
    """准备完整旧文件快照后才改程序文件；调用方须持有更新锁。"""
    directory = update_directory(root)
    recover_installation(root)
    old = load_manifest(root)
    new = load_manifest(package, verify=True)
    if version_number(new["version"]) <= version_number(old["version"]):
        raise UpdateError("目标版本没有高于当前版本")
    old_names = set(old["files"]) | {MANIFEST}
    new_names = set(new["files"]) | {MANIFEST}
    for name in old_names | new_names:
        target = safe_target(root, name)
        if target.exists() and (not target.is_file() or name not in old_names):
            raise UpdateError(f"新程序文件与已有用户文件冲突: {name}")
    identity = uuid.uuid4().hex
    work = directory / identity
    work.mkdir()
    originals = {}
    for name in sorted(old_names | new_names):
        target = safe_target(root, name)
        if target.is_file():
            previous = safe_target(work / "previous", name)
            previous.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, previous)
            with previous.open("r+b") as stream:
                os.fsync(stream.fileno())
            originals[name] = file_digest(previous)
        else:
            originals[name] = None
    data = {"phase": "installing", "transaction": identity, "originals": originals}
    journal = directory / "transaction.json"
    write_json(journal, data)
    try:
        for name in sorted(old_names - new_names):
            safe_target(root, name).unlink(missing_ok=True)
        for name in sorted(new_names - {MANIFEST}):
            _replace(
                safe_target(package, name), safe_target(root, name), work / "swap.tmp"
            )
        _replace(package / MANIFEST, root / MANIFEST, work / "swap.tmp")
        load_manifest(root, verify=True)
        data["phase"] = "committed"
        write_json(journal, data)
    except (OSError, ValueError):
        logger.exception("安装失败，恢复旧程序文件")
        recover_installation(root)
        raise
    logger.info("已安装版本 %s", new["version"])
