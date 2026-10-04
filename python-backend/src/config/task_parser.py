"""日常、周常、任务开关及附带选项的声明解析；不读写文件或依赖机制类。"""

import ast
import re
from collections.abc import Callable
from copy import deepcopy
from pathlib import PureWindowsPath

from src.utils.utils_dict import get_field


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
    assert isinstance(value, (str, int, bool)), f"{context} 必须为字符串、整数或布尔"
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
        _relative_path(source["path"], f"{context}/source/path")
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
            "template",
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
        if "template" in definition:
            _validate_name(definition["template"], f"{script_name}/{name}/template")
        if "options" in definition:
            _validate_group(definition["options"], f"{script_name}/{name}")


def parse_task_map(data: dict, require_class: bool = False) -> dict[str, list[dict]]:
    """校验日常或周常声明，返回独立副本。

    Args:
        data: 文件解码后的声明。
        require_class: 是否要求每条任务声明机制类及主配置路径。

    Returns:
        按脚本分组的任务声明。
    """
    assert isinstance(data, dict), "任务声明必须是字典"
    for script_name, definitions in data.items():
        _validate_name(script_name, "脚本标识")
        _validate_definitions(script_name, definitions)
        if require_class:
            for definition in definitions:
                context = f"{script_name}/{definition['display_name']}"
                assert {"class", "config"} <= definition.keys(), (
                    f"{context} 未声明 class/config"
                )
                _validate_name(definition["class"], f"{context}/class")
                _relative_path(definition["config"])
    return deepcopy(data)


def materialize_options(
    node: dict,
    read_source: Callable[[dict], list[str]],
) -> dict:
    """物化一个声明节点的选项组。

    Args:
        node: 声明节点（日常或选项）。
        read_source: 由调用方提供的来源候选名读取函数。

    Returns:
        物化后的选项组（新 dict，不改动声明）：``key`` 等声明字段原样保留，
        ``values`` 恒存在，每个选项均带 ``physical_name``。

    Raises:
        AssertionError: 节点未声明选项或候选项不符合声明规则。
    """
    assert "options" in node, f"{node['display_name']} 未声明选项"
    group = node["options"]
    if "source" in group:
        names = read_source(group["source"])
        values = [{"display_name": name} for name in names] if names else []
    else:
        values = group["values"]
    options = []
    for option in values:
        materialized = {**option, "physical_name": get_physical_name(option)}
        if "options" in option:
            materialized["options"] = materialize_options(option, read_source)
        options.append(materialized)
    return deepcopy({**group, "values": options})


#: 声明段共有：可选字段 names（白名单 / 展示名 / 多选候选项）
_OPTIONAL_FIELDS = frozenset({"names"})

#: 声明段形态 → (必需字段, 可选字段, 形态标识)；各形态字段集互不重叠
_FORMS: tuple[tuple[frozenset, frozenset, str], ...] = (
    (frozenset({"config", "task_pattern"}), _OPTIONAL_FIELDS, "pattern"),
    (
        frozenset({"config", "tasks_key", "enabled_key"}),
        _OPTIONAL_FIELDS,
        "key_pair",
    ),
    (
        frozenset({"config", "list_key", "id_key", "enabled_key"}),
        _OPTIONAL_FIELDS,
        "app_list",
    ),
    (
        frozenset({"config", "list_key", "names"}),
        frozenset(),
        "multi_select",
    ),
)


def switch_form(declaration: dict) -> str | None:
    """匹配声明段所属形态：必需字段齐且无多余字段；不属于任何形态时返回 None。"""
    fields = frozenset(declaration)
    for required, optional, cls in _FORMS:
        if required <= fields and fields <= (required | optional):
            return cls
    return None


def _single_group_pattern(text: str) -> bool:
    """正则可编译且恰好一个捕获组（行名取自它）。"""
    try:
        pattern = re.compile(text)
    except re.error:
        return False
    return pattern.groups == 1


