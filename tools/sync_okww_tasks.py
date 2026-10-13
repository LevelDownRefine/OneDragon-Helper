"""以 ok-ww 的 F2 分组为准同步副本；正式服游戏数据仅补充无音区名称。

凝素领域仍按最前插入模型保留别名。无音区在首次接入或 ok-ww 分组变化时
读取同一正式服提交的副本表和中文文本，数量、分组匹配后才更新名称和编号。
已处理的分组写入 tools/okww_tacet_state.json；游戏数据单独更新不触发同步。

退出码：0 = 无差异或已应用；1 = 有差异未应用；2 = 上游未就绪/解析失败。
"""

import argparse
import json
import logging
import os
import re
import sys
import urllib.error
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

if __package__:
    from .okww_tacet_names import (
        DATA_REPO,
        TacetSnapshot,
        fetch_tacet_snapshot,
        fetch_text,
        require_fields,
    )
else:
    from okww_tacet_names import (
        DATA_REPO,
        TacetSnapshot,
        fetch_tacet_snapshot,
        fetch_text,
        require_fields,
    )

logger = logging.getLogger(__name__)
_yaml = YAML()
_UPSTREAM_ROOT = (
    "https://raw.githubusercontent.com/ok-oldking/ok-wuthering-waves/master"
)
_FORGERY_URL = f"{_UPSTREAM_ROOT}/src/task/ForgeryTask.py"
_TACET_URL = f"{_UPSTREAM_ROOT}/src/task/TacetTask.py"
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DUNGEON_PATH = os.path.join(_PROJECT_ROOT, "config", "daily_task_list.yml")
_STATE_PATH = os.path.join(_PROJECT_ROOT, "tools", "okww_tacet_state.json")
_OKWW_KEY = "ok-ww"
_NUMERIC_CATEGORIES = {_FORGERY_URL: "凝素领域", _TACET_URL: "无音区"}


def _fetch_structures() -> dict[str, list[int]]:
    """先读取 ok-ww 支持的分组；不由游戏数据推断脚本支持范围。"""
    structures = {}
    for url, label in _NUMERIC_CATEGORIES.items():
        content = fetch_text(url)
        match = re.search(r"self\.structure\s*=\s*\[([\d\s,]+)\]", content)
        if match is None:
            raise ValueError(f"{label} 上游未找到 structure 定义")
        structure = [int(value) for value in re.findall(r"\d+", match[1])]
        if not structure or any(value <= 0 for value in structure):
            raise ValueError(f"{label} 上游分组无效：{structure}")
        structures[label] = structure
    return structures


def _daily_tasks(data: dict) -> list[dict]:
    """按日常名定位菜单，避免依赖声明位置。"""
    assert _OKWW_KEY in data, "缺少脚本日常配置"
    matches = []
    for daily in data[_OKWW_KEY]:
        assert "display_name" in daily
        name = (
            daily["physical_name"]
            if "physical_name" in daily
            else daily["display_name"]
        )
        if name == "每日任务":
            matches.append(daily)
    assert len(matches) == 1, "必须唯一声明每日任务"
    assert "options" in matches[0] and "values" in matches[0]["options"]
    return matches[0]["options"]["values"]


def _load_data() -> dict:
    """读取本地任务声明。"""
    with open(_DUNGEON_PATH, encoding="utf-8") as stream:
        data = _yaml.load(stream)
    assert isinstance(data, dict) and _OKWW_KEY in data
    return data


def _load_okww() -> dict[str, list[int]]:
    """读取数字分类的已声明编号。"""
    result = {}
    for task in _daily_tasks(_load_data()):
        assert "display_name" in task
        if task["display_name"] == "未选择":
            continue
        assert "options" in task and "values" in task["options"]
        values = []
        for option in task["options"]["values"]:
            assert "physical_name" in option
            values.append(option["physical_name"])
        if values and all(type(value) is int for value in values):
            assert sorted(values) == list(range(1, len(values) + 1)), (
                "编号必须连续且唯一"
            )
            result[task["display_name"]] = values
    return result


def _rebase_sequences(seqs: list[dict], delta: int) -> list[dict]:
    """凝素领域新增项插在最前，已有别名跟随编号后移。"""
    assert delta > 0
    rebased = [
        {"display_name": str(value), "physical_name": value}
        for value in range(1, delta + 1)
    ]
    for option in seqs:
        assert "physical_name" in option and "display_name" in option
        value = option["physical_name"] + delta
        name = option["display_name"]
        if name == str(option["physical_name"]):
            name = str(value)
        rebased.append({**option, "display_name": name, "physical_name": value})
    rebased.sort(key=lambda option: option["physical_name"])
    assert len({option["display_name"] for option in rebased}) == len(rebased)
    return rebased


def _updated_data(
    upstream: dict[str, int], current: dict[str, list[int]], names: list[str] | None
) -> dict:
    """生成完整变更，抓取与校验结束前不写盘。"""
    data = _load_data()
    for category, total in upstream.items():
        assert category in current
        task = next(
            item for item in _daily_tasks(data) if item["display_name"] == category
        )
        if category == "无音区" and names is not None:
            assert len(names) == total
            task["options"]["values"] = [
                {"display_name": name, "physical_name": index}
                for index, name in enumerate(names, 1)
            ]
        elif total > len(current[category]):
            task["options"]["values"] = _rebase_sequences(
                task["options"]["values"], total - len(current[category])
            )
    return data


