"""读取 MAA 本地活动资源，按客户端和开放时间筛选关卡。"""

import logging
from datetime import UTC, datetime, timedelta, timezone

from src.utils.utils_dict import get_field
from src.utils.utils_sub_config import load_game_config

logger = logging.getLogger(__name__)
_SERVERS = ("Official", "Official", "YoStarEN", "YoStarJP", "YoStarKR", "txwy")


def load_activity_stages(
    script_name: str, source: str, config_path: str = "config/gui.new.json"
) -> list[str]:
    """按原生客户端类型及活动开放时间读取关卡代码，缺文件返回空列表。"""
    try:
        data = load_game_config(script_name, source)
        config = load_game_config(script_name, config_path)
    except (OSError, ValueError):
        logger.warning("[MAA] 活动资源读取失败: %s", source, exc_info=True)
        return []
    if data is None or config is None:
        return []
    configurations = get_field(config, "Configurations", "MAA", dict)
    default = get_field(configurations, "Default", "MAA", dict)
    gui = get_field(default, "Gui", "MAA", dict)
    runtime = get_field(gui, "RuntimeSettings", "MAA", dict)
    client = get_field(runtime, "ClientType", "MAA")
    if type(client) is int and 0 <= client < len(_SERVERS):
        server_name = _SERVERS[client]
    elif isinstance(client, str) and client in (*_SERVERS, "Bilibili"):
        server_name = "Official" if client == "Bilibili" else client
    else:
        logger.warning("[MAA] 未识别的客户端类型: %r", client)
        return []
    if server_name not in data:
        logger.warning("[MAA] 本地活动资源没有客户端 %s 的数据", server_name)
        return []
    server = data[server_name]
    stories = get_field(server, "sideStoryStage", "MAA", dict)
    now = datetime.now(UTC)
    stages = []
    for story in stories.values():
        activity = get_field(story, "Activity", "MAA", dict)
        # MAA 旧活动资源可省略时区，原生默认 UTC+8。
        offset = 8
        if "TimeZone" in activity:
            offset = activity["TimeZone"]
        try:
            zone = timezone(timedelta(hours=offset))
            start = datetime.strptime(
                get_field(activity, "UtcStartTime", "MAA", str), "%Y/%m/%d %H:%M:%S"
            ).replace(tzinfo=zone)
            end = datetime.strptime(
                get_field(activity, "UtcExpireTime", "MAA", str), "%Y/%m/%d %H:%M:%S"
            ).replace(tzinfo=zone)
        except (ValueError, TypeError, OverflowError):
            logger.warning("[MAA] 活动时间无效，跳过该活动", exc_info=True)
            continue
        if not start < now < end:
            continue
        for stage in get_field(story, "Stages", "MAA", list):
            value = get_field(stage, "Value", "MAA", str)
            # MAS getStage 的活动材料关列表按 Display 排除复刻导航入口，保留资源顺序。
            display = get_field(stage, "Display", "MAA", str)
            if value and "SSReopen" not in display:
                stages.append(value)
    return stages
