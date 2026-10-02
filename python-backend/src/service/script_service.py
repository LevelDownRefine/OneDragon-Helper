"""脚本管理：增删改与排序的校验、跨配置编排，无 GUI/传输依赖。

输入错误在写入前拒绝；写入失败即停止，已完成的步骤不回滚、不重试。
"""

import os
from dataclasses import dataclass, field, replace

from src.config.set_config import init_config
from src.config.task_options import task_options_of
from src.config.task_switch import task_switch_of
from src.utils import utils_config, utils_weekly
from src.utils.utils_shortcut import read_shortcut
from src.utils.utils_sub_config import (
    default_script_entry,
    get_script_name,
    resolve_script_path,
)

_TEXT_FIELDS = (
    "script_path",
    "script_type",
    "script_arguments",
    "check_done",
    "game_process_name",
    "game_path",
    "game_arguments",
)
_BOOL_FIELDS = ("kill_script_after_done", "kill_game_after_done", "block")


@dataclass(frozen=True)
class ScriptEdit:
    """一次完整编辑的输入；冻结字段绑定，不保证容器深层不可变。"""

    script_name: str  # 编辑前标识
    display_name: str
    config_patch: dict[str, str | bool]  # config.yml
    weekly_timeouts: list[int | None]  # weekly.yml
    switches: dict[str, bool]  # 脚本自身 config
    task_options: dict[str, bool | str | list[str]] = field(default_factory=dict)


class InvalidScript(ValueError):
    """写入前发现的无效输入或过期脚本状态。"""


class DuplicateScript(InvalidScript):
    """同标识 EXE 已在列表，批量导入可继续处理其他文件。"""


def validate_edit(
    edit: ScriptEdit, *, script_names: set[str] | None = None
) -> ScriptEdit:
    """校验并规范化输入；保存时复用本次读取的标识集合，不重复读盘。"""
    if not isinstance(edit.script_name, str) or not edit.script_name:
        raise InvalidScript("脚本标识不能为空")
    if not isinstance(edit.display_name, str) or not edit.display_name.strip():
        raise InvalidScript("脚本名称不能为空")
    patch = edit.config_patch
    if not isinstance(patch, dict) or set(patch) != set(_TEXT_FIELDS + _BOOL_FIELDS):
        raise InvalidScript("脚本配置字段不完整或包含未知字段")
    for key in _TEXT_FIELDS:
        assert key in patch
        if not isinstance(patch[key], str):
            raise InvalidScript(f"{key} 必须是文本")
    for key in _BOOL_FIELDS:
        assert key in patch
        if type(patch[key]) is not bool:
            raise InvalidScript(f"{key} 必须是开关")
    patch = {
        key: value.strip() if isinstance(value, str) else value
        for key, value in patch.items()
    }
    assert all(key in patch for key in _TEXT_FIELDS + _BOOL_FIELDS)
    if not patch["script_path"]:
        raise InvalidScript("脚本路径不能为空")
    if patch["script_type"] not in ("external", "python"):
        raise InvalidScript("脚本类型无效")
    if patch["check_done"] not in (
        "script_closed",
        "game_closed",
        "game_or_script_closed",
    ):
        raise InvalidScript("完成检测方式无效")
    if patch["game_path"] and not os.path.isfile(patch["game_path"]):
        raise InvalidScript("游戏路径不存在")
    if not patch["game_process_name"]:
        patch["kill_game_after_done"] = False
    if (
        not isinstance(edit.weekly_timeouts, list)
        or len(edit.weekly_timeouts) != 7
        or any(
            value is not None and (type(value) is not int or not 0 <= value <= 86400)
            for value in edit.weekly_timeouts
        )
    ):
        raise InvalidScript("每周超时须为七项 0～86400 秒或空值")
    if not isinstance(edit.switches, dict) or any(
        not isinstance(name, str) or not name or type(value) is not bool
        for name, value in edit.switches.items()
    ):
        raise InvalidScript("任务开关格式无效")
    display_name = edit.display_name.strip()
    new_script_name = get_script_name({**patch, "display_name": display_name})
    if not isinstance(edit.task_options, dict):
        raise InvalidScript("任务选项格式无效")
    if edit.task_options:
        if new_script_name != edit.script_name:
            raise InvalidScript("修改脚本标识后请刷新，再编辑任务选项")
        try:
            task_options_of(edit.script_name).prepare(edit.task_options)
        except ValueError as exc:
            raise InvalidScript(str(exc)) from exc
    if new_script_name != edit.script_name:
        if script_names is None:
            config = utils_config.load_config()
            assert "script_list" in config
            script_names = {get_script_name(script) for script in config["script_list"]}
        if new_script_name in script_names:
            raise InvalidScript("已存在同标识脚本，请修改路径或名称")
    return replace(edit, display_name=display_name, config_patch=patch)


