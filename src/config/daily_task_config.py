from typing import Any

from src.config.set_config import get_daily_task_options, get_task_lists
from src.config.task_config import (
    get_options,
    get_physical_name,
    load_daily_map,
    load_weekly_map,
)

DailyTaskOptions = list[str]
SequenceOptionsMap = dict[str, list[tuple[str, Any]]]


def parse_daily_task_config(
    task_cfg: Any,
) -> tuple[DailyTaskOptions, SequenceOptionsMap, bool]:
    """
    解析单个日常的副本配置。

    菜单数据格式（get_daily_task_map 的 `dailies[i]`）：
    name: "日常展示名"
    tasks:
      - name: "副本名"
      - name: "有二级选项的副本"
        sequences:
          - display: "显示名称"
            value: 实际值

    Args:
        task_cfg: 某个日常的菜单数据（`{name, tasks}`）。

    Returns:
        (options, seq_map, show_seq)
        - options: 一级副本名称列表
        - seq_map: 副本名 → [(display_name, actual_value), ...]
        - show_seq: 是否有二级选项
    """
    options: DailyTaskOptions = []
    seq_map: SequenceOptionsMap = {}
    show_seq = False

    if isinstance(task_cfg, dict) and "tasks" in task_cfg:
        for i, task in enumerate(task_cfg["tasks"]):
            assert isinstance(task, dict), (
                f"第{i}个副本配置必须是字典，实际是 {type(task)}"
            )
            assert "name" in task, f"第{i}个副本配置缺少 'name' 字段"
            assert isinstance(task["name"], str), f"第{i}个副本的 'name' 必须是字符串"

            name = task["name"]
            options.append(name)

            sequences = task.get("sequences")  # optional: 副本可能没有二级选项
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
    seq_map: SequenceOptionsMap, task_name: str, actual_value: Any
) -> str:
    """
    根据实际值获取对应的显示名称。

    Args:
        seq_map: 副本名 → [(display_name, actual_value), ...]
        task_name: 副本名称
        actual_value: 实际值

    Returns:
        显示名称，如果找不到则返回实际值的字符串表示
    """
    assert task_name in seq_map, (
        f"[daily_task_config] 副本 '{task_name}' 不在序列映射中"
    )
    seq_options = seq_map[task_name]
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
    names = get_task_lists(script_name, category, source["path"])
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
            item["tasks"] = [option["display_name"] for option in options]
        defs.append(item)
    return defs


def get_daily_task_map() -> dict:
    """把日常声明转换为按日常分组的菜单，二级选择继续传物理值。

    每个脚本一组日常，每个日常一份一级副本列表（含二级序列）：
    {script: {"dailies": [{"name": 日常展示名, "tasks": [{name, sequences?}, ...]}, ...]}}。
    """
    data = {}
    for script_name in load_daily_map():
        dailies = []
        for daily in get_daily_task_options(script_name):
            tasks = []
            for option in daily["options"]:
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
                tasks.append(item)
            dailies.append({"name": daily["daily_display_name"], "tasks": tasks})
        data[script_name] = {"dailies": dailies}
    return data
