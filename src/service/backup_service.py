"""子脚本配置备份与恢复：把各子脚本 config 打包成单个 zip，按需回写。

产物为单个 zip（``config/backups/backup_<时间戳>.zip``），内部结构：

    manifest.json                       条目清单（kind / rel / src / arc），恢复时按 src 回写
    scripts/<脚本名>/<rel_path>         子脚本配置（rel_path 为适配层备份范围的展开结果）

子脚本 config 的「配置面在哪」归适配层（:mod:`src.config.set_config`）：每个脚本声明
``_backup_paths``（元素可为目录或文件），本模块按条展开——目录递归收录、文件直接收录、
不存在即跳过（脚本未安装属常态）。

恢复按 manifest 的 ``src`` 回写；子脚本 config 里**已设置**的游戏路径保留现值
（键路径由适配层 ``get_game_path_keys`` 给出）——游戏路径与机器绑定，换机恢复时旧值多半
已失效。恢复前先自动备份当前状态，便于回退。
"""

import json
import logging
import os
import zipfile
from datetime import datetime

from src.config.set_config import get_game_path_keys, iter_backup_paths
from src.utils import get_path_under_root, safe_path_join
from src.utils.utils_sub_config import get_script_root_dir
from src.utils.utils_yaml import dump_yaml_str, load_yaml_str

logger = logging.getLogger(__name__)

MANIFEST_VERSION = 1
"""manifest 结构版本；恢复侧据此识别（结构变更即升版）。"""

MANIFEST_NAME = "manifest.json"
"""zip 内清单文件名。"""

_BACKUP_SUBS = ("config", "backups")
"""备份产物目录（相对项目根）。"""

_SCRIPT_ARC = "scripts"
"""zip 内子脚本配置的前缀。"""


def get_backup_dir() -> str:
    """备份产物目录（``config/backups``，不存在则创建）。

    Returns:
        备份目录绝对路径。
    """
    return get_path_under_root(*_BACKUP_SUBS)


def _script_entry(script_name: str, rel: str, src: str) -> dict:
    """构造子脚本配置条目（arc 为 zip 内路径）。"""
    return {
        "kind": "script",
        "script_name": script_name,
        "rel": rel,
        "src": src,
        "arc": f"{_SCRIPT_ARC}/{script_name}/{rel}",
    }


def _path_entries(script_name: str, root: str, rel: str) -> list[dict]:
    """展开一条备份路径：目录递归收录全部文件，文件则收录该条；不存在即跳过。

    Args:
        script_name: 脚本唯一标识。
        root: 脚本根目录。
        rel: 备份路径（目录或文件），相对脚本根目录。

    Returns:
        条目列表；路径不存在（脚本未安装 / 尚未生成）时为空列表。
    """
    abs_path = safe_path_join(root, rel)
    if os.path.isfile(abs_path):
        return [_script_entry(script_name, rel, abs_path)]
    if not os.path.isdir(abs_path):
        return []  # 脚本未安装 / 尚未生成 config：跳过，不中断整包
    entries: list[dict] = []
    for dirpath, _, filenames in os.walk(abs_path):
        for name in filenames:
            src = os.path.join(dirpath, name)
            file_rel = f"{rel}/{os.path.relpath(src, abs_path).replace(os.sep, '/')}"
            entries.append(_script_entry(script_name, file_rel, src))
    return entries


def _script_entries() -> list[dict]:
    """遍历各已适配脚本的备份范围（目录递归 / 单文件收录，缺失即跳过）。

    Returns:
        条目列表，每项含 kind="script" / script_name / rel（相对脚本根目录）/ src / arc。
    """
    entries: list[dict] = []
    for script_name, rel_paths in sorted(iter_backup_paths().items()):
        root = get_script_root_dir(script_name)
        if root is None:
            continue  # config.yml 无此脚本或 script_path 为空：无从定位，跳过
        for rel in rel_paths:
            entries.extend(_path_entries(script_name, root, rel))
    return entries


