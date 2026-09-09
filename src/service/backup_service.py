"""配置文件搬运：普通 ZIP，目录固定为 scripts/<脚本名>/<相对路径>。

目录正确性与上游兼容性由用户保证；仅对游戏路径字段保留本机值，无清单或版本协议。
恢复按当前脚本目录覆盖同名文件，保留额外文件，未配置的脚本跳过并报告。
"""

import json
import logging
import os
import shutil
import tempfile
import zipfile
import zlib
from datetime import datetime
from pathlib import Path, PureWindowsPath

from ruamel.yaml.error import YAMLError

from src.config.set_config import get_game_path_keys, iter_backup_paths
from src.utils import get_path_under_root
from src.utils.utils_sub_config import get_script_root_dir
from src.utils.utils_yaml import dump_yaml_str, load_yaml_str

logger = logging.getLogger(__name__)


def _write_zip(files: dict[str, Path]) -> str:
    """按 ZIP 内相对路径打包原文件，失败时清理本次不完整产物。"""
    directory = get_path_under_root("config", "backups")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = Path(directory, f"backup_{stamp}.zip")
    created = False
    try:
        with path.open("xb") as output:
            created = True
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
                for name, source in files.items():
                    archive.write(source, name)
    except (OSError, ValueError, zipfile.LargeZipFile):
        if created:
            path.unlink()
        raise
    logger.info("[backup] 已备份 %d 个文件：%s", len(files), path)
    return str(path)


def create_backup() -> dict:
    """收集声明目录内的全部文件与散装配置，返回 ZIP 路径和文件数。"""
    files: dict[str, Path] = {}
    for script_name, paths in iter_backup_paths().items():
        root = get_script_root_dir(script_name)
        if root is None:
            continue
        for rel in paths:
            source = Path(root, rel)
            if source.is_file():
                files[
                    f"scripts/{script_name}/{source.relative_to(root).as_posix()}"
                ] = source
                continue
            errors: list[OSError] = []
            if not source.exists():
                continue
            for directory, _, names in os.walk(source, onerror=errors.append):
                for name in names:
                    file = Path(directory, name)
                    files[
                        f"scripts/{script_name}/{file.relative_to(root).as_posix()}"
                    ] = file
            if errors:
                raise errors[0]
    if not files:
        raise ValueError("未找到可备份的配置文件，请检查脚本目录")
    return {"status": "ok", "path": _write_zip(files), "file_count": len(files)}


def _target_path(root: str, rel: str) -> Path:
    """ZIP 输入只允许脚本目录内的普通相对路径，拒绝穿越和链接重定向。"""
    parts = rel.split("/")
    if any(
        not part
        or part in (".", "..")
        or part.endswith((".", " "))
        or PureWindowsPath(part).is_reserved()
        or any(char in part for char in '\\:*?"<>|')
        or any(ord(char) < 32 for char in part)
        for part in parts
    ):
        raise ValueError(f"非法配置相对路径: {rel}")
    target = Path(root).resolve().joinpath(*parts)
    if target.resolve() != target:
        raise ValueError(f"配置路径包含链接或目录重定向: {rel}")
    return target


def _restore_targets(archive: zipfile.ZipFile) -> tuple[dict[str, Path], list[str]]:
    """由 ZIP 目录直接定位当前脚本；不读取旧包清单，不限制配置文件名。"""
    files: dict[str, Path] = {}
    targets: set[str] = set()
    skipped: set[str] = set()
    roots: dict[str, str | None] = {}
    for info in archive.infolist():
        if info.is_dir() or not info.filename.startswith("scripts/"):
            continue  # 普通说明文件及旧包的 manifest.json / self 目录不参与恢复。
        parts = info.filename.split("/", 2)
        if len(parts) != 3 or not parts[1]:
            raise ValueError(f"无效的 ZIP 目录: {info.filename}")
        _, script_name, rel = parts
        if script_name not in roots:
            roots[script_name] = get_script_root_dir(script_name)
        assert script_name in roots
        root = roots[script_name]
        if root is None:
            skipped.add(script_name)
            continue
        target = _target_path(root, rel)
        key = str(target).casefold()
        if key in targets:
            raise ValueError(f"ZIP 内存在重复目标: {target}")
        if target.exists() and not target.is_file():
            raise ValueError(f"恢复目标不是文件: {target}")
        targets.add(key)
        files[info.filename] = target
    for target in targets:
        if any(str(parent).casefold() in targets for parent in Path(target).parents):
            raise ValueError(f"恢复目标存在文件与目录冲突: {target}")
    if not files and not skipped:
        raise ValueError("ZIP 内没有 scripts/<脚本名>/<配置路径> 文件")
    bad_member = archive.testzip()
    if bad_member is not None:
        raise ValueError(f"ZIP 校验失败: {bad_member}")
    return files, sorted(skipped)


