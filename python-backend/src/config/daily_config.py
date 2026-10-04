"""把日常、周常声明物化成 GUI 菜单数据；本地资源缺失时没有可选副本。

物化 = 词汇与声明一致（``display_name`` / ``physical_name`` / 递归 ``options.values``），
仅做两件事：把 ``source`` 引用替换成本地资源展开的具体副本；给省略 ``physical_name``
的选项补齐缺省值（回落展示名）。不做任何改名与拍平。
"""

from src.config.set_config import get_task_lists
from src.config.task_config import (
    load_daily_map,
    load_weekly_map,
)
from src.config.task_parser import get_physical_name, materialize_options
from src.config.task_source import read_task_source


def get_weekly_map(script_name: str) -> list:
    """把周常声明物化成菜单（词汇与声明一致）；本地资源缺失时没有可选副本。

    每项即周常声明节点（无选项的开关周常原样），有选项的 ``options.values`` 已物化。
    当前周常菜单只支持一级选择：物化后仍断言各选项无子选项组；``class`` / ``config``
    是代码耦合字段，不属于 UI 词汇，物化时剥掉。
    """
    defs_map = load_weekly_map()
    if script_name not in defs_map:
        return []
    defs = []
    for task in defs_map[script_name]:
        if "options" in task:
            task = {
                **task,
                "options": materialize_options(
                    task, lambda source: read_task_source(script_name, source)
                ),
            }
            values = task["options"]["values"]
            assert all("options" not in option for option in values), (
                "当前周常菜单只支持一级选择"
            )
        defs.append({k: v for k, v in task.items() if k not in ("class", "config")})
    return defs


def _materialize_daily(script_name: str, declaration: dict) -> dict:
    """物化一条日常声明，选项组按声明形态呈现：

    - 两层日常（各一级项自带子选项组）：一级项即各 value；
    - 单层带 ``key``（选择结果直接写字段）：整组即唯一一级项（展示名用日常名），
      其 values 作二级——与写路径一致（一级项名 = 日常名、值走二级）；
    - 单层无 ``key``（no-op）：values 即一级项。
    """
    options = materialize_options(
        declaration,
        lambda source: get_task_lists(script_name, declaration["display_name"], source),
    )
    assert all(
        "options" not in child
        for option in options["values"]
        if "options" in option
        for child in option["options"]["values"]
    ), "当前日常菜单最多支持两级选择"
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
    # class/config/routine、enable_* 与模板落点（template）都是代码耦合字段
    # （机制类、文件路径、开关与模板落点），不属于 UI 词汇，物化时剥掉。
    declaration = {
        k: v
        for k, v in declaration.items()
        if k
        not in (
            "class",
            "config",
            "routine",
            "enable_key",
            "enable_task",
            "template",
        )
    }
    return {**declaration, "options": options}


def get_daily_map(script_name: str | None = None) -> dict:
    """把日常声明物化成按日常分组的菜单（词汇与声明一致）。

    {script: {"dailies": [日常声明节点, ...]}}，``options.values`` 已物化。菜单
    静态选项直接来自声明，资源选项由适配器统一委托给该日常机制类读取。

    Args:
        script_name: 仅物化指定脚本；省略时返回全部菜单。
    """
    return {
        name: {
            "dailies": [
                _materialize_daily(name, declaration) for declaration in declarations
            ]
        }
        for name, declarations in load_daily_map().items()
        if script_name is None or name == script_name
    }