def _validate_segment(script_name: str, segment: dict) -> None:
    """单段声明须匹配某一形态，字段全为非空字符串，config 为脚本内相对路径。

    Raises:
        AssertionError: 字段缺失、多写、形态混用、取值非法，或正则不可用（编译失败／
            捕获组数不为 1，行名无从取）。
    """
    assert switch_form(segment) is not None, (
        f"{script_name} 的任务开关声明字段必须为 "
        + " 或 ".join(
            str(sorted(required)) + (f" + 可选 {sorted(optional)}" if optional else "")
            for required, optional, _ in _FORMS
        )
    )
    for field in sorted(segment):
        if field in _OPTIONAL_FIELDS:
            continue
        value = segment[field]
        assert isinstance(value, str) and value.strip(), (
            f"{script_name}/task_switch/{field} 必须为非空字符串"
        )
    _relative_path(segment["config"], f"{script_name}/task_switch/config")
    if "task_pattern" in segment:
        assert _single_group_pattern(segment["task_pattern"]), (
            f"{script_name}/task_switch/task_pattern 必须是可编译且恰好一个捕获组的正则"
        )
    if "names" in segment:
        _validate_names(script_name, segment["names"])


def _validate_names(script_name: str, names) -> None:
    """``names`` 为 ``{标识: 展示名}`` 或 ``[标识]``（后者行名即标识），键与值都须非空。

    Raises:
        AssertionError: 既非字典也非列表，或其中某项不是非空字符串。
    """
    assert isinstance(names, (dict, list)), (
        f"{script_name}/task_switch/names 必须为字典（标识: 展示名）或列表（标识）"
    )
    pairs = (
        list(names.items())
        if isinstance(names, dict)
        else [(ident, ident) for ident in names]
    )
    for ident, name in pairs:
        assert isinstance(ident, str) and ident.strip(), (
            f"{script_name}/task_switch/names 的标识必须为非空字符串"
        )
        assert isinstance(name, str) and name.strip(), (
            f"{script_name}/task_switch/names 的展示名必须为非空字符串"
        )


def _with_dict_names(segment: dict) -> dict:
    """``names`` 写成 ``[标识]`` 时补成 ``{标识: 标识}``（行名即标识）。"""
    names = segment.get("names", {})  # names 可省略。
    if isinstance(names, list):
        return {**segment, "names": {ident: ident for ident in names}}
    return segment


def _normalized_segments(script_name: str, node) -> list[dict]:
    """把声明节点校验并归一化成段列表。

    单段直接写在节点上；多段写在 ``segments`` 下，节点级的 ``config`` 作为各段默认（同一
    脚本的开关常散在同一个文件的不同键上，路径因此只写一次）。``names`` 统一成
    ``{标识: 展示名}``。

    Returns:
        段列表，每段一种形态。

    Raises:
        AssertionError: 节点非字典、``segments`` 非非空列表、节点级多写字段，或某段非法。
    """
    assert isinstance(node, dict), f"{script_name} 的任务开关声明必须为字典"
    node = {key: value for key, value in node.items() if key != "options"}
    if "segments" not in node:
        _validate_segment(script_name, node)
        return [_with_dict_names(node)]

    defaults = {key: value for key, value in node.items() if key != "segments"}
    assert set(defaults) <= {"config"}, (
        f"{script_name}/task_switch 多段声明的节点级只能给 config（作为各段默认）"
    )
    segments = node["segments"]
    assert isinstance(segments, list) and segments, (
        f"{script_name}/task_switch/segments 必须为非空列表"
    )
    result: list[dict] = []
    for segment in segments:
        assert isinstance(segment, dict), (
            f"{script_name}/task_switch/segments 的每一项必须为字典"
        )
        merged = {**defaults, **segment}
        _validate_segment(script_name, merged)
        result.append(_with_dict_names(merged))
    return result


