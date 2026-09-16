"""读取 MAA 的本地关卡与导航资源，不另存关卡清单。"""

import logging
import re
from datetime import UTC, datetime, timedelta, timezone
from pathlib import PurePosixPath

from src.utils.utils_dict import get_field
from src.utils.utils_sub_config import load_game_config

logger = logging.getLogger(__name__)
_SERVERS = ("Official", "Official", "YoStarEN", "YoStarJP", "YoStarKR", "txwy")
# 与 MAS 的常驻菜单对齐；主线只展示这三个常用关，资源本仍从 MAA 读取。
_COMMON_MAIN_STAGES = ("1-7", "R8-11", "12-17-HARD")


def load_normal_stages(script_name: str, source: str) -> list[str]:
    """按 MAS 的范围展示常用主线、资源本和芯片本，核对原生导航入口。"""
    resource = PurePosixPath(source).parent
    try:
        stages = load_game_config(script_name, source)
        if stages is None:
            return []
        tasks = load_game_config(script_name, str(resource / "tasks/tasks.json"))
        if tasks is None:
            # 旧版 MAA 将主线和资源本导航集中在同一个文件。
            tasks = load_game_config(script_name, str(resource / "tasks.json"))
        else:
            supplies = load_game_config(
                script_name, str(resource / "tasks/Stages/Supplies.json")
            )
            if supplies is not None:
                assert isinstance(supplies, dict), "MAA 资源本导航必须是字典"
                tasks = tasks | supplies
    except (OSError, ValueError):
        logger.warning("[MAA] 普通关卡资源读取失败: %s", source, exc_info=True)
        return []
    if tasks is None:
        return []
    assert isinstance(stages, list), "MAA 关卡资源必须是列表"
    assert isinstance(tasks, dict), "MAA 导航任务必须是字典"
    main_stages, resource_stages = set(), set()
    codes = {get_field(stage, "code", "MAA", str) for stage in stages}
    for stage in stages:
        stage_id = get_field(stage, "stageId", "MAA", str)
        code = get_field(stage, "code", "MAA", str)
        if stage_id.startswith(("main_", "sub_", "tough_")):
            match = re.fullmatch(r"[A-Za-z]{0,3}(\d{1,2})-\d{1,2}", code)
            if match is None or (
                code not in tasks and f"Episode{match[1]}" not in tasks
            ):
                continue
            if stage_id.startswith("tough_"):
                # MAA 主线导航以 -HARD 选择磨难关；15 章起切换方式不同。
                chapter = int(match[1])
                switches = (
                    {"ChangeToRaidDifficulty", "RaidConfirm"}
                    if chapter >= 15
                    else {"ChapterDifficultyHard"}
                )
                if chapter < 10 or not switches <= tasks.keys():
                    continue
                code += "-HARD"
            if code in _COMMON_MAIN_STAGES:
                main_stages.add(code)
        elif stage_id.startswith(("wk_", "pro_")) and code in tasks:
            # CE-5 / LS-5 等旧入口在 MAA 中重定向到新关卡，只展示实际目标。
            task = tasks[code]
            if "next" in task and len(task["next"]) == 1:
                target = task["next"][0]
                if target != code and target in codes:
                    continue
            resource_stages.add(code)

    def stage_order(code: str) -> list:
        return [
            int(part) if part.isdigit() else part for part in re.split(r"(\d+)", code)
        ]

    return [code for code in _COMMON_MAIN_STAGES if code in main_stages] + sorted(
        resource_stages, key=stage_order
    )


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