def _preserve_game_path(target: Path, temporary: Path, keys: tuple[str, ...]) -> None:
    """仅保留本机游戏路径字段（含空值）；本机缺失时不导入备份里的旧路径。"""
    assert keys
    ext = target.suffix.lower()
    if ext not in (".json", ".yaml", ".yml"):
        raise ValueError(f"不支持的游戏路径配置格式: {ext}")
    parse = json.loads if ext == ".json" else load_yaml_str
    current = parse(target.read_text(encoding="utf-8-sig")) if target.is_file() else {}
    payload = temporary.read_bytes()
    restored = parse(payload.decode("utf-8-sig"))
    if not isinstance(current, dict) or not isinstance(restored, dict):
        raise ValueError(f"游戏路径配置必须是对象: {target}")
    missing = object()
    value = current
    for key in keys:
        if not isinstance(value, dict):
            raise ValueError(f"本机游戏路径字段结构不兼容: {target}")
        if key not in value:
            value = missing
            break
        assert key in value
        value = value[key]
    node = restored
    for key in keys[:-1]:
        if key not in node:
            if value is missing:
                return
            node[key] = {}
        assert key in node
        node = node[key]
        if not isinstance(node, dict):
            raise ValueError(f"备份游戏路径字段结构不兼容: {target}")
    key = keys[-1]
    if value is missing:
        if key not in node:
            return
        del node[key]
    else:
        if key in node and node[key] == value:
            return
        node[key] = value
    text = (
        json.dumps(restored, ensure_ascii=False, indent=4)
        if ext == ".json"
        else dump_yaml_str(restored)
    )
    encoding = "utf-8-sig" if payload.startswith(b"\xef\xbb\xbf") else "utf-8"
    temporary.write_bytes(text.encode(encoding))


def _copy_member(archive: zipfile.ZipFile, name: str, target: Path) -> None:
    """以原始字节覆盖单个文件；写完临时文件后替换，避免截断现有配置。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=target.parent, prefix=".odh-", delete=False
    ) as output:
        temporary = Path(output.name)
    try:
        with archive.open(name) as source, temporary.open("wb") as output:
            shutil.copyfileobj(source, output)
        _, script_name, rel = name.split("/", 2)
        keys = get_game_path_keys(script_name, rel)
        if keys:
            _preserve_game_path(target, temporary, keys)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def restore_backup(zip_path: str) -> dict:
    """按当前脚本目录覆盖并保留游戏路径；失败报告进度与覆盖前的 ZIP 位置。

    Returns:
        status / restored / skipped_scripts / pre_backup；全部跳过时不创建备份。
    """
    restored = 0
    pre_backup = None
    try:
        with zipfile.ZipFile(zip_path) as archive:
            files, skipped = _restore_targets(archive)
            existing = {
                name: target for name, target in files.items() if target.is_file()
            }
            if existing:
                pre_backup = _write_zip(existing)
            try:
                for name, target in files.items():
                    _copy_member(archive, name, target)
                    restored += 1
            except (OSError, ValueError, YAMLError) as exc:
                raise OSError(
                    f"已恢复 {restored} 个文件，恢复失败且未回滚：{type(exc).__name__}: {exc}；"
                    f"恢复前备份: {pre_backup or '无（目标原先不存在）'}"
                ) from exc
    except (zipfile.BadZipFile, zlib.error, RuntimeError) as exc:
        raise ValueError(f"备份无法读取：{type(exc).__name__}: {exc}") from exc
    for script_name in skipped:
        logger.warning("[backup] 未配置脚本路径，跳过: %s", script_name)
    logger.info("[backup] 已恢复 %d 个文件，跳过 %d 个脚本", restored, len(skipped))
    return {
        "status": "partial"
        if restored and skipped
        else "ok"
        if restored
        else "skipped",
        "restored": restored,
        "skipped_scripts": skipped,
        "pre_backup": pre_backup,
    }
