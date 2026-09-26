"""任务卡查询与编辑：聚合适配器数据，校验来自 CLI 的选择。"""

from src.config.daily_config import get_daily_map, get_weekly_map
from src.config.set_config import get_daily_readback, is_adapted, set_config
from src.config.weekly import get_weekly_task
from src.utils.utils_config import get_script, load_config
from src.utils.utils_sub_config import get_script_name
from src.utils.utils_weekly import get_weekly_start_map


class InvalidTaskSelection(ValueError):
    """请求引用了不存在的脚本、日常或选项。"""


def _script_summary(script: dict) -> dict:
    assert "display_name" in script and "script_path" in script
    script_name = get_script_name(script)
    return {
        "script_name": script_name,
        "display_name": script["display_name"],
        "script_path": script["script_path"],
        "adapted": is_adapted(script_name),
    }


def app_snapshot() -> dict:
    """只读脚本列表，不预热所有脚本的适配器。"""
    config = load_config()
    assert "script_list" in config
    return {"scripts": [_script_summary(script) for script in config["script_list"]]}


def _require_script(script_name: str) -> dict:
    script = get_script(script_name)
    if script is None:
        raise InvalidTaskSelection(f"脚本不存在: {script_name}")
    return script


def _daily_definitions(script_name: str) -> list[dict]:
    menus = get_daily_map(script_name)
    if script_name not in menus:
        return []
    assert "dailies" in menus[script_name]
    return menus[script_name]["dailies"]


def script_view(script_name: str) -> dict:
    """返回脚本身份、日常/周常选项及反读状态；不缓存外部配置快照。"""
    script = _require_script(script_name)
    dailies = []
    records = get_daily_readback(script_name)
    for daily in _daily_definitions(script_name):
        assert "display_name" in daily and "options" in daily
        matches = []
        for record in records:
            assert "name" in record
            if record["name"] == daily["display_name"]:
                matches.append(record)
        assert len(matches) == 1, "日常声明与适配器反读记录不一致"
        record = matches[0]
        assert all(key in record for key in ("task", "sequence", "enabled"))
        dailies.append(
            {
                "daily_name": daily["display_name"],
                "options": daily["options"],
                "selected": {
                    "task_name": record["task"],
                    "sequence": record["sequence"],
                },
                "enabled": record["enabled"],
            }
        )
    weeklies = []
    definitions = get_weekly_map(script_name)
    starts = get_weekly_start_map() if definitions else {}
    # 周常可以尚未配置起始日；按项目约定显式区分缺失字段。
    script_starts = starts[script_name] if script_name in starts else {}  # noqa: SIM401
    for weekly in definitions:
        assert "display_name" in weekly
        name = weekly["display_name"]
        weeklies.append(
            {
                "weekly_name": name,
                "options": weekly["options"] if "options" in weekly else None,  # noqa: SIM401
                "selected": get_weekly_task(script_name, name),
                "start_day": script_starts[name] if name in script_starts else None,  # noqa: SIM401
            }
        )
    return {"script": _script_summary(script), "dailies": dailies, "weeklies": weeklies}


def select_daily(
    script_name: str,
    daily_name: str,
    task_name: str,
    sequence: str | int | bool | None = None,
) -> dict:
    """校验物化菜单后复用原适配器写盘（含启用语义），返回实际任务卡。"""
    _require_script(script_name)
    if not is_adapted(script_name):
        raise InvalidTaskSelection(f"脚本没有日常适配: {script_name}")
    for daily in _daily_definitions(script_name):
        assert "display_name" in daily and "options" in daily
        if daily["display_name"] == daily_name:
            break
    else:
        raise InvalidTaskSelection(f"日常不存在: {daily_name}")
    assert "values" in daily["options"]
    for option in daily["options"]["values"]:
        assert "display_name" in option
        if option["display_name"] == task_name:
            break
    else:
        raise InvalidTaskSelection(f"一级选项不存在: {task_name}")
    if "options" in option:
        assert "values" in option["options"]
        allowed = []
        for child in option["options"]["values"]:
            assert "physical_name" in child
            allowed.append(child["physical_name"])
        # bool 是 int 的子类，但 JSON 的 true 与 1 是不同的选项。
        if type(sequence) not in (str, int, bool) or not any(
            sequence == value and isinstance(sequence, bool) == isinstance(value, bool)
            for value in allowed
        ):
            raise InvalidTaskSelection("sequence 必须是当前二级选项的 physical_name")
    elif sequence is not None:
        raise InvalidTaskSelection("该选项没有二级选择，sequence 必须为 null")
    set_config(script_name, daily_name, task_name, sequence)
    return script_view(script_name)
