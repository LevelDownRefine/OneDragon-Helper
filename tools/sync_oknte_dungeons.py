"""同步异环（ok-nte）副本列表到 config/dungeon_list.yml（CI 自动更新用）。

两个数据源，分别对应 dungeon_list.yml 中 ok-nte 的两类副本：

1. 异象界域（数字序号）—— 源 ok-nte 仓库 src/tasks/AnomalyTask.py 的
   `{TASK}_ID_RANGE = (1, N)`。数字是任务列表中的序号（1-based），N 即副本总数：

       CONSOLE_ID_RANGE = (1, 6)  → 空幕
       ABILITY_ID_RANGE = (1, 5)  → 异能升级材料
       ARC_ID_RANGE = (1, 5)      → 弧盘突破材料

   （EXP_COIN_ID_RANGE 对应「经验与甲硬币」，yml 未配置该分类，不参与。）

2. 追猎目标（字符串 boss 名）—— 源 ok-nte 仓库 src/tasks/AnomalyHunter.py 的
   HUNTER_TARGETS 列表（元素为 TARGET_* 常量，常量值为中文 boss 名）：

       音霸魔王 / 无首铁驭 / 塞润尼缇 / 黑之书 / 海囚 / 围巢鸟 / 斑蝶

对比 dungeon_list.yml 中 ok-nte 的对应分类，检测新增/移除；--apply 时把
新增项以占位条目追加到分类末尾，供人工确认后改友好名（数字类）或核对（boss 名类）。

本文件不 import 项目任何模块，独立可运行（位于 tools/ 下）。

用法：
    python tools/sync_oknte_dungeons.py            # 只检测，输出差异报告
    python tools/sync_oknte_dungeons.py --apply    # 检测并自动补齐新增项

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
_HUNTER_URL = (
    "https://raw.githubusercontent.com/BnanZ0/ok-nte/main/src/tasks/AnomalyHunter.py"
)
# 本文件位于 tools/ 下，需两级 dirname 才到项目根
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DUNGEON_PATH = os.path.join(_PROJECT_ROOT, "config", "dungeon_list.yml")
_OKNTE_KEY = "ok-nte"
_HUNTER_CATEGORY = "追猎目标"
# 上游 _ID_RANGE 前缀 → yml 分类名（EXP_COIN 无对应分类，忽略）
_RANGE_LABELS = {
    "CONSOLE": "空幕",
    "ABILITY": "异能升级材料",
    "ARC": "弧盘突破材料",
}


def _fetch_url(url: str) -> str:
    """抓取上游源码文本；网络失败 → exit 2（区别于"有差异"的 1，CI 据此跳过）。"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.read().decode("utf-8")
    except (urllib.error.URLError, OSError) as exc:
        print(f"[sync_oknte_dungeons] 抓取失败 {url}: {exc}")
        sys.exit(2)


def _fetch_anomaly_totals() -> dict[str, int]:
    """拉取 AnomalyTask.py，返回 {分类: 副本总数}（_ID_RANGE 上限）。"""
    content = _fetch_url(_ANOMALY_URL)
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


def _fetch_hunter_targets() -> list[str]:
    """拉取 AnomalyHunter.py，返回 HUNTER_TARGETS 解析后的中文 boss 名（顺序同上游）。"""
    content = _fetch_url(_HUNTER_URL)
    name_map = dict(re.findall(r'TARGET_(\w+)\s*=\s*"([^"]+)"', content))
    match = re.search(r"HUNTER_TARGETS\s*=\s*\[(.*?)\]", content, re.DOTALL)
    if match is None:
        print("[sync_oknte_dungeons] 上游未找到 HUNTER_TARGETS 定义（结构可能变化）")
        sys.exit(2)
    targets = []
    for const in re.findall(r"TARGET_(\w+)", match.group(1)):
        if const not in name_map:
            print(f"[sync_oknte_dungeons] HUNTER_TARGETS 引用未定义的 TARGET_{const}")
            sys.exit(2)
        targets.append(name_map[const])
    return targets


