"""读取日常、周常声明并校验递归选项；不负责调度或写入子脚本。"""

from copy import deepcopy
from functools import lru_cache
from pathlib import Path, PureWindowsPath

from src.utils import (
    get_daily_task_list_yml_path_under_root,
    get_weekly_task_list_yml_path_under_root,
)
from src.utils.utils_yaml import load_yaml_str


def get_physical_name(node: dict) -> str | int:
    """任务和选项统一取物理名，省略时使用展示名。"""
    assert "display_name" in node, "必须声明 display_name"
    # 物理名与展示名相同时可省略。
    return node.get("physical_name", node["display_name"])


def get_options(node: dict) -> list[dict]:
    """取得直属选项副本；无选项或来源尚未展开时为空。"""
    if "options" not in node:
        return []
    group = node["options"]
    assert isinstance(group, dict), "options 必须为选项组"
    # 来源尚未展开时没有 values。
    return deepcopy(group.get("values", []))


def get_value_map(node: dict) -> dict[str, str | int]:
    """把一组选项声明转换成展示名到物理名的映射。"""
    return {
        option["display_name"]: get_physical_name(option)
        for option in get_options(node)
    }


def _validate_name(value, context: str) -> None:
    assert isinstance(value, str) and value.strip(), f"{context} 必须为非空字符串"


def _validate_physical_name(value, context: str) -> None:
    assert isinstance(value, (str, int)) and not isinstance(value, bool), (
        f"{context} 必须为字符串或整数"
    )
    if isinstance(value, str):
        _validate_name(value, context)


def _validate_group(group: dict, context: str) -> None:
    assert isinstance(group, dict), f"{context} 的 options 必须为选项组"
    assert group.keys() <= {"key", "values", "source"}, f"{context} 含未知选项组字段"
    if "key" in group:
        _validate_name(group["key"], f"{context}/options/key")
    assert ("values" in group) != ("source" in group), (
        f"{context} 的 values 与 source 必须二选一，不能同时声明"
    )
    if "source" in group:
        source = group["source"]
        assert isinstance(source, dict) and "path" in source, (
            f"{context} 的 source 必须声明 path"
        )
        assert source.keys() <= {"path", "category"}, f"{context} 含未知来源字段"
        _validate_name(source["path"], f"{context}/source/path")
        path = PureWindowsPath(source["path"])
        assert not path.anchor and ".." not in path.parts, (
            f"{context} 的来源必须为脚本内相对路径"
        )
        if "category" in source:
            _validate_physical_name(source["category"], f"{context}/source/category")
    else:
        validate_options(group["values"], context)


def validate_options(options: list[dict], context: str) -> None:
    """每层选项节点使用相同规则，子选项组递归校验。"""
    assert isinstance(options, list), f"{context} 的 values 必须为选项列表"
    names, values = set(), set()
    for option in options:
        assert isinstance(option, dict) and "display_name" in option, (
            "选项必须声明 display_name"
        )
        assert option.keys() <= {"display_name", "physical_name", "options"}, (
            f"{context} 含未知选项声明"
        )
        name = option["display_name"]
        _validate_name(name, "选项名")
        assert name not in names, f"{context} 的选项名重复: {name}"
        names.add(name)
        value = get_physical_name(option)
        _validate_physical_name(value, f"{context}/{name}/physical_name")
        assert value not in values, f"{context} 的原生值重复，无法唯一反读"
        values.add(value)
        if "options" in option:
            _validate_group(option["options"], f"{context}/{name}")


def _validate_definitions(script_name: str, definitions: list[dict]) -> None:
    assert isinstance(definitions, list), f"{script_name} 的任务必须是列表"
    names, physical_names = set(), set()
    for definition in definitions:
        assert isinstance(definition, dict) and "display_name" in definition, (
            "任务必须声明 display_name"
        )
        assert definition.keys() <= {
            "display_name",
            "physical_name",
            "key",
            "options",
        }, f"{script_name} 含未知任务声明"
        name = definition["display_name"]
        _validate_name(name, "任务名")
        assert name not in names, f"{script_name} 的任务名重复: {name}"
        names.add(name)
        physical_name = get_physical_name(definition)
        _validate_name(physical_name, f"{name}/physical_name")
        assert physical_name not in physical_names, (
            f"{script_name} 的任务物理名重复: {physical_name}"
        )
        physical_names.add(physical_name)
        if "key" in definition:
            _validate_name(definition["key"], f"{name}/key")
        if "options" in definition:
            _validate_group(definition["options"], f"{script_name}/{name}")


def load_task_map(path: str) -> dict[str, list[dict]]:
    """同一份内容只解析一次；调用方取得独立副本。"""
    file = Path(path)
    assert file.is_file(), f"任务声明缺失: {path}"
    return deepcopy(_load_task_map(file.read_text(encoding="utf-8")))


@lru_cache(maxsize=2)
def _load_task_map(content: str) -> dict[str, list[dict]]:
    """以内容为缓存键，避免同大小、同时间戳的文件替换读到旧声明。"""
    data = load_yaml_str(content)
    assert isinstance(data, dict), "任务声明必须是字典"
    for script_name, definitions in data.items():
        _validate_name(script_name, "脚本标识")
        _validate_definitions(script_name, definitions)
    return data


def load_daily_map() -> dict[str, list[dict]]:
    """取得日常声明。"""
    return load_task_map(get_daily_task_list_yml_path_under_root())


def load_weekly_map() -> dict[str, list[dict]]:
    """取得周常声明，周几起仍由 weekly.yml 维护。"""
    return load_task_map(get_weekly_task_list_yml_path_under_root())


def get_daily_config(script_name: str) -> dict:
    """取得脚本的单个日常声明；特殊玩法由对应子类处理。"""
    data = load_daily_map()
    assert script_name in data, f"缺少日常声明: {script_name}"
    tasks = data[script_name]
    assert len(tasks) == 1, f"{script_name} 的多个日常需由子类适配"
    return tasks[0]


def get_weekly_config(script_name: str, weekly_name: str) -> dict:
    """按展示名取得指定周常声明。"""
    data = load_weekly_map()
    assert script_name in data, f"缺少周常声明: {script_name}"
    matches = [
        task for task in data[script_name] if task["display_name"] == weekly_name
    ]
    assert len(matches) == 1, f"缺少周常声明: {script_name}/{weekly_name}"
    return matches[0]
