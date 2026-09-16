"""MAS 刷图任务生成规则；不读写配置，名字和用药由 Daily 适配。

来源：AUTO-MAS c26f1095，app/task/MAA/AutoProxy.py 与 app/utils/constants.py。
保留其「复制原生选项 → 覆盖托管字段」语义，创建和运行使用同一套规则。
"""

# Copyright (C) 2024-2025 DLmaster361
# Copyright (C) 2025-2026 AUTO-MAS Team
# SPDX-License-Identifier: AGPL-3.0-or-later
# https://github.com/AUTO-MAS-Project/AUTO-MAS/tree/c26f1095c98d0e5c9c17a8a314e019f8facab7d9
# License text: LICENSES/AUTO-MAS-AGPL-3.0.txt

from copy import deepcopy

from src.utils.utils_dict import get_field

# MAS 的 MAA_REMAIN_FIGHT_BASE；任务名字与用药字段由 Daily 管理。
REMAIN_FIGHT_BASE = {
    "$type": "FightTask",
    "EnableTargetDrop": False,
    "DropId": "",
    "DropCount": 0,
    "IsInventoryTarget": False,
    "EnableTimesLimit": False,
    "TimesLimit": 999,
    "Series": 0,
    "StagePlan": [""],
    "IsDrGrandet": False,
    "UseCustomAnnihilation": False,
    "AnnihilationStage": "Annihilation",
    "HideUnavailableStage": True,
    "IsStageManually": True,
    "UseOptionalStage": False,
    "HideSeries": False,
    "UseWeeklySchedule": False,
    "WeeklySchedule": {
        "Sunday": True,
        "Monday": True,
        "Tuesday": True,
        "Wednesday": True,
        "Thursday": True,
        "Friday": True,
        "Saturday": True,
    },
    "IsEnable": True,
    "TaskType": "Fight",
}

# MAS 的剿灭基础配置；两者共有字段相同，下面列出其全部差异。
ANNIHILATION_FIGHT_BASE = deepcopy(REMAIN_FIGHT_BASE) | {
    "StagePlan": ["Annihilation"],
    "UseCustomAnnihilation": True,
    "IsStageManually": False,
}


def find_fight_source(queue: list[dict], name: str) -> dict | None:
    """MAS 的 Fight 精确匹配：取第一个同名同类型任务，无类型兜底。"""
    for task in queue:
        if (
            get_field(task, "TaskType", "MAA", str) == "Fight"
            and get_field(task, "Name", "MAA", str) == name
        ):
            return deepcopy(task)
    return None


def build_main_fight(source: dict, name: str, stage: str, series: int) -> dict:
    """MAS Routine 脚本模式；本项目固定选择一个理智作战关卡。"""
    task = deepcopy(source)
    task.update(
        {
            "$type": "FightTask",
            "Name": name,
            "TaskType": "Fight",
            "UseCustomAnnihilation": False,
            "Series": series,
            "StagePlan": [stage],
            "IsStageManually": True,
            "UseOptionalStage": True,
            "UseWeeklySchedule": False,
            "EnableTimesLimit": False,
            "EnableTargetDrop": False,
            "IsEnable": True,
        }
    )
    return task


def build_activity_fight(source: dict, name: str, stage: str) -> dict:
    """适配 MAS 活动任务字段，名字与用药交由 Daily 管理。"""
    task = deepcopy(source)
    task.update(
        {
            "Name": name,
            "IsEnable": True,
            "TaskType": "Fight",
            "StagePlan": [stage],
            "IsStageManually": True,
            "UseOptionalStage": False,
            "UseWeeklySchedule": False,
            "EnableTargetDrop": False,
            "DropId": "",
            "DropCount": 0,
            "IsInventoryTarget": False,
            "EnableTimesLimit": False,
        }
    )
    if "$type" not in task:
        task["$type"] = "FightTask"
    return task


def build_remaining_fight(source: dict, name: str, stage: str, series: int) -> dict:
    """MAS 原生来源与 MAA_REMAIN_FIGHT_BASE 合并后应用计划关卡和连战。"""
    task = deepcopy(source) | deepcopy(REMAIN_FIGHT_BASE)
    task.update(Name=name, StagePlan=[stage], Series=series)
    return task


def build_annihilation_fight(source: dict, name: str, stage: str) -> dict:
    """MAS 剿灭阶段的任务生成；本项目随后接到同一次 MAA 执行的最前面。"""
    task = deepcopy(source) | deepcopy(ANNIHILATION_FIGHT_BASE)
    task.update(Name=name, AnnihilationStage=stage)
    return task


def build_runtime_queue(
    source_queue: list[dict],
    annihilation: dict,
    activity: dict | None,
    main: dict | None,
    remaining: dict | None,
) -> list[dict]:
    """移植 MAS 重新生成战斗队列的流程，只接管本项目范围内的 Fight。

    框架适配：剿灭在同一次进程中先跑；非 Fight 原样保留；停用角色保留
    禁用的配置项供 Daily 反读，不进入实际执行。库存保持仍位于主作战之前。
    """
    queue = [
        deepcopy(task)
        for task in source_queue
        if get_field(task, "TaskType", "MAA", str) != "Fight"
    ]
    start = next(
        (i + 1 for i, task in enumerate(queue) if task["TaskType"] == "StartUp"),
        0,
    )
    priority = [deepcopy(annihilation)]
    if activity is not None:
        priority.append(deepcopy(activity))
    queue[start:start] = priority
    start += len(priority)
    depot = next(
        (i + 1 for i, task in enumerate(queue) if task["TaskType"] == "DepotMaintain"),
        start,
    )
    start = max(start, depot)
    queue[start:start] = [
        deepcopy(task) for task in (main, remaining) if task is not None
    ]
    return queue
