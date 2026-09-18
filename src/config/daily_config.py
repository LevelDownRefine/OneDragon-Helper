"""把日常、周常声明物化成 GUI 菜单数据；本地资源缺失时没有可选副本。

物化 = 词汇与声明一致（``display_name`` / ``physical_name`` / 递归 ``options.values``），
仅做两件事：把 ``source`` 引用替换成本地资源展开的具体副本；给省略 ``physical_name``
的选项补齐缺省值（回落展示名）。不做任何改名与拍平。
"""

from src.config.set_config import get_task_lists
from src.config.task_config import (
    get_physical_name,
    load_daily_map,
    load_weekly_map,
)
from src.config.task_source import read_task_source


def _materialize_options(
    script_name: str,
    node: dict,
    depth: int = 0,
    *,
    daily: str | None = None,
) -> dict:
    """物化一个声明节点的选项组。

    Args:
        script_name: 脚本标识名（资源定位用）。
        node: 声明节点（日常或选项）。
        depth: 选项组嵌套深度（日常自身为 0，其子选项组为 1）。
        daily: 所属日常展示名；周常省略并使用通用资源读取。

    Returns:
        物化后的选项组（新 dict，不改动声明）：``key`` 等声明字段原样保留，
        ``values`` 恒存在，每个选项均带 ``physical_name``。

    Raises:
        AssertionError: 节点未声明选项，或子选项组还带更深的选项组
            （GUI 目前最多渲染两级，不许静默丢层）。
    """
    assert "options" in node, f"{node['display_name']} 未声明选项"
    group = node["options"]
    if "source" in group:
        names = (
            get_task_lists(script_name, daily, group["source"])
            if daily is not None
            else read_task_source(script_name, group["source"])
        )
        values = [{"display_name": name} for name in names] if names else []
    else:
        values = group["values"]
    options = []
    for option in values:
        materialized = {**option, "physical_name": get_physical_name(option)}
        if "options" in option:
            assert depth < 1, "当前日常菜单最多支持两级选择"
            materialized["options"] = _materialize_options(
                script_name, option, depth + 1, daily=daily
            )
        options.append(materialized)
    return {**group, "values": options}


def get_weekly_map(script_name: str) -> list:
    """把周常声明物化成菜单（词汇与声明一致）；本地资源缺失时没有可选副本。

    每项即周常声明节点（无选项的开关周常原样），有选项的 ``options.values`` 已物化。
    当前周常菜单只支持一级选择：物化后仍断言各选项无子选项组。
    """
    defs_map = load_weekly_map()
    if script_name not in defs_map:
        return []
    defs = []
    for task in defs_map[script_name]:
        if "options" in task:
            task = {**task, "options": _materialize_options(script_name, task)}
            values = task["options"]["values"]
            assert all("options" not in option for option in values), (
                "当前周常菜单只支持一级选择"
            )
        defs.append(task)
    return defs


def _materialize_daily(script_name: str, declaration: dict) -> dict:
    """物化一条日常声明，选项组按声明形态呈现：

    - 两层日常（各一级项自带子选项组）：一级项即各 value；
    - 单层带 ``key``（选择结果直接写字段）：整组即唯一一级项（展示名用日常名），
      其 values 作二级——与写路径一致（一级项名 = 日常名、值走二级）；
    - 单层无 ``key``（no-op）：values 即一级项。
    """
    options = _materialize_options(
        script_name, declaration, daily=declaration["display_name"]
    )
    # layered 判断走物化结果（values 恒存在），不读裸声明——日常级 source 组没有 values。
    layered = any("options" in option for option in options["values"])
    if "key" in declaration["options"] and not layered:
        options = {
            "values": [
                {
                    "display_name": declaration["display_name"],
                    "physical_name": get_physical_name(declaration),
                    "options": options,
                }
            ]
        }
    # class/config/routine 与 enable_* 是代码耦合字段（机制类、文件路径、开关落点），
    # 不属于 UI 词汇，物化时剥掉。
    declaration = {
        k: v
        for k, v in declaration.items()
        if k not in ("class", "config", "routine", "enable_key", "enable_task")
    }
    return {**declaration, "options": options}


def get_daily_map() -> dict:
    """把日常声明物化成按日常分组的菜单（词汇与声明一致）。

    {script: {"dailies": [日常声明节点, ...]}}，``options.values`` 已物化。菜单
    静态选项直接来自声明，资源选项由适配器统一委托给该日常机制类读取。
    """
    return {
        script_name: {
            "dailies": [
                _materialize_daily(script_name, declaration)
                for declaration in declarations
            ]
        }
        for script_name, declarations in load_daily_map().items()
    }