def _load_state() -> dict | None:
    """首次接入没有状态；已有状态损坏时停止同步。"""
    if not os.path.exists(_STATE_PATH):
        return None
    state = require_fields(
        json.loads(Path(_STATE_PATH).read_text(encoding="utf-8")),
        ("okww_structure", "ids", "data_commit", "game_version"),
        "无音区同步状态",
    )
    structure, ids = state["okww_structure"], state["ids"]
    if (
        not isinstance(structure, list)
        or not structure
        or any(type(value) is not int or value <= 0 for value in structure)
        or not isinstance(ids, list)
        or any(type(value) is not int for value in ids)
        or len(ids) != sum(structure)
        or len(set(ids)) != len(ids)
    ):
        raise ValueError("无音区同步状态的数量或 ID 无效")
    if (
        not isinstance(state["data_commit"], str)
        or not re.fullmatch(r"[0-9a-f]{40}", state["data_commit"])
        or not isinstance(state["game_version"], str)
        or not re.fullmatch(r"\d+\.\d+\.\d+", state["game_version"])
    ):
        raise ValueError("无音区同步状态的来源提交或版本无效")
    return state


def _snapshot_state(snapshot: TacetSnapshot) -> dict:
    """记录已处理的 ok-ww 分组与可追溯的数据提交。"""
    return {
        "okww_structure": snapshot.structure,
        "ids": snapshot.ids,
        "data_commit": snapshot.revision,
        "game_version": snapshot.version,
    }


def _sync(apply: bool) -> tuple[bool, str]:
    """以 ok-ww 为门槛生成一次同步及可审阅的 PR 报告。"""
    structures = _fetch_structures()
    current = _load_okww()
    upstream = {category: sum(structure) for category, structure in structures.items()}
    assert "无音区" in structures and "无音区" in current
    old_state = _load_state()
    state = old_state
    snapshot = None
    tacet_total = upstream["无音区"]
    needs_names = (
        old_state is None
        or old_state["okww_structure"] != structures["无音区"]
        or len(current["无音区"]) != tacet_total
    )
    report = ["以 ok-ww 的 `self.structure` 为同步依据。", ""]
    if needs_names and tacet_total >= len(current["无音区"]):
        snapshot = fetch_tacet_snapshot(structures["无音区"])
        if old_state is not None:
            previous_ids = old_state["ids"]
            retained = [value for value in snapshot.ids if value in previous_ids]
            if retained != previous_ids:
                raise ValueError("已有无音区消失或相对顺序改变，需人工核对 F2")
        state = _snapshot_state(snapshot)
        report.extend(
            [
                f"无音区分组：`{snapshot.structure}`，共 {len(snapshot.ids)} 项。",
                f"名称来源：[正式服 {snapshot.version}]"
                f"(https://github.com/{DATA_REPO}/tree/{snapshot.revision})。",
                "排序依据游戏数据 SortId（降序），今州同值项沿用既有 F2 顺序；合并前核对菜单。",
                "",
                "| ok-ww 编号 | 正式名称 |",
                "|---|---|",
                *[
                    f"| {index} | {name} |"
                    for index, name in enumerate(snapshot.names, 1)
                ],
                "",
            ]
        )
    else:
        report.append(
            "ok-ww 无音区分组未变或数量回退，不读取游戏数据、不扩展支持范围。"
        )
    for category, total in upstream.items():
        assert category in current
        delta = total - len(current[category])
        if delta < 0:
            report.append(f"{category}：ok-ww 数量回退 {abs(delta)}，仅报告，不删除。")
        elif delta > 0 and category != "无音区":
            report.append(
                f"{category}：最前新增 {delta} 个数字占位，已有别名后移；请人工命名。"
            )
    data = _updated_data(upstream, current, snapshot.names if snapshot else None)
    changed = data != _load_data() or state != old_state
    if apply and changed:
        with open(_DUNGEON_PATH, "w", encoding="utf-8") as stream:
            _yaml.dump(data, stream)
        if state != old_state:
            Path(_STATE_PATH).write_text(
                json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
    return changed, "\n".join(report) + "\n"


def main(argv: list[str] | None = None) -> int:
    """检查或应用一次快照，并为 GitHub Action 输出结果。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    try:
        changed, report = _sync(args.apply)
    except (urllib.error.URLError, OSError, UnicodeError, ValueError, YAMLError) as exc:
        report = f"鸣潮同步暂缓，本次同步未完成：{type(exc).__name__}: {exc}\n"
        logger.warning(report.rstrip())
        if args.report:
            args.report.write_text(report, encoding="utf-8")
        if args.github_output:
            with args.github_output.open("a", encoding="utf-8") as stream:
                stream.write("changed=false\n")
        return 2
    logger.info(report.rstrip())
    if args.report:
        args.report.write_text(report, encoding="utf-8")
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as stream:
            stream.write(f"changed={'true' if changed and args.apply else 'false'}\n")
    logger.info(
        "已应用更新"
        if changed and args.apply
        else "检测到差异"
        if changed
        else "无差异"
    )
    return 1 if changed and not args.apply else 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.exit(main())
