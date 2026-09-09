"""配置备份：把自身 config 目录与各子脚本 config 打包成单个 zip。

产物为单个 zip（``config/backups/backup_<时间戳>.zip``），内部结构：

    manifest.json               条目清单（kind / rel / src / arc），恢复时按 src 回写
    self/<config 内相对路径>     自身配置（config/ 整个目录，排除备份产物目录）
    scripts/<脚本名>/<rel_path>  子脚本配置（rel_path 由 set_config 适配层声明）

子脚本 config 的「有哪些、在哪」归适配层（:mod:`src.config.set_config`）：
整目录都是 config 的（如 ok-ww 的 ``working/configs``、BetterGI 的 ``User``）按目录递归
打包，目录外的单文件（如崩铁的 ``config.yaml``）另按声明补；两者重叠时以目录为准去重。
脚本未安装 / config 未生成（不存在）时跳过，不中断整包备份。
"""

import json
import logging
import os
import zipfile
from datetime import datetime

from src.config.set_config import iter_config_dir_rel_paths, iter_config_rel_paths
from src.utils import get_path_under_root, get_root_dir, safe_path_join
from src.utils.utils_sub_config import get_script_root_dir

logger = logging.getLogger(__name__)

MANIFEST_VERSION = 1
"""manifest 结构版本；恢复侧据此识别（结构变更即升版）。"""

MANIFEST_NAME = "manifest.json"
"""zip 内清单文件名。"""

_BACKUP_SUBS = ("config", "backups")
"""备份产物目录（相对项目根）。"""

_SELF_ARC = "self"
"""zip 内自身配置的前缀。"""

_SCRIPT_ARC = "scripts"
"""zip 内子脚本配置的前缀。"""


def get_backup_dir() -> str:
    """备份产物目录（``config/backups``，不存在则创建）。

    Returns:
        备份目录绝对路径。
    """
    return get_path_under_root(*_BACKUP_SUBS)


def _self_entries() -> list[dict]:
    """遍历自身 config 目录下的全部文件（排除备份产物目录）。

    Returns:
        条目列表，每项含 kind="self" / rel（相对 config 目录）/ src / arc。
    """
    config_dir = safe_path_join(get_root_dir(), "config")
    backup_dir = get_backup_dir()
    entries: list[dict] = []
    for dirpath, dirnames, filenames in os.walk(config_dir):
        # 备份产物目录就地排除：否则备份会把自己嵌套进去
        dirnames[:] = [
            d
            for d in dirnames
            if os.path.abspath(os.path.join(dirpath, d)) != os.path.abspath(backup_dir)
        ]
        for name in filenames:
            src = os.path.join(dirpath, name)
            rel = os.path.relpath(src, config_dir).replace(os.sep, "/")
            entries.append(
                {
                    "kind": "self",
                    "rel": rel,
                    "src": src,
                    "arc": f"{_SELF_ARC}/{rel}",
                }
            )
    return entries


def _script_entry(script_name: str, rel: str, src: str) -> dict:
    """构造子脚本配置条目（arc 为 zip 内路径）。"""
    return {
        "kind": "script",
        "script_name": script_name,
        "rel": rel,
        "src": src,
        "arc": f"{_SCRIPT_ARC}/{script_name}/{rel}",
    }


def _dir_entries(script_name: str, root: str, rel_dir: str) -> list[dict]:
    """递归收集 config 目录下的全部文件（整个目录都是 config）。

    Args:
        script_name: 脚本唯一标识。
        root: 脚本根目录。
        rel_dir: config 目录相对脚本根目录的路径。

    Returns:
        条目列表；目录不存在（脚本未安装 / 尚未生成）时为空列表。
    """
    abs_dir = safe_path_join(root, rel_dir)
    if not os.path.isdir(abs_dir):
        return []
    entries: list[dict] = []
    for dirpath, _, filenames in os.walk(abs_dir):
        for name in filenames:
            src = os.path.join(dirpath, name)
            rel = f"{rel_dir}/{os.path.relpath(src, abs_dir).replace(os.sep, '/')}"
            entries.append(_script_entry(script_name, rel, src))
    return entries


def _script_entries() -> list[dict]:
    """遍历各已适配脚本的 config 目录（整目录）与目录外的单文件（缺失即跳过）。

    Returns:
        条目列表，每项含 kind="script" / script_name / rel（相对脚本根目录）/ src / arc。
    """
    dirs = iter_config_dir_rel_paths()
    files = iter_config_rel_paths()
    entries: list[dict] = []
    for script_name in sorted(set(dirs) | set(files)):
        root = get_script_root_dir(script_name)
        if root is None:
            continue  # config.yml 无此脚本或 script_path 为空：无从定位，跳过
        packed = (
            _dir_entries(script_name, root, dirs[script_name])
            if script_name in dirs
            else []
        )
        entries.extend(packed)
        packed_rels = {entry["rel"] for entry in packed}
        for rel in files.get(script_name, []):
            if rel in packed_rels:
                continue  # 已随整目录打包
            src = safe_path_join(root, rel)
            if not os.path.exists(src):
                continue  # 脚本未安装 / 尚未生成 config：跳过，不中断整包
            entries.append(_script_entry(script_name, rel, src))
    return entries


def collect_entries() -> list[dict]:
    """汇总待备份条目（自身配置 + 各子脚本 config）。

    Returns:
        条目列表（先自身后子脚本）。
    """
    return _self_entries() + _script_entries()


def read_manifest(zip_path: str) -> dict:
    """读备份产物的清单（供 CLI 回显与后续恢复）。

    Args:
        zip_path: 备份 zip 路径。

    Returns:
        manifest dict（含 version / created_at / entries）。

    Raises:
        KeyError: 压缩包内无 manifest.json（非本工具产物）。
    """
    with zipfile.ZipFile(zip_path) as archive:
        return json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))


def _next_backup_path(stamp: str) -> str:
    """按时间戳拼产物路径；同秒重复时追加序号，避免覆盖已有备份。"""
    backup_dir = get_backup_dir()
    path = safe_path_join(backup_dir, f"backup_{stamp}.zip")
    index = 1
    while os.path.exists(path):
        index += 1
        path = safe_path_join(backup_dir, f"backup_{stamp}_{index}.zip")
    return path


def create_backup() -> str:
    """一键备份：把自身配置与各子脚本 config 打包为单个 zip。

    Returns:
        产物 zip 的绝对路径。

    Raises:
        OSError: 产物目录不可创建或 zip 不可写（磁盘满 / 权限不足）。
    """
    entries = collect_entries()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = _next_backup_path(stamp)
    manifest = {
        "version": MANIFEST_VERSION,
        "created_at": stamp,
        "entries": entries,
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2)
        )
        for entry in entries:
            archive.write(entry["src"], entry["arc"])
    logger.info(
        "[backup] 已备份 %d 个文件（自身 %d / 子脚本 %d）→ %s",
        len(entries),
        sum(1 for e in entries if e["kind"] == "self"),
        sum(1 for e in entries if e["kind"] == "script"),
        path,
    )
    return path
