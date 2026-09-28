"""完整脚本编辑：输入校验与跨配置保存流程，无 GUI/传输依赖。"""

import os
from dataclasses import dataclass, replace

from src.config.set_config import init_config
from src.config.task_switch import task_switch_of
from src.utils import utils_config, utils_weekly
from src.utils.utils_sub_config import get_script_name

_TEXT_FIELDS = (
    "script_path",
    "script_type",
    "script_arguments",
    "check_done",
    "game_process_name",
    "game_path",
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


class InvalidScriptEdit(ValueError):
    """尚未写入的可恢复编辑错误。"""


def validate_edit(edit: ScriptEdit) -> ScriptEdit:
    """校验并返回规范化的编辑输入，不写盘或修改传入对象。"""
    if not isinstance(edit.script_name, str) or not edit.script_name:
        raise InvalidScriptEdit("脚本标识不能为空")
    if not isinstance(edit.display_name, str) or not edit.display_name.strip():
        raise InvalidScriptEdit("脚本名称不能为空")
    patch = edit.config_patch
    if not isinstance(patch, dict) or set(patch) != set(_TEXT_FIELDS + _BOOL_FIELDS):
        raise InvalidScriptEdit("脚本配置字段不完整或包含未知字段")
    for key in _TEXT_FIELDS:
        assert key in patch
        if not isinstance(patch[key], str):
            raise InvalidScriptEdit(f"{key} 必须是文本")
    for key in _BOOL_FIELDS:
        assert key in patch
        if type(patch[key]) is not bool:
            raise InvalidScriptEdit(f"{key} 必须是开关")
    patch = {
        key: value.strip() if isinstance(value, str) else value
        for key, value in patch.items()
    }
    assert all(key in patch for key in _TEXT_FIELDS + _BOOL_FIELDS)
    if not patch["script_path"]:
        raise InvalidScriptEdit("脚本路径不能为空")
    if patch["script_type"] not in ("external", "python"):
        raise InvalidScriptEdit("脚本类型无效")
    if patch["check_done"] not in (
        "script_closed",
        "game_closed",
        "game_or_script_closed",
    ):
        raise InvalidScriptEdit("完成检测方式无效")
    if patch["game_path"] and not os.path.isfile(patch["game_path"]):
        raise InvalidScriptEdit("游戏路径不存在")
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
        raise InvalidScriptEdit("每周超时须为七项 0～86400 秒或空值")
    if not isinstance(edit.switches, dict) or any(
        not isinstance(name, str) or not name or type(value) is not bool
        for name, value in edit.switches.items()
    ):
        raise InvalidScriptEdit("任务开关格式无效")
    display_name = edit.display_name.strip()
    identity = get_script_name({**patch, "display_name": display_name})
    if identity != edit.script_name and utils_config.get_script(identity) is not None:
        raise InvalidScriptEdit("已存在同标识脚本，请修改路径或名称")
    return replace(edit, display_name=display_name, config_patch=patch)


def save(edit: ScriptEdit) -> str:
    """应用完整编辑并返回保存后的标识；失败即停止，已完成的写入不回滚。"""
    edit = validate_edit(edit)
    previous = utils_config.get_script(edit.script_name)
    if previous is None:
        raise InvalidScriptEdit("脚本已不存在，请刷新列表")
    assert "script_path" in previous and "script_path" in edit.config_patch
    previous_path = previous["script_path"]

    current = utils_config.update_script(
        edit.script_name, edit.display_name, edit.config_patch
    )
    if current != edit.script_name:
        utils_weekly.rename_weekly(edit.script_name, current)
    utils_weekly.save_weekly(current, edit.weekly_timeouts)
    if previous_path != edit.config_patch["script_path"] or current != edit.script_name:
        init_config(current)
    switch = task_switch_of(current)
    if switch is not None:
        switch.write(edit.switches)
    return current