def parse_task_switch_map(data: dict) -> dict[str, list[dict]]:
    """校验任务开关声明并归一化段列表。

    Args:
        data: 文件解码后的完整声明。

    Returns:
        按脚本分组的独立段列表，names 统一为字典。
    """
    assert isinstance(data, dict), "任务开关声明必须是字典"
    for script_name in data:
        _validate_name(script_name, "脚本标识")
    return deepcopy(
        {
            script_name: _normalized_segments(script_name, node)
            for script_name, node in data.items()
        }
    )


def _relative_path(value: str, context: str = "config/source/path") -> None:
    _validate_name(value, context)
    path = PureWindowsPath(value)
    assert not path.anchor and ".." not in path.parts, f"{context} 必须为脚本内相对路径"


def parse_task_options(data: dict) -> dict:
    """校验附带选项声明，返回按脚本分组的独立副本。

    Args:
        data: task_switch_list.yml 解码后的完整声明。

    Returns:
        含附带选项的脚本及其选项组。
    """
    assert isinstance(data, dict), "任务选项声明必须为 dict"
    for name, node in data.items():
        _validate_name(name, "脚本标识")
        assert isinstance(node, dict), f"{name} 的任务声明必须为字典"
    data = {name: node["options"] for name, node in data.items() if "options" in node}
    for groups in data.values():
        assert isinstance(groups, list)
        identifiers = set()
        for group in groups:
            assert isinstance(group, dict), "任务选项组必须为字典"
            assert {"display_name", "config", "fields", "tasks"} <= group.keys()
            _relative_path(group["config"])
            assert isinstance(group["display_name"], str) and group["display_name"]
            assert isinstance(group["fields"], list) and group["fields"]
            assert isinstance(group["tasks"], list)
            assert all(isinstance(name, str) and name for name in group["tasks"])
            for field in group["fields"]:
                assert isinstance(field, dict), "任务选项字段必须为字典"
                assert {"id", "display_name", "keys", "type"} <= field.keys()
                assert isinstance(field["id"], str) and field["id"]
                assert field["id"] not in identifiers
                identifiers.add(field["id"])
                assert isinstance(field["display_name"], str) and field["display_name"]
                assert field["type"] in ("bool", "choice", "multi")
                assert isinstance(field["keys"], list) and field["keys"]
                assert all(isinstance(key, str) and key for key in field["keys"])
                if "min_items" in field:
                    assert field["type"] == "multi"
                    assert type(field["min_items"]) is int and field["min_items"] >= 0
                if field["type"] != "bool":
                    assert ("values" in field) != ("source" in field)
                    if "source" in field:
                        assert isinstance(field["source"], dict)
                        assert "path" in field["source"]
                        _relative_path(field["source"]["path"])
                    else:
                        parse_choices(field["values"])
    return deepcopy(data)


def parse_choices(names: list) -> list[dict]:
    """归一化附带选项的字符串或显示名/物理名节点。

    Args:
        names: 静态声明或资源解析出的候选项。

    Returns:
        物理名为字符串且互不重复的候选项列表。
    """
    assert isinstance(names, list)
    choices = []
    for name in names:
        if isinstance(name, str):
            choices.append({"display_name": name, "physical_name": name})
        else:
            assert (
                isinstance(name, dict)
                and {"display_name", "physical_name"} <= name.keys()
            )
            choices.append(dict(name))
    validate_options(choices, "任务附带选项")
    assert all(isinstance(item["physical_name"], str) for item in choices)
    assert len({item["physical_name"] for item in choices}) == len(choices)
    return choices


def parse_resource_choices(names: list[str], source: dict) -> list[dict]:
    """校验外部候选名，添加固定候选项并归一化。

    Args:
        names: 已从外部资源提取的候选名。
        source: 来源声明，可包含 prepend。

    Returns:
        归一化后的候选项列表。

    Raises:
        ValueError: 外部候选名不再是非空字符串。
    """
    if not all(isinstance(name, str) and name for name in names):
        raise ValueError("候选资源名称必须是非空字符串")
    if "prepend" in source:
        names = [*source["prepend"], *names]
    return parse_choices(names)


