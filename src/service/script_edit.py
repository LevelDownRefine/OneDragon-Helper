"""单脚本表单的输入校验；保存沿用 AppService 原有编辑流程。"""

import os

from src.utils.utils_config import get_script
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


class InvalidScriptEdit(ValueError):
    """尚未写入的可恢复表单错误。"""


def validate_edit(script_name, display_name, config_patch, weekly_timeouts, switches):
    """验证完整表单，返回清理空白后的名称和配置字段。"""
    if not isinstance(display_name, str) or not display_name.strip():
        raise InvalidScriptEdit("脚本名称不能为空")
    if not isinstance(config_patch, dict) or set(config_patch) != set(
        _TEXT_FIELDS + _BOOL_FIELDS
    ):
        raise InvalidScriptEdit("脚本配置字段不完整或包含未知字段")
    for key in _TEXT_FIELDS:
        assert key in config_patch
        if not isinstance(config_patch[key], str):
            raise InvalidScriptEdit(f"{key} 必须是文本")
    for key in _BOOL_FIELDS:
        assert key in config_patch
        if type(config_patch[key]) is not bool:
            raise InvalidScriptEdit(f"{key} 必须是开关")
    patch = {
        key: value.strip() if isinstance(value, str) else value
        for key, value in config_patch.items()
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
    if (
        not isinstance(weekly_timeouts, list)
        or len(weekly_timeouts) != 7
        or any(
            value is not None and (type(value) is not int or not 0 <= value <= 86400)
            for value in weekly_timeouts
        )
    ):
        raise InvalidScriptEdit("每周超时须为七项 0～86400 秒或空值")
    if not isinstance(switches, dict) or any(
        not isinstance(name, str) or not name or type(value) is not bool
        for name, value in switches.items()
    ):
        raise InvalidScriptEdit("任务开关格式无效")
    display_name = display_name.strip()
    identity = get_script_name({**patch, "display_name": display_name})
    if identity != script_name and get_script(identity) is not None:
        raise InvalidScriptEdit("已存在同标识脚本，请修改路径或名称")
    return display_name, patch
