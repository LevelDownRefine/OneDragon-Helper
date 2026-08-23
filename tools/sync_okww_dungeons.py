"""同步鸣潮（ok-ww）副本数字列表到 config/dungeon_list.yml（CI 自动更新用）。

数据源：ok-wuthering-waves 仓库 src/task/ 下各副本 task 类的 `self.structure`。
F2 面板按页展示副本，structure 是每页数量，`total_number = sum(structure)`
即副本总数（数字 1..N 为 F2 面板序号，脚本只认数字不认名字）。

    src/task/ForgeryTask.py  → structure → 凝素领域总数（当前 20）
    src/task/TacetTask.py    → structure → 无音区总数（当前 19）

对比 dungeon_list.yml 中 ok-ww 的纯数字分类（凝素领域/无音区；模拟领域是
固定英文选项不参与），检测数字上限变化；--apply 时把新增数字以占位条目
（display=数字）追加到对应分类末尾，供人工确认后改友好名（梦州-迅刀 等）。

本文件不 import 项目任何模块，独立可运行（位于 tools/ 下）。

用法：
    python tools/sync_okww_dungeons.py            # 只检测，输出差异报告
    python tools/sync_okww_dungeons.py --apply    # 检测并自动补齐新增数字

退出码：0 = 无差异（或已应用）；1 = 有差异未应用；2 = 抓取/解析失败（跳过本次）。
"""

import os
import re
import sys
import urllib.error
import urllib.request

from ruamel.yaml import YAML

_yaml = YAML()

_FORGERY_URL = (
    "https://raw.githubusercontent.com/ok-oldking/ok-wuthering-waves/"
    "master/src/task/ForgeryTask.py"
)
_TACET_URL = (
    "https://raw.githubusercontent.com/ok-oldking/ok-wuthering-waves/"
    "master/src/task/TacetTask.py"
)
# 本文件位于 tools/ 下，需两级 dirname 才到项目根
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DUNGEON_PATH = os.path.join(_PROJECT_ROOT, "config", "dungeon_list.yml")
_OKWW_KEY = "ok-ww"
# 数字分类：上游 task 文件 → yml 分类名
_NUMERIC_CATEGORIES = {
    _FORGERY_URL: "凝素领域",
    _TACET_URL: "无音区",
}


def _fetch_totals() -> dict[str, int]:
    """拉取各 task 文件，返回 {分类: 副本总数}（structure 之和）。

    网络失败或上游结构变化 → exit 2（区别于"有差异"的 1，CI 据此跳过不开 PR）。
    """
    totals = {}
    for url, label in _NUMERIC_CATEGORIES.items():
        try:  # 外部网络操作，失败可恢复，以 exit 2 区分于"有差异"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                content = resp.read().decode("utf-8")
        except (urllib.error.URLError, OSError) as exc:
            print(f"[sync_okww_dungeons] 抓取失败 {url}: {exc}")
            sys.exit(2)
        match = re.search(r"self\.structure\s*=\s*\[([\d\s,]+)\]", content)
        if match is None:
            print(
                f"[sync_okww_dungeons] {label} 上游未找到 structure 定义（结构可能变化）"
            )
            sys.exit(2)
        structure = [int(x) for x in re.findall(r"\d+", match.group(1))]
        totals[label] = sum(structure)
    return totals


def _load_okww() -> dict[str, list[int]]:
    """读取 dungeon_list.yml 中 ok-ww 的纯数字分类 → 数字 value 列表。"""
    with open(_DUNGEON_PATH, encoding="utf-8") as f:
        data = _yaml.load(f)
    assert isinstance(data, dict) and _OKWW_KEY in data, (
        f"dungeon_list.yml 缺少 {_OKWW_KEY} 配置"
    )
    result = {}
    for dungeon in data[_OKWW_KEY]["dungeons"]:
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
        data = _yaml.load(f)
    for cat, total in upstream.items():
        dungeon = next(d for d in data[_OKWW_KEY]["dungeons"] if d["name"] == cat)
        existing = {s["value"] for s in dungeon["sequences"]}
        for num in range(1, total + 1):
            if num not in existing:
                dungeon["sequences"].append({"display": str(num), "value": num})
    with open(_DUNGEON_PATH, "w", encoding="utf-8") as f:
        _yaml.dump(data, f)


def main() -> int:
    apply = "--apply" in sys.argv
    upstream = _fetch_totals()
    current = _load_okww()

    new_numbers = {}
    removed = {}
    for cat, total in upstream.items():
        expected = set(range(1, total + 1))
        existing = set(current.get(cat, []))
        new_numbers[cat] = sorted(expected - existing)
        removed[cat] = sorted(existing - expected)

    if not any(new_numbers.values()) and not any(removed.values()):
        print("[sync_okww_dungeons] 无差异")
        return 0

    print(
        "[sync_okww_dungeons] 上游总数："
        + "、".join(f"{cat}={total}" for cat, total in upstream.items())
    )
    for cat in upstream:
        if new_numbers[cat]:
            print(f"新增数字 [{cat}]：{new_numbers[cat]}（display 待人工改友好名）")
        if removed[cat]:
            print(f"移除数字（仅报告不删除）[{cat}]：{removed[cat]}")

    if not apply:
        print("[sync_okww_dungeons] 检测到差异，未应用（加 --apply 自动补齐）")
        return 1

    _apply_new(upstream, current)
    print("[sync_okww_dungeons] 已自动补齐新增数字（display=数字占位）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