def parse_source_names(data, source: dict, script_name: str) -> list[str]:
    """从资源数据的键路径取选项名；列表取值，字典取键。

    Args:
        data: 已读取的资源数据，缺失时为 None。
        source: path/key 来源声明。
        script_name: 错误上下文中的脚本标识。

    Returns:
        候选名列表，资源为空时返回空列表。
    """
    assert source.keys() <= {"path", "key"}, "通用资源来源只支持 path / key"
    path = get_field(source, "path", script_name, str)
    keys = source["key"] if "key" in source else ()  # noqa: SIM401  # 键路径可省略
    assert isinstance(keys, (list, tuple)), "source.key 必须为键路径列表"
    if data is None or data == {} or data == []:
        return []
    for key in keys:
        assert isinstance(key, str) and key, "source.key 的每层键必须为非空字符串"
        assert isinstance(data, dict), (
            f"[{script_name}] {path} 的 {key!r} 父节点必须为字典"
        )
        data = get_field(data, key, script_name)
    assert isinstance(data, (list, dict)), (
        f"[{script_name}] {path} 的选项必须为列表或字典"
    )
    names = list(data)
    assert all(isinstance(name, str) and name for name in names), (
        f"[{script_name}] {path} 的选项名必须为非空字符串"
    )
    return names


def parse_enum_names(content: str, source: dict) -> list[str]:
    """读取外部枚举源码中的字符串常量，不执行源码。

    Args:
        content: 外部 Python 源码。
        source: enum/argument 来源声明。

    Returns:
        枚举候选名列表。

    Raises:
        ValueError: 枚举不存在或构造参数已变化。
    """
    tree = ast.parse(content)
    names = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == source["enum"]:
            for item in node.body:
                if isinstance(item, ast.Assign) and isinstance(item.value, ast.Call):
                    argument = source["argument"]
                    if len(item.value.args) <= argument:
                        raise ValueError("枚举构造参数已变化")
                    value = item.value.args[argument]
                    if not isinstance(value, ast.Constant) or not isinstance(
                        value.value, str
                    ):
                        raise ValueError("枚举候选名不再是字符串常量")
                    names.append(value.value)
    if not names:
        raise ValueError("未找到枚举候选项")
    return names


def parse_record_names(records, source: dict) -> list[str]:
    """从资源字典的各记录提取名称字段。

    Args:
        records: JSON 解码后的资源数据。
        source: 含 field 的来源声明。

    Returns:
        记录中的候选名列表。

    Raises:
        ValueError: 上游资源结构或字段已变化。
    """
    if not isinstance(records, dict):
        raise ValueError("候选资源不再是字典")
    assert "field" in source
    names = []
    for record in records.values():
        if not isinstance(record, dict) or source["field"] not in record:
            raise ValueError("候选资源字段已变化")
        names.append(record[source["field"]])
    return names


def parse_map_point_names(data, source: dict, context: str) -> list[str]:
    """按分类从原神地图资源提取点位名称。

    Args:
        data: 已解码的地图资源。
        source: path/category 来源声明。
        context: 错误上下文中的日常名。

    Returns:
        指定分类的点位名称，资源缺失或分类无点位时为空列表。
    """
    assert source.keys() <= {"path", "category"}, "原神资源来源只支持 path / category"
    category = get_field(source, "category", context, str)
    if not data:
        return []
    assert isinstance(data, dict), "原神地图资源必须为 dict"
    names = []
    # 地图和点位可没有秘境分类或名称，此时不提供选项。
    scenes = data["data"] if "data" in data else []  # noqa: SIM401
    for scene in scenes:
        if not isinstance(scene, dict) or "points" not in scene:
            continue
        for point in scene["points"]:
            if (
                isinstance(point, dict)
                and "type" in point
                and point["type"] == category
                and "name" in point
                and point["name"]
            ):
                names.append(point["name"])
    return names