def collect_entries() -> list[dict]:
    """汇总待备份条目（各子脚本 config）。

    Returns:
        条目列表。
    """
    return _script_entries()


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
    """一键备份：把各子脚本 config 打包为单个 zip。

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
    logger.info("[backup] 已备份 %d 个子脚本配置文件 → %s", len(entries), path)
    return path


# ============================================================
# 恢复
# ============================================================


def _parse(text: str, ext: str) -> dict | list:
    """按扩展名解析配置文本（json / yaml）。"""
    if ext == ".json":
        return json.loads(text)
    if ext in (".yaml", ".yml"):
        return load_yaml_str(text)
    raise ValueError(f"[backup] 不支持的 config 格式: {ext}")


def _dump(data: dict | list, ext: str) -> str:
    """按扩展名序列化配置为文本（json / yaml）。"""
    if ext == ".json":
        return json.dumps(data, ensure_ascii=False, indent=4)
    if ext in (".yaml", ".yml"):
        return dump_yaml_str(data)
    raise ValueError(f"[backup] 不支持的 config 格式: {ext}")


def _game_path_value(data: dict | list, keys: tuple[str, ...]) -> str:
    """按嵌套键取游戏路径值；结构缺失或值非字符串时返回空字符串。"""
    node = data
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return ""
        node = node[key]
    return node if isinstance(node, str) else ""


def _keep_game_path(
    payload: str, target: str, keys: tuple[str, ...], ext: str
) -> tuple[str, bool]:
    """目标文件已设置游戏路径时保留现值，其余字段用备份内容覆盖。

    Args:
        payload: 备份中的文件内容文本。
        target: 目标文件绝对路径。
        keys: 游戏路径的嵌套键路径。
        ext: 文件扩展名（决定解析格式）。

    Returns:
        (待写入文本, 是否保留了现有游戏路径)；目标不存在、解析失败或现有值为空
        时不保留，原样返回 payload。
    """
    if not os.path.isfile(target):
        return payload, False
    try:
        with open(target, encoding="utf-8") as f:
            current = _parse(f.read(), ext)
        data = _parse(payload, ext)
    except (OSError, ValueError, TypeError):
        return payload, False
    value = _game_path_value(current, keys)
    if not value.strip():
        return payload, False
    # 沿键路径下钻；备份结构缺失（脚本版本演进 / 旧备份字段未生成）即放弃保留，
    # 退回用备份值覆盖，绝不为单条坏数据中断整次恢复。
    node = data
    for key in keys[:-1]:
        if not isinstance(node, dict) or key not in node:
            logger.warning("[backup] 备份缺少游戏路径中间字段 %s，跳过保留现值", keys)
            return payload, False
        node = node[key]
    if not isinstance(node, dict) or keys[-1] not in node:
        logger.warning("[backup] 备份缺少游戏路径字段 %s，跳过保留现值", keys)
        return payload, False
    node[keys[-1]] = value
    return _dump(data, ext), True


def restore_backup(zip_path: str) -> dict:
    """一键恢复：按 manifest 把子脚本 config 回写原位置（仅 kind=script 条目；旧备份的 self 条目跳过）。

    恢复前先备份当前状态（便于回退）。子脚本 config 里**已设置**的游戏路径
    保留现值不覆盖（游戏路径与机器绑定，换机恢复时旧值多半已失效）。

    Args:
        zip_path: 备份 zip 路径（须存在）。

    Returns:
        统计 dict：status / zip / restored / game_path_kept / pre_backup。

    Raises:
        AssertionError: zip 不存在，或 manifest 版本不受支持。
        OSError: 目标不可写（权限不足 / 磁盘满）。
    """
    assert os.path.isfile(zip_path), f"[backup] 备份文件不存在: {zip_path}"
    manifest = read_manifest(zip_path)
    assert manifest["version"] == MANIFEST_VERSION, (
        f"[backup] 不支持的备份版本: {manifest['version']}"
    )

    pre_backup = create_backup()
    restored = 0
    game_path_kept = 0
    with zipfile.ZipFile(zip_path) as archive:
        for entry in manifest["entries"]:
            # 只恢复子脚本 config；旧备份里的 self 条目跳过（与备份口径一致）
            if entry.get("kind") != "script":
                continue
            target = entry["src"]
            os.makedirs(os.path.dirname(target), exist_ok=True)
            ext = os.path.splitext(target)[1].lower()
            payload = archive.read(entry["arc"]).decode("utf-8")
            keys = get_game_path_keys(entry["script_name"], entry["rel"])
            if keys:
                payload, kept = _keep_game_path(payload, target, keys, ext)
                game_path_kept += kept
            # newline=""：按备份原文的换行落盘，不被 Windows 转成 \r\n
            with open(target, "w", encoding="utf-8", newline="") as f:
                f.write(payload)
            restored += 1
    if restored == 0:
        logger.warning("[backup] %s 中无可恢复的子脚本条目", zip_path)
    logger.info(
        "[backup] 已从 %s 恢复 %d 个文件（保留游戏路径 %d 处）",
        zip_path,
        restored,
        game_path_kept,
    )
    return {
        "status": "ok",
        "zip": zip_path,
        "restored": restored,
        "game_path_kept": game_path_kept,
        "pre_backup": pre_backup,
    }