def _read_yaml() -> dict:
    """读取 dungeon_list.yml 全量。"""
    with open(_DUNGEON_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert isinstance(data, dict) and _OKNTE_KEY in data, (
        f"dungeon_list.yml 缺少 {_OKNTE_KEY} 配置"
    )
    return data


def _write_yaml(data: dict) -> None:
    """写回 dungeon_list.yml（无注释、格式幂等，diff 只含真实增量）。"""
    with open(_DUNGEON_PATH, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False)


def _oknte_dungeons() -> list[dict]:
    """返回 dungeon_list.yml 中 ok-nte 的 dungeons 列表。"""
    return _read_yaml()[_OKNTE_KEY]["dungeons"]


def _load_numeric() -> dict[str, list[int]]:
    """读取 ok-nte 的数字分类 → 数字 value 列表（仅含全为 int 的分类）。"""
    result = {}
    for dungeon in _oknte_dungeons():
        if dungeon.get("name") == "未选择":
            continue
        values = [s["value"] for s in dungeon["sequences"]]
        if values and all(isinstance(v, int) for v in values):
            result[dungeon["name"]] = values
    return result


def _load_hunter() -> list[str]:
    """读取 ok-nte「追猎目标」分类 → 字符串 boss value 列表。"""
    for dungeon in _oknte_dungeons():
        if dungeon.get("name") == _HUNTER_CATEGORY:
            return [
                s["value"]
                for s in dungeon.get("sequences", [])
                if isinstance(s["value"], str)
            ]
    return []


def _apply_numeric(upstream: dict[str, int]) -> None:
    """把新增数字补齐到 yml（display=数字占位，待人工改友好名）。"""
    data = _read_yaml()
    for cat, total in upstream.items():
        dungeon = next(d for d in data[_OKNTE_KEY]["dungeons"] if d["name"] == cat)
        existing = {s["value"] for s in dungeon["sequences"]}
        for num in range(1, total + 1):
            if num not in existing:
                dungeon["sequences"].append({"display": str(num), "value": num})
    _write_yaml(data)


def _apply_hunter(targets: list[str]) -> None:
    """把新增 boss 名补齐到「追猎目标」分类（display=value=中文名）。"""
    data = _read_yaml()
    dungeon = next(
        d for d in data[_OKNTE_KEY]["dungeons"] if d["name"] == _HUNTER_CATEGORY
    )
    existing = {s["value"] for s in dungeon.get("sequences", [])}
    for name in targets:
        if name not in existing:
            dungeon.setdefault("sequences", []).append(
                {"display": name, "value": name}
            )
    _write_yaml(data)


def main() -> int:
    apply = "--apply" in sys.argv
    anomaly_upstream = _fetch_anomaly_totals()
    hunter_upstream = _fetch_hunter_targets()

    # ---- 异象界域（数字）----
    anomaly_current = _load_numeric()
    anomaly_new: dict[str, list[int]] = {}
    anomaly_removed: dict[str, list[int]] = {}
    for cat, total in anomaly_upstream.items():
        expected = set(range(1, total + 1))
        existing = set(anomaly_current.get(cat, []))
        anomaly_new[cat] = sorted(expected - existing)
        anomaly_removed[cat] = sorted(existing - expected)

    # ---- 追猎目标（字符串 boss 名）----
    hunter_current = _load_hunter()
    hunter_new = [t for t in hunter_upstream if t not in set(hunter_current)]
    hunter_removed = [t for t in hunter_current if t not in set(hunter_upstream)]

    has_diff = (
        any(anomaly_new.values())
        or any(anomaly_removed.values())
        or hunter_new
        or hunter_removed
    )
    if not has_diff:
        print("[sync_oknte_dungeons] 无差异")
        return 0

    print(
        "[sync_oknte_dungeons] 上游异象界域总数："
        + "、".join(f"{cat}={total}" for cat, total in anomaly_upstream.items())
    )
    print(f"[sync_oknte_dungeons] 上游追猎目标：{hunter_upstream}")
    for cat in anomaly_upstream:
        if anomaly_new[cat]:
            print(f"新增数字 [{cat}]：{anomaly_new[cat]}（display 待人工改友好名）")
        if anomaly_removed[cat]:
            print(f"移除数字（仅报告不删除）[{cat}]：{anomaly_removed[cat]}")
    if hunter_new:
        print(f"新增追猎目标（待人工核对）[{_HUNTER_CATEGORY}]：{hunter_new}")
    if hunter_removed:
        print(f"移除追猎目标（仅报告不删除）[{_HUNTER_CATEGORY}]：{hunter_removed}")

    if not apply:
        print("[sync_oknte_dungeons] 检测到差异，未应用（加 --apply 自动补齐）")
        return 1

    _apply_numeric(anomaly_upstream)
    _apply_hunter(hunter_upstream)
    print("[sync_oknte_dungeons] 已自动补齐新增项（display 占位/中文名）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
