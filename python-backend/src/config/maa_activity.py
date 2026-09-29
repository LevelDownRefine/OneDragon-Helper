"""从 MAA 的 StageActivityV2 缓存读取当前客户端的活动单关卡。"""

import logging
from datetime import UTC, datetime, timedelta, timezone

from src.utils.utils_dict import get_field
from src.utils.utils_sub_config import load_game_config

logger = logging.getLogger(__name__)

# MAA 的 ClientType 是客户端名而非序号：Bilibili 与 Official 共用关卡资源，其余同名。
CLIENT_RESOURCES = {
    "Official": "Official",
    "Bilibili": "Official",
    "YoStarEN": "YoStarEN",
    "YoStarJP": "YoStarJP",
    "YoStarKR": "YoStarKR",
    "txwy": "txwy",
}


def read_activity_stages(
    script_name: str, resource_path: str, config_path: str
) -> list[str]:
    """使用原生客户端、时区和开放时间，返回去重后的关卡执行值。"""
    config = load_game_config(script_name, config_path)
    data = load_game_config(script_name, resource_path)
    if config is None or data is None:
        return []
    # 外层骨架（Configurations/Default）缺失属配置损坏，保持严格 assert 暴露问题。
    configurations = get_field(config, "Configurations", "MAA", dict)
    default = get_field(configurations, "Default", "MAA", dict)
    # MAA 未初始化时主配置缺 Gui 段，属可恢复状态：无活动关卡而非崩溃，并记日志。
    gui = default.get("Gui")
    if not isinstance(gui, dict):
        logger.warning(
            "[MAA][%s] 主配置缺 Gui 段（Arknights MAA 未初始化），活动关卡返回空",
            script_name,
        )
        return []
    runtime = get_field(gui, "RuntimeSettings", "MAA", dict)
    client = get_field(runtime, "ClientType", "MAA", str)
    assert client in CLIENT_RESOURCES, f"[MAA] 未知客户端: {client}"
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
