"""读取日常、周常声明并校验递归选项；不负责调度或写入子脚本。"""

import logging
from copy import deepcopy
from functools import lru_cache
from pathlib import Path, PureWindowsPath

from src.utils import (
    get_daily_task_list_yml_path_under_root,
    get_weekly_task_list_yml_path_under_root,
)
from src.utils.utils_yaml import load_yaml_str

logger = logging.getLogger(__name__)


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
        assert source.keys() <= {"path", "key", "category"}, f"{context} 含未知来源字段"
        assert not ("key" in source and "category" in source), (
            f"{context} 的 source.key 与 category 不能同时声明"
        )
        _validate_name(source["path"], f"{context}/source/path")
        path = PureWindowsPath(source["path"])
        assert not path.anchor and ".." not in path.parts, (
            f"{context} 的来源必须为脚本内相对路径"
        )
        if "category" in source:
            _validate_physical_name(source["category"], f"{context}/source/category")
        if "key" in source:
            assert isinstance(source["key"], (list, tuple)), (
                f"{context} 的 source.key 必须为键路径列表"
            )
            for key in source["key"]:
                _validate_name(key, f"{context}/source/key")
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
            "class",
            "config",
            "routine",
            "enable_key",
            "enable_task",
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
        if "enable_key" in definition:
            _validate_name(definition["enable_key"], f"{name}/enable_key")
        if "enable_task" in definition:
            _validate_name(definition["enable_task"], f"{name}/enable_task")
        if "options" in definition:
            _validate_group(definition["options"], f"{script_name}/{name}")


def load_task_map(path: str, *, require_class: bool = False) -> dict[str, list[dict]]:
    """同一份内容只解析一次；调用方取得独立副本。

    Args:
        path: 声明文件路径。
        require_class: True 时每个任务必须声明 ``class``（机制类）与 ``config``
            （读写的主文件路径）——仅日常声明路径使用。

    Returns:
        {脚本标识: 任务声明列表}。

    Raises:
        AssertionError: require_class 且某任务未声明 ``class``。
    """
    file = Path(path)
    assert file.is_file(), f"任务声明缺失: {path}"
    data = deepcopy(_load_task_map(file.read_text(encoding="utf-8")))
    if require_class:
        for definitions in data.values():
            for definition in definitions:
                assert (
                    isinstance(definition.get("class"), str) and definition["class"]
                ), f"{definitions} 的任务 {definition.get('display_name')} 未声明 class"
                assert (
                    isinstance(definition.get("config"), str) and definition["config"]
                ), (
                    f"{definitions} 的任务 {definition.get('display_name')} 未声明 config"
                )
    return data


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
    """取得日常声明（每个日常必须标注机制类 ``class``）。"""
    return load_task_map(get_daily_task_list_yml_path_under_root(), require_class=True)


def load_weekly_map() -> dict[str, list[dict]]:
    """取得周常声明，周几起仍由 weekly.yml 维护。"""
    return load_task_map(get_weekly_task_list_yml_path_under_root())


def get_daily_configs(script_name: str) -> list[dict]:
    """取得某脚本的全部日常声明（顺序与声明一致）。

    Args:
        script_name: 脚本标识名。

    Returns:
        该脚本的日常声明列表；单日常脚本长度为 1。声明文件里未出现的脚本
        （如 MaaEnd：任务编排在其自身界面、本工具不给落点）为空列表。
    """
    data = load_daily_map()
    if script_name not in data:
        logger.info(f"[get_daily_configs] {script_name} 无日常声明，按无日常处理")
        return []
    return data[script_name]


def get_weekly_config(script_name: str, weekly_name: str) -> dict:
    """按展示名取得指定周常声明。"""
    data = load_weekly_map()
    assert script_name in data, f"缺少周常声明: {script_name}"
    matches = [
        task for task in data[script_name] if task["display_name"] == weekly_name
    ]
    assert len(matches) == 1, f"缺少周常声明: {script_name}/{weekly_name}"
    return matches[0]
