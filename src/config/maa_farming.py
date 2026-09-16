"""MAS 刷图任务生成规则；不读写配置，名字和用药由 Daily 适配。

生成流程源自 AUTO-MAS c26f1095，app/task/MAA/AutoProxy.py。
基础模板按 MAA 的 FightTask 配置定义维护，用药由 Daily 独立管理。
"""

# Copyright (C) 2024-2025 DLmaster361
# Copyright (C) 2025-2026 AUTO-MAS Team
# SPDX-License-Identifier: AGPL-3.0-or-later
# https://github.com/AUTO-MAS-Project/AUTO-MAS/tree/c26f1095c98d0e5c9c17a8a314e019f8facab7d9
# License text: LICENSES/AUTO-MAS-AGPL-3.0.txt

from copy import deepcopy
from functools import cache

from src.utils.utils_dict import get_field
from src.utils.utils_sub_config import load_template


@cache
def _fight_template() -> dict:
    """缓存随项目发布的 MAA 配置片段，调用方使用副本。"""
    # MAA 7e5de9b3，src/MaaWpfGui/Configuration/Single/MaaTask/FightTask.cs。
    template = load_template("MAA", "MAA战斗任务.json")
    assert isinstance(template, dict)
    assert get_field(template, "$type", "MAA", str) == "FightTask"
    assert get_field(template, "TaskType", "MAA", str) == "Fight"
    return template


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
    """使用 MAA 基础配置，指定剩余理智关卡和连战。"""
    task = deepcopy(source) | deepcopy(_fight_template())
    task.update(Name=name, StagePlan=[stage], Series=series, IsStageManually=True)
    return task


def build_annihilation_fight(source: dict, name: str, stage: str) -> dict:
    """使用 MAA 基础配置，指定剿灭关卡。"""
    task = deepcopy(source) | deepcopy(_fight_template())
    task.update(
        Name=name,
        StagePlan=["Annihilation"],
        UseCustomAnnihilation=True,
        AnnihilationStage=stage,
    )
    return task


def build_farming_queue(
    source_queue: list[dict],
    annihilation: dict,
    activity: dict,
    main: dict,
    remaining: dict,
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
    priority = [deepcopy(annihilation), deepcopy(activity)]
    queue[start:start] = priority
    start += len(priority)
    depot = next(
        (i + 1 for i, task in enumerate(queue) if task["TaskType"] == "DepotMaintain"),
        start,
    )
    start = max(start, depot)
    queue[start:start] = [deepcopy(main), deepcopy(remaining)]
    return queue
