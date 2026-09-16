"""适配 MAA 的 FightTask 配置及原生执行队列，不承担读写和调度。

字段依据 MAA 的配置定义，单关卡及队列顺序由本项目约定。
历史版本改编自 AUTO-MAS c26f1095，保留来源及版权声明。
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


def find_fight_task(queue: list[dict], name: str) -> dict | None:
    """按声明的物理名定位原生任务，返回队列中的首个匹配项。"""
    for task in queue:
        if (
            get_field(task, "TaskType", "MAA", str) == "Fight"
            and get_field(task, "Name", "MAA", str) == name
        ):
            return task
    return None


def build_fight_task(source: dict, name: str, stage: str) -> dict:
    """缺任务时使用固定模板，已有任务只改接管的单关卡和限制开关。"""
    task = deepcopy(source if source else _fight_template())
    task.update(
        {
            "$type": "FightTask",
            "Name": name,
            "IsEnable": True,
            "TaskType": "Fight",
            "StagePlan": [stage],
            "IsStageManually": True,
            "UseCustomAnnihilation": False,
            "UseOptionalStage": False,
            "UseWeeklySchedule": False,
            "EnableTargetDrop": False,
            "EnableTimesLimit": False,
        }
    )
    return task


def build_annihilation_fight(source: dict, name: str, stage: str) -> dict:
    """使用 MAA 基础配置，指定剿灭关卡。"""
    task = build_fight_task(source, name, "Annihilation")
    task.update(
        IsStageManually=False,
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
    """按本项目约定排列原生队列，实际执行及禁用项跳过由 MAA 完成。

    剿灭和活动接在唤醒后，理智作战和剩余理智接在库存保持后。
    非 Fight 保留原有顺序，停用入口保留配置供 Daily 反读。
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
