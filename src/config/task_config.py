"""读取任务声明，校验递归选项组；任务类型仅属于顶层。"""

from copy import deepcopy
from pathlib import PureWindowsPath

from src.utils import get_task_list_yml_path_under_root
from src.utils.utils_yaml import load_yaml


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


def has_selection_binding(node: dict) -> bool:
    """递归判断选择绑定，不包含顶层任务操作的 key。"""
    return "options" in node and (
        "key" in node["options"]
        or any(has_selection_binding(option) for option in get_options(node))
    )


def validate_selection_depth(node: dict, remaining: int = 2) -> None:
    """声明允许递归；当前选择接口和 GUI 只支持两级。"""
    if "options" not in node:
        return
    assert remaining > 0, "当前选择接口最多支持两层选项"
    for option in get_options(node):
        validate_selection_depth(option, remaining - 1)


def get_selection_key(node: dict) -> str:
    """取得选择字段；纯展示分组共用实际选项组的 key。"""
    assert "options" in node, "所选项必须声明 options.key"
    if "key" in node["options"]:
        return node["options"]["key"]
    options = get_options(node)
    assert options and all(
        "options" in option and "key" in option["options"] for option in options
    ), "所选项必须声明 options.key"
    keys = {option["options"]["key"] for option in options}
    assert len(keys) == 1, "展示分类写入不同字段，无法唯一反读"
    return keys.pop()


def validate_selection_bindings(definition: dict) -> None:
    """普通选择的字段必须明确，展示分组的原生值必须唯一。"""
    validate_selection_depth(definition)
    get_selection_key(definition)
    options = get_options(definition)
    for option in options:
        if "options" in option:
            assert "key" in option["options"], "二级选择必须声明 options.key"
    if "key" not in definition["options"]:
        values = [
            get_physical_name(child)
            for option in options
            for child in get_options(option)
        ]
        assert len(values) == len(set(values)), "展示分类下的原生值重复，无法唯一反读"


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


def _validate_definitions(
    script_name: str, definitions: list[dict], task_type: str | None = None
) -> None:
    assert isinstance(definitions, list), f"{script_name} 的任务必须是列表"
    names, physical_names = set(), set()
    for definition in definitions:
        assert isinstance(definition, dict) and "display_name" in definition, (
            "任务必须声明 display_name"
        )
        assert definition.keys() <= {
            "display_name",
            "physical_name",
            "type",
            "key",
            "allow_disable",
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
        if task_type is None:
            assert "type" in definition, "任务必须声明 type"
        if "type" in definition:
            assert definition["type"] in ("daily", "weekly"), (
                "type 必须为 daily 或 weekly"
            )
            assert task_type is None or definition["type"] == task_type, (
                f"{name} 的 type 应为 {task_type}"
            )
        if "key" in definition:
            _validate_name(definition["key"], f"{name}/key")
        if "allow_disable" in definition:
            assert isinstance(definition["allow_disable"], bool), (
                "allow_disable 必须为 bool"
            )
        if "options" in definition:
            _validate_group(definition["options"], f"{script_name}/{name}")


def validate_daily_definitions(script_name: str, definitions: list[dict]) -> None:
    """校验日常声明。"""
    _validate_definitions(script_name, definitions, "daily")


def validate_weekly_definitions(script_name: str, definitions: list[dict]) -> None:
    """校验周常声明，选择规则与日常一致。"""
    _validate_definitions(script_name, definitions, "weekly")


def load_task_map() -> dict[str, list[dict]]:
    """读取完整声明，校验跨类型任务名和物理名的唯一性。"""
    data = load_yaml(get_task_list_yml_path_under_root())
    assert isinstance(data, dict), "任务声明必须是字典"
    for script_name, definitions in data.items():
        _validate_name(script_name, "脚本标识")
        _validate_definitions(script_name, definitions)
    return data


def load_daily_map() -> dict[str, list[dict]]:
    """取得日常声明。"""
    return {
        script: [task for task in tasks if task["type"] == "daily"]
        for script, tasks in load_task_map().items()
    }


def load_weekly_map() -> dict[str, list[dict]]:
    """取得周常声明，周几起仍由 weekly.yml 维护。"""
    return {
        script: [task for task in tasks if task["type"] == "weekly"]
        for script, tasks in load_task_map().items()
        if any(task["type"] == "weekly" for task in tasks)
    }
