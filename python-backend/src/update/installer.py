"""可恢复的程序文件替换；只操作新旧清单拥有的路径。"""

import errno
import json
import logging
import os
import shutil
import time
import uuid
from pathlib import Path

from src.update.package import (
    MANIFEST,
    VERSION_FILE,
    UpdateError,
    file_digest,
    load_manifest,
    manifest_frontend,
    safe_target,
    version_number,
)
from src.update.runtime import update_directory

logger = logging.getLogger(__name__)

REPLACE_ATTEMPTS = 5
REPLACE_BACKOFF_SECONDS = 0.2
# 文件被其他进程短暂持有：Windows 的拒绝访问与共享冲突，POSIX 的权限与占用。
TRANSIENT_WINERRORS = frozenset({5, 32, 33})
TRANSIENT_ERRNOS = frozenset({errno.EACCES, errno.EPERM, errno.EBUSY, errno.ETXTBSY})


def _transient_occupation(exc: OSError) -> bool:
    """瞬时占用可退避重试；其余失败立即上抛，不掩盖确定性错误。"""
    winerror = getattr(exc, "winerror", None)
    if winerror is not None:
        return winerror in TRANSIENT_WINERRORS
    return exc.errno in TRANSIENT_ERRNOS


def write_json(path: Path, data: dict) -> None:
    """临时文件与目标同目录；先 flush/fsync 再原子替换。"""
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as output:
        json.dump(data, output, ensure_ascii=False, indent=2)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


def _replace(source: Path, target: Path, temporary: Path) -> None:
    """copy/fsync/原子替换；占用退避重试，不让偶发失败中断整次安装或回滚。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            shutil.copy2(source, temporary)
            with temporary.open("r+b") as stream:
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            return
        except OSError as exc:
            if attempt + 1 == REPLACE_ATTEMPTS or not _transient_occupation(exc):
                raise
            delay = REPLACE_BACKOFF_SECONDS * 2**attempt
            logger.warning(
                "文件被占用，%.1f 秒后重试: %s (%s: %s)",
                delay,
                target.name,
                type(exc).__name__,
                exc,
            )
            time.sleep(delay)


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
    if manifest_frontend(old) != manifest_frontend(new):
        raise UpdateError("更新包与当前安装的前端类型不一致，请手动切换发行版")
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
            target = safe_target(root, name)
            if target.is_file() and file_digest(target) == new["files"][name]:
                # 内容已一致：重写只会多一次撞上文件被占用的机会。
                continue
            _replace(safe_target(package, name), target, work / "swap.tmp")
        _replace(package / MANIFEST, root / MANIFEST, work / "swap.tmp")
        load_manifest(root, verify=True)
        data["phase"] = "committed"
        write_json(journal, data)
    except (OSError, ValueError):
        logger.exception("安装失败，恢复旧程序文件")
        recover_installation(root)
        raise
    logger.info("已安装版本 %s", new["version"])


def settle_transaction(root: Path) -> bool:
    """启动闸门：能证明安装目录自洽就补完事务，否则交给显式恢复。

    中断的安装常只差元数据——程序文件已全部就位，只剩 version.json 与清单是旧版；
    此时把用户挡在门外只能手敲 --recover。安装目录与某个更高版本包逐文件一致时，
    用该包的元数据补齐后提交；证明不了就维持拒绝，不放行混合版本。
    """
    directory = update_directory(root)
    journal = directory / "transaction.json"
    if not journal.exists():
        return True
    data = json.loads(journal.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "phase" not in data:
        return False
    if data["phase"] in ("committed", "rolled_back"):
        return True
    if data["phase"] != "installing":
        return False
    if not _adopt_prepared_package(root, directory):
        return False
    data["phase"] = "committed"
    write_json(journal, data)
    logger.info("已补完中断的更新事务")
    return True


def _adopt_prepared_package(root: Path, directory: Path) -> bool:
    """安装目录与已准备包中版本更高、且程序文件逐一相同的那一个对齐元数据。"""
    try:
        current = load_manifest(root)
    except (OSError, ValueError) as exc:
        logger.warning("无法读取当前安装清单，不自动补完: %s", type(exc).__name__)
        return False
    current_version = version_number(current["version"])
    adopted = []
    for path in directory.glob(f"download-*/package/{MANIFEST}"):
        try:
            data = load_manifest(path.parent)
        except (OSError, ValueError) as exc:
            logger.warning("跳过无法读取的更新包: %s (%s)", path, type(exc).__name__)
            continue
        if manifest_frontend(data) != manifest_frontend(current):
            continue
        version = version_number(data["version"])
        if version <= current_version:
            continue
        try:
            matched = _matches_program_files(root, data)
        except (OSError, ValueError) as exc:
            logger.warning("核对安装目录失败: %s (%s)", path, type(exc).__name__)
            continue
        if matched:
            adopted.append((version, path.parent, data))
    if not adopted:
        return False
    _version, package, data = max(adopted, key=lambda item: item[0])
    # 先版本信息后清单：中途再中断时目录仍与包对得上，下次启动可重来。
    _replace(package / VERSION_FILE, root / VERSION_FILE, directory / "swap.tmp")
    _replace(package / MANIFEST, root / MANIFEST, directory / "swap.tmp")
    logger.info("安装目录已是 %s，补上清单与版本信息", data["version"])
    return True


def _matches_program_files(root: Path, data: dict) -> bool:
    """除元数据外程序文件是否已全是该包内容；元数据由采纳时补写。"""
    for name, digest in data["files"].items():
        if name == VERSION_FILE:
            continue
        target = safe_target(root, name)
        if not target.is_file() or file_digest(target) != digest:
            return False
    return True