def add(file_path: str) -> dict:
    """登记脚本条目、创建每周默认参数并初始化，返回标识与展示名。"""
    if not isinstance(file_path, str) or not file_path.strip():
        raise InvalidScript("请选择脚本文件")
    file_path = os.path.normpath(resolve_script_path(file_path.strip()))
    if not file_path.lower().endswith((".exe", ".bat", ".py", ".lnk")):
        raise InvalidScript("请选择 .exe、.bat、.py 或有效快捷方式")
    if not os.path.isfile(file_path):
        raise InvalidScript("脚本文件不存在")
    config = utils_config.load_config()
    assert "script_list" in config
    existing = {get_script_name(script) for script in config["script_list"]}

    script_arguments = ""
    if file_path.lower().endswith(".lnk"):
        try:
            file_path, script_arguments, working_dir = read_shortcut(file_path)
        except (OSError, ValueError) as exc:
            raise InvalidScript(f"无法读取脚本：{exc}") from exc
        file_path = os.path.normpath(os.path.expandvars(file_path))
        if not file_path.lower().endswith((".exe", ".bat", ".py")):
            raise InvalidScript("快捷方式未指向 .exe、.bat 或 .py 文件")
        if not os.path.isfile(file_path):
            raise InvalidScript("快捷方式的目标文件不存在")
        # 运行器以目标所在目录启动，不能丢弃不同的起始位置。
        if working_dir and os.path.normcase(
            os.path.realpath(os.path.expandvars(working_dir))
        ) != os.path.normcase(os.path.realpath(os.path.dirname(file_path))):
            raise InvalidScript("快捷方式指定了不同的工作目录，暂不支持导入")

    base_name = os.path.splitext(os.path.basename(file_path))[0]
    display_name = base_name
    suffix = 1
    while display_name in existing:
        display_name = f"{base_name}_{suffix}"
        suffix += 1
    entry = default_script_entry(
        display_name=display_name,
        script_type="python" if file_path.lower().endswith(".py") else "external",
        script_path=file_path,
        script_arguments=script_arguments,
    )
    script_name = get_script_name(entry)
    if script_name in existing:
        raise DuplicateScript(f"脚本已存在：{script_name}")
    config["script_list"].append(entry)
    utils_config.save_config(config)
    utils_weekly.ensure_weekly_entry(script_name)
    init_config(script_name)
    assert "display_name" in entry
    return {"script_name": script_name, "display_name": entry["display_name"]}


def remove(script_name: str) -> None:
    """从助手列表删除已确认条目，保留至少一个脚本。"""
    config = utils_config.load_config()
    assert "script_list" in config
    scripts = config["script_list"]
    target = next(
        (script for script in scripts if get_script_name(script) == script_name), None
    )
    if target is None:
        raise InvalidScript("脚本已不存在，请刷新列表")
    if len(scripts) <= 1:
        raise InvalidScript("至少保留一个脚本，无法删除")
    scripts.remove(target)
    utils_config.save_config(config)
    utils_weekly.delete_weekly(script_name)


def update(edit: ScriptEdit) -> str:
    """保存完整编辑，按新标识同步每周参数、初始化及任务开关。"""
    config = utils_config.load_config()
    assert "script_list" in config
    scripts = config["script_list"]
    edit = validate_edit(
        edit, script_names={get_script_name(script) for script in scripts}
    )
    target = next(
        (script for script in scripts if get_script_name(script) == edit.script_name),
        None,
    )
    if target is None:
        raise InvalidScript("脚本已不存在，请刷新列表")
    assert "script_path" in target and "script_path" in edit.config_patch
    previous_path = target["script_path"]
    if edit.task_options and previous_path != edit.config_patch["script_path"]:
        raise InvalidScript("修改脚本路径后请刷新，再编辑任务选项")
    options = task_options_of(edit.script_name) if edit.task_options else None
    try:
        pending = options.prepare(edit.task_options) if options is not None else []
    except ValueError as exc:
        raise InvalidScript(str(exc)) from exc

    target.update(edit.config_patch)
    target["display_name"] = edit.display_name
    new_script_name = get_script_name(target)
    utils_config.save_config(config)
    if new_script_name != edit.script_name:
        utils_weekly.rename_weekly(edit.script_name, new_script_name)
    utils_weekly.save_weekly(new_script_name, edit.weekly_timeouts)
    if (
        previous_path != edit.config_patch["script_path"]
        or new_script_name != edit.script_name
    ):
        init_config(new_script_name)
    switch = task_switch_of(new_script_name)
    if options is not None:
        options.write_prepared(pending)
    if switch is not None:
        switch.write(edit.switches)
    return new_script_name


def reorder(script_names: list[str]) -> None:
    """按完整标识列表重排；拒绝过期快照，不遗漏外部新增条目。"""
    if not isinstance(script_names, list) or any(
        not isinstance(name, str) or not name for name in script_names
    ):
        raise InvalidScript("脚本顺序格式无效")
    config = utils_config.load_config()
    assert "script_list" in config
    entries = {get_script_name(script): script for script in config["script_list"]}
    if len(script_names) != len(entries) or set(script_names) != set(entries):
        raise InvalidScript("脚本列表已变化，请刷新后重排")
    assert all(name in entries for name in script_names)
    config["script_list"] = [entries[name] for name in script_names]
    utils_config.save_config(config)
