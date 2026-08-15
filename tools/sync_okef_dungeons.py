"""同步终末地（ok-ef）关卡列表到 config/dungeon_list.yml（CI 自动更新用）。

数据源：ok-end-field 仓库 assets/data/world_map.json 的 stages_dict
（{分类: [关卡名]}，脚本仓库自带，同源权威）。终末地副本 display=value=关卡名，
分类 = stages_dict 的 key，均可自动生成——与原神不同（原神 display 需人工
套装配对，见 .workbuddy/skills/sync-bgi-dungeons/），因此本脚本可全自动。

对比 dungeon_list.yml 中 ok-ef 的分类与关卡名集合，输出差异报告；
--apply 时自动补齐：新增分类整块追加、新增关卡追加到对应分类末尾
（display=value=关卡名）。移除的关卡仅报告不删除（避免上游短暂缺失时丢配置）。

本文件不 import 项目任何模块，独立可运行（位于 tools/ 下）。

用法：
    python tools/sync_okef_dungeons.py            # 只检测，输出差异报告
    python tools/sync_okef_dungeons.py --apply    # 检测并自动补齐新增条目

退出码：0 = 无差异（或已应用）；1 = 有差异未应用；2 = 抓取/解析失败（跳过本次）。
"""

import json
import os
import sys
import urllib.error
import urllib.request

import yaml

_WORLD_MAP_URL = (
    "https://raw.githubusercontent.com/AliceJump/ok-end-field/"
    "master/assets/data/world_map.json"
)
# 本文件位于 tools/ 下，需两级 dirname 才到项目根
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DUNGEON_PATH = os.path.join(_PROJECT_ROOT, "config", "dungeon_list.yml")
_OKEF_KEY = "ok-ef"


def _fetch_stages() -> dict[str, list[str]]:
    """拉取 world_map.json，返回 stages_dict（{分类: [关卡名]}）。

    网络失败或数据结构变化 → exit 2（区别于"有差异"的 1，CI 据此跳过不开 PR）。
    """
    try:  # 外部网络操作，失败可恢复，以 exit 2 区分于"有差异"
        req = urllib.request.Request(
            _WORLD_MAP_URL, headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.load(resp)
    except (urllib.error.URLError, OSError) as exc:
        print(f"[sync_okef_dungeons] 抓取失败 {_WORLD_MAP_URL}: {exc}")
        sys.exit(2)
    if "stages_dict" not in data:
        print(
            "[sync_okef_dungeons] 上游 world_map.json 缺少 stages_dict（结构可能变化）"
        )
        sys.exit(2)
    return data["stages_dict"]


def _load_okef() -> dict[str, list[str]]:
    """读取 dungeon_list.yml 中 ok-ef 的分类 → 关卡 value 列表。"""
    with open(_DUNGEON_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert isinstance(data, dict) and _OKEF_KEY in data, (
        f"dungeon_list.yml 缺少 {_OKEF_KEY} 配置"
    )
    return {
        d["name"]: [s["value"] for s in d["sequences"]]
        for d in data[_OKEF_KEY]["dungeons"]
        if d.get("name") != "未选择"
    }


def _apply_new(upstream: dict[str, list[str]], current: dict[str, list[str]]) -> None:
    """把新增分类/关卡补齐到 yml（display=value=关卡名，全自动无需人工）。

    dungeon_list.yml 已由 yaml 统一管理（无注释、格式幂等），
    直接 load→改→dump 即可，重写后 diff 只含真实增量。
    """
    with open(_DUNGEON_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    okef = data[_OKEF_KEY]
    existing_names = {d["name"] for d in okef["dungeons"]}
    for cat, stages in upstream.items():
        if cat not in existing_names:
            okef["dungeons"].append(
                {
                    "name": cat,
                    "sequences": [{"display": s, "value": s} for s in stages],
                }
            )
            continue
        dungeon = next(d for d in okef["dungeons"] if d["name"] == cat)
        existing_values = {s["value"] for s in dungeon["sequences"]}
        for stage in stages:
            if stage not in existing_values:
                dungeon["sequences"].append({"display": stage, "value": stage})
    with open(_DUNGEON_PATH, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False)


def main() -> int:
    apply = "--apply" in sys.argv
    upstream = _fetch_stages()
    current = _load_okef()

    new_categories = sorted(set(upstream) - set(current))
    removed_categories = sorted(set(current) - set(upstream))
    new_stages = {
        cat: sorted(set(stages) - set(current.get(cat, [])))
        for cat, stages in upstream.items()
        if cat in current
    }
    new_stages = {cat: stages for cat, stages in new_stages.items() if stages}
    removed_stages = {
        cat: sorted(set(current[cat]) - set(upstream.get(cat, [])))
        for cat in current
        if cat in upstream
    }
    removed_stages = {cat: stages for cat, stages in removed_stages.items() if stages}

    if (
        not new_categories
        and not removed_categories
        and not new_stages
        and not removed_stages
    ):
        print("[sync_okef_dungeons] 无差异")
        return 0

    print(
        f"[sync_okef_dungeons] 上游 {len(upstream)} 个分类 / yml {len(current)} 个分类"
    )
    if new_categories:
        print(f"新增分类：{new_categories}")
    if new_stages:
        for cat, stages in new_stages.items():
            print(f"新增关卡 [{cat}]：{stages}")
    if removed_categories:
        print(f"移除分类（yml 有、上游缺，仅报告不删除）：{removed_categories}")
    if removed_stages:
        for cat, stages in removed_stages.items():
            print(f"移除关卡（仅报告不删除）[{cat}]：{stages}")

    if not apply:
        print("[sync_okef_dungeons] 检测到差异，未应用（加 --apply 自动补齐）")
        return 1

    _apply_new(upstream, current)
    print("[sync_okef_dungeons] 已自动补齐新增分类/关卡（display=value=关卡名）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
