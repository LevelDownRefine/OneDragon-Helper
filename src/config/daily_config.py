"""把日常、周常声明转换成 GUI 菜单数据；本地资源缺失时没有可选副本。"""

from src.config.daily import Daily
from src.config.set_config import get_task_lists
from src.config.task_config import (
    get_options,
    get_physical_name,
    load_daily_map,
    load_weekly_map,
)


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


def get_daily_map() -> dict:
    """把日常声明转换为按日常分组的菜单（GUI 最终形状）。

    每个脚本一组日常，每个日常一份一级副本列表（含二级序列，二级继续传物理值）：
    {script: {"dailies": [{"name": 日常展示名,
                            "options": [{"name": 副本名,
                                         "sequences": [{"label": 展示名,
                                                        "value": 物理值}]}]},
                           ...]}}。

    菜单只需要声明，故用声明 + 基类 ``Daily`` 解析，**不经过 ``_daily_types``**：
    声明里新增一个日常时菜单照常显示，而落点（要按该日常的读写机制来）由各脚本的
    ``_daily_types`` 决定、不齐即报错。
    """
    data = {}
    for script_name, declarations in load_daily_map().items():
        dailies = []
        for declaration in declarations:
            daily = Daily(script_name, declaration)
            options = []
            for option in daily.options:
                item = {"name": option["display_name"], "sequences": []}
                if "options" in option:
                    children = _resolve_options(script_name, option)
                    assert all("options" not in child for child in children), (
                        "当前日常菜单最多支持两级选择"
                    )
                    item["sequences"] = [
                        {
                            "label": child["display_name"],
                            "value": get_physical_name(child),
                        }
                        for child in children
                    ]
                options.append(item)
            dailies.append({"name": daily.name, "options": options})
        data[script_name] = {"dailies": dailies}
    return data
