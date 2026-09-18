"""从 MAA 的 StageActivityV2 缓存读取当前客户端的活动单关卡。"""

from datetime import UTC, datetime, timedelta, timezone

from src.utils.utils_dict import get_field
from src.utils.utils_sub_config import load_game_config

# MAA ClientType 的序号；Bilibili 与 Official 共用关卡资源。
CLIENT_RESOURCES = ("Official", "Official", "YoStarEN", "YoStarJP", "YoStarKR", "txwy")


def read_activity_stages(
    script_name: str, resource_path: str, config_path: str
) -> list[str]:
    """使用原生客户端、时区和开放时间，返回去重后的关卡执行值。"""
    config = load_game_config(script_name, config_path)
    data = load_game_config(script_name, resource_path)
    if config is None or data is None:
        return []
    profile = get_field(
        get_field(config, "Configurations", "MAA", dict), "Default", "MAA", dict
    )
    runtime = get_field(
        get_field(profile, "Gui", "MAA", dict), "RuntimeSettings", "MAA", dict
    )
    client = get_field(runtime, "ClientType", "MAA", int)
    assert type(client) is int and 0 <= client < len(CLIENT_RESOURCES)
    server = get_field(data, CLIENT_RESOURCES[client], "MAA", dict)
    groups = get_field(server, "sideStoryStage", "MAA", dict)
    now = datetime.now(UTC)
    result = []
    for group in groups.values():
        activity = get_field(group, "Activity", "MAA", dict)
        offset = 8
        if "TimeZone" in activity:
            offset = activity["TimeZone"]
        zone = timezone(timedelta(hours=offset))
        times = [
            datetime.strptime(
                get_field(activity, field, "MAA", str), "%Y/%m/%d %H:%M:%S"
            ).replace(tzinfo=zone)
            for field in ("UtcStartTime", "UtcExpireTime")
        ]
        if times[0] < now < times[1]:
            for stage in get_field(group, "Stages", "MAA", list):
                value = get_field(stage, "Value", "MAA", str)
                # 复刻导航是一组关卡的指令，不作为单关卡选项。
                if value and not value.startswith("SSReopen-") and value not in result:
                    result.append(value)
    return result
