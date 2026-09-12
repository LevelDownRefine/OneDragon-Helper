from typing import Any

from src.config.set_config import get_dungeon_lists, get_dungeon_options
from src.config.task_config import (
    get_options,
    get_physical_name,
    load_daily_map,
    load_weekly_map,
)

DungeonOptions = list[str]
SequenceOptionsMap = dict[str, list[tuple[str, Any]]]


def parse_dungeon_config(
    dungeon_cfg: Any,
) -> tuple[DungeonOptions, SequenceOptionsMap, bool]:
    """
    解析单个脚本的副本配置。

    菜单数据格式（由 get_dungeon_map 转换）：
    dungeons:
      - name: "副本名"
      - name: "有二级选项的副本"
        sequences:
          - display: "显示名称"
            value: 实际值

    Args:
        dungeon_cfg: get_dungeon_map 返回的单脚本菜单数据。

    Returns:
        (options, seq_map, show_seq)
        - options: 一级副本名称列表
        - seq_map: 副本名 → [(display_name, actual_value), ...]
        - show_seq: 是否有二级选项
    """
    options: DungeonOptions = []
    seq_map: SequenceOptionsMap = {}
    show_seq = False

    if isinstance(dungeon_cfg, dict) and "dungeons" in dungeon_cfg:
        for i, dungeon in enumerate(dungeon_cfg["dungeons"]):
            assert isinstance(dungeon, dict), (
                f"第{i}个副本配置必须是字典，实际是 {type(dungeon)}"
            )
            assert "name" in dungeon, f"第{i}个副本配置缺少 'name' 字段"
            assert isinstance(dungeon["name"], str), (
                f"第{i}个副本的 'name' 必须是字符串"
            )

            name = dungeon["name"]
            options.append(name)

            sequences = dungeon.get("sequences")  # optional: 副本可能没有二级选项
            if sequences:
                assert isinstance(sequences, list), (
                    f"副本 '{name}' 的 sequences 必须是列表"
                )
                seq_map[name] = []
                for j, seq in enumerate(sequences):
                    assert isinstance(seq, dict), f"副本 '{name}' 第{j}个序列必须是字典"
                    assert "display" in seq, (
                        f"副本 '{name}' 第{j}个序列缺少 'display' 字段"
                    )
                    assert "value" in seq, f"副本 '{name}' 第{j}个序列缺少 'value' 字段"
                    assert isinstance(seq["display"], str), (
                        f"副本 '{name}' 第{j}个序列的 'display' 必须是字符串"
                    )
                    seq_map[name].append((seq["display"], seq["value"]))
                show_seq = True

    return options, seq_map, show_seq


def get_display_name(
    seq_map: SequenceOptionsMap, dungeon_name: str, actual_value: Any
) -> str:
    """
    根据实际值获取对应的显示名称。

    Args:
        seq_map: 副本名 → [(display_name, actual_value), ...]
        dungeon_name: 副本名称
        actual_value: 实际值

    Returns:
        显示名称，如果找不到则返回实际值的字符串表示
    """
    assert dungeon_name in seq_map, (
        f"[dungeon_config] 副本 '{dungeon_name}' 不在序列映射中"
    )
    seq_options = seq_map[dungeon_name]
    for display_name, val in seq_options:
        if val == actual_value:
            return display_name
    return str(actual_value)


def _resolve_options(script_name: str, node: dict) -> list[dict]:
    """展开一组选项的本地资源，保留选项的展示名和物理值。"""
    if "options" not in node:
        return []
    group = node["options"]
    if "source" not in group:
        return get_options(node)
    source = group["source"]
    # 资源没有另行指定分类时，以节点物理名定位。
    category = source.get("category", get_physical_name(node))
    names = get_dungeon_lists(script_name, category, source["path"])
    return [{"display_name": name} for name in names] if names else []


def get_weekly_map(script_name: str) -> list:
    """把周常声明转换为原有菜单数据；本地资源缺失时没有可选副本。"""
    defs_map = load_weekly_map()
    if script_name not in defs_map:
        return []
    defs = []
    for task in defs_map[script_name]:
        item = {"name": task["display_name"]}
        if "options" in task:
            options = _resolve_options(script_name, task)
            assert all("options" not in option for option in options), (
                "当前周常菜单只支持一级选择"
            )
            item["dungeons"] = [option["display_name"] for option in options]
        defs.append(item)
    return defs


def get_dungeon_map() -> dict:
    """把日常声明转换为原有单副本菜单，二级选择继续传物理值。"""
    data = {}
    for script_name in load_daily_map():
        dungeons = []
        for option in get_dungeon_options(script_name):
            item = {"name": option["display_name"]}
            if "options" in option:
                children = _resolve_options(script_name, option)
                assert all("options" not in child for child in children), (
                    "当前日常菜单最多支持两级选择"
                )
                item["sequences"] = [
                    {
                        "display": child["display_name"],
                        "value": get_physical_name(child),
                    }
                    for child in children
                ]
            dungeons.append(item)
        data[script_name] = {"dungeons": dungeons}
    return data
