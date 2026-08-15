"""同步异环（ok-nte）副本数字列表到 config/dungeon_list.yml（CI 自动更新用）。

数据源：ok-nte 仓库 src/tasks/AnomalyTask.py 的 `{TASK}_ID_RANGE = (1, N)`。
数字是任务列表中的序号（1-based），范围由上游代码写死，N 即副本总数：

    CONSOLE_ID_RANGE = (1, 6)  → 空幕
    ABILITY_ID_RANGE = (1, 5)  → 异能升级材料
    ARC_ID_RANGE = (1, 5)      → 弧盘突破材料

（EXP_COIN_ID_RANGE 对应「经验与甲硬币」，yml 未配置该分类，不参与。）

对比 dungeon_list.yml 中 ok-nte 的数字分类，检测数字上限变化；--apply 时把
新增数字以占位条目（display=数字）追加到对应分类末尾，供人工确认后改友好名
（光暗/鸟/苹果 等）。

本文件不 import 项目任何模块，独立可运行（位于 tools/ 下）。

用法：
    python tools/sync_oknte_dungeons.py            # 只检测，输出差异报告
    python tools/sync_oknte_dungeons.py --apply    # 检测并自动补齐新增数字

退出码：0 = 无差异（或已应用）；1 = 有差异未应用；2 = 抓取/解析失败（跳过本次）。
"""

import os
import re
import sys
import urllib.error
import urllib.request

import yaml

_ANOMALY_URL = (
    "https://raw.githubusercontent.com/BnanZ0/ok-nte/main/src/tasks/AnomalyTask.py"
)
# 本文件位于 tools/ 下，需两级 dirname 才到项目根
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DUNGEON_PATH = os.path.join(_PROJECT_ROOT, "config", "dungeon_list.yml")
_OKNTE_KEY = "ok-nte"
# 上游 _ID_RANGE 前缀 → yml 分类名（EXP_COIN 无对应分类，忽略）
_RANGE_LABELS = {
    "CONSOLE": "空幕",
    "ABILITY": "异能升级材料",
    "ARC": "弧盘突破材料",
}


def _fetch_totals() -> dict[str, int]:
    """拉取 AnomalyTask.py，返回 {分类: 副本总数}（_ID_RANGE 上限）。

    网络失败或上游结构变化 → exit 2（区别于"有差异"的 1，CI 据此跳过不开 PR）。
    """
    try:  # 外部网络操作，失败可恢复，以 exit 2 区分于"有差异"
        req = urllib.request.Request(
            _ANOMALY_URL, headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            content = resp.read().decode("utf-8")
    except (urllib.error.URLError, OSError) as exc:
        print(f"[sync_oknte_dungeons] 抓取失败 {_ANOMALY_URL}: {exc}")
        sys.exit(2)
    totals = {}
    for prefix, label in _RANGE_LABELS.items():
        match = re.search(rf"{prefix}_ID_RANGE\s*=\s*\(\d+,\s*(\d+)\)", content)
        if match is None:
            print(
                f"[sync_oknte_dungeons] {label} 上游未找到 {prefix}_ID_RANGE"
                " 定义（结构可能变化）"
            )
            sys.exit(2)
        totals[label] = int(match.group(1))
    return totals


def _load_oknte() -> dict[str, list[int]]:
    """读取 dungeon_list.yml 中 ok-nte 的数字分类 → 数字 value 列表。"""
    with open(_DUNGEON_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert isinstance(data, dict) and _OKNTE_KEY in data, (
        f"dungeon_list.yml 缺少 {_OKNTE_KEY} 配置"
    )
    result = {}
    for dungeon in data[_OKNTE_KEY]["dungeons"]:
        if dungeon.get("name") == "未选择":
            continue
        values = [s["value"] for s in dungeon["sequences"]]
        if values and all(isinstance(v, int) for v in values):
            result[dungeon["name"]] = values
    return result


def _apply_new(upstream: dict[str, int], current: dict[str, list[int]]) -> None:
    """把新增数字补齐到 yml（display=数字占位，待人工改友好名）。

    dungeon_list.yml 已由 yaml 统一管理（无注释、格式幂等），
    直接 load→改→dump 即可，重写后 diff 只含真实增量。
    """
    with open(_DUNGEON_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    for cat, total in upstream.items():
        dungeon = next(d for d in data[_OKNTE_KEY]["dungeons"] if d["name"] == cat)
        existing = {s["value"] for s in dungeon["sequences"]}
        for num in range(1, total + 1):
            if num not in existing:
                dungeon["sequences"].append({"display": str(num), "value": num})
    with open(_DUNGEON_PATH, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False)


def main() -> int:
    apply = "--apply" in sys.argv
    upstream = _fetch_totals()
    current = _load_oknte()

    new_numbers = {}
    removed = {}
    for cat, total in upstream.items():
        expected = set(range(1, total + 1))
        existing = set(current.get(cat, []))
        new_numbers[cat] = sorted(expected - existing)
        removed[cat] = sorted(existing - expected)

    if not any(new_numbers.values()) and not any(removed.values()):
        print("[sync_oknte_dungeons] 无差异")
        return 0

    print(
        "[sync_oknte_dungeons] 上游总数："
        + "、".join(f"{cat}={total}" for cat, total in upstream.items())
    )
    for cat in upstream:
        if new_numbers[cat]:
            print(f"新增数字 [{cat}]：{new_numbers[cat]}（display 待人工改友好名）")
        if removed[cat]:
            print(f"移除数字（仅报告不删除）[{cat}]：{removed[cat]}")

    if not apply:
        print("[sync_oknte_dungeons] 检测到差异，未应用（加 --apply 自动补齐）")
        return 1

    _apply_new(upstream, current)
    print("[sync_oknte_dungeons] 已自动补齐新增数字（display=数字占位）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
