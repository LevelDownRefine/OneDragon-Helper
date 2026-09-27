"""任务卡聚合查询；编辑复用 AppService 既有写接口。"""

from src.config.daily_config import get_daily_map, get_weekly_map
from src.config.set_config import (
    get_daily_readback,
    is_adapted,
)
from src.config.weekly import get_weekly_task
from src.utils.utils_config import get_script, load_config
from src.utils.utils_sub_config import get_script_name
from src.utils.utils_weekly import get_weekly_start_map


class InvalidTaskSelection(ValueError):
    """任务卡查询引用了不存在的脚本。"""


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
    return {
        "scripts": [
            {**_script_summary(script), "script_data": dict(script)}
            for script in config["script_list"]
        ]
    }


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
    records = {}
    for record in get_daily_readback(script_name):
        assert "name" in record
        name = record["name"]
        assert name not in records, "日常反读记录重复"
        records[name] = record
    for daily in _daily_definitions(script_name):
        assert "display_name" in daily and "options" in daily
        name = daily["display_name"]
        assert name in records, "日常声明与适配器反读记录不一致"
        record = records[name]
        assert all(key in record for key in ("task", "sequence", "enabled"))
        dailies.append({**record, "options": daily["options"]})
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
                "name": name,
                "options": weekly["options"] if "options" in weekly else None,  # noqa: SIM401
                "task": get_weekly_task(script_name, name),
                "start_day": script_starts[name] if name in script_starts else None,  # noqa: SIM401
            }
        )
    return {"script": _script_summary(script), "dailies": dailies, "weeklies": weeklies}
