"""无 Qt 脚本列表操作；文件导入只记录路径，不执行文件。"""

import os

from src.utils.utils_config import (
    add_script,
    build_script_entry,
    load_config,
    remove_script,
    save_config,
)
from src.utils.utils_sub_config import get_script_name, resolve_script_path


class InvalidScriptList(ValueError):
    """写入前发现的无效路径、重复脚本或过期列表。"""


class DuplicateScript(InvalidScriptList):
    """同进程名 EXE 已在列表，批量导入可继续处理其他文件。"""


def add(file_path: str) -> dict:
    """解析文件/快捷方式后复用添加流程，返回新标识与展示名。"""
    if not isinstance(file_path, str) or not file_path.strip():
        raise InvalidScriptList("请选择脚本文件")
    file_path = os.path.normpath(resolve_script_path(file_path.strip()))
    if not file_path.lower().endswith((".exe", ".bat", ".py", ".lnk")):
        raise InvalidScriptList("请选择 .exe、.bat、.py 或有效快捷方式")
    if not os.path.isfile(file_path):
        raise InvalidScriptList("脚本文件不存在")
    config = load_config()
    assert "script_list" in config
    existing = {get_script_name(script) for script in config["script_list"]}
    try:
        entry = build_script_entry(file_path, existing)
    except (OSError, ValueError) as exc:
        raise InvalidScriptList(f"无法读取脚本：{exc}") from exc
    name = get_script_name(entry)
    if name in existing:
        raise DuplicateScript(f"脚本已存在：{name}")
    add_script(entry)
    assert "display_name" in entry
    return {"script_name": name, "display_name": entry["display_name"]}


def remove(script_name: str) -> None:
    """从助手列表删除已确认条目，保留至少一个脚本。"""
    config = load_config()
    assert "script_list" in config
    scripts = config["script_list"]
    if not any(get_script_name(script) == script_name for script in scripts):
        raise InvalidScriptList("脚本已不存在，请刷新列表")
    if len(scripts) <= 1:
        raise InvalidScriptList("至少保留一个脚本，无法删除")
    remove_script(script_name)


def reorder(script_names: list[str]) -> None:
    """按完整标识列表重排；拒绝过期快照，不遗漏外部新增条目。"""
    if not isinstance(script_names, list) or any(
        not isinstance(name, str) or not name for name in script_names
    ):
        raise InvalidScriptList("脚本顺序格式无效")
    config = load_config()
    assert "script_list" in config
    entries = {get_script_name(script): script for script in config["script_list"]}
    if len(script_names) != len(entries) or set(script_names) != set(entries):
        raise InvalidScriptList("脚本列表已变化，请刷新后重排")
    assert all(name in entries for name in script_names)
    config["script_list"] = [entries[name] for name in script_names]
    save_config(config)
