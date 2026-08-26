"""同步鸣潮（ok-ww）副本数字列表到 config/dungeon_list.yml（CI 自动更新用）。

数据源：ok-wuthering-waves 仓库 src/task/ 下各副本 task 类的 `self.structure`。
F2 面板按页展示副本，structure 是每页数量，`total_number = sum(structure)`
即副本总数（数字 1..N 为 F2 面板序号，脚本只认数字不认名字）。

    src/task/ForgeryTask.py  → structure → 凝素领域总数（当前 20）
    src/task/TacetTask.py    → structure → 无音区总数（当前 19）

不变式（关键）：鸣潮新增副本**恒插在最前方**（F2 面板位置 1），已有副本
整体后移。因此别名与副本的绑定靠「跟随滑动」维持——新增 delta 个时，所有
已有别名的 value += delta，最前方补 delta 个占位（value=1..delta，display
先填数字待人工改友好名，如 梦州-迅刀）。模拟领域是固定英文选项，不参与数字
重排。

对比 dungeon_list.yml 中 ok-ww 的纯数字分类（凝素领域/无音区），按总数差
delta 判定：delta>0 为最前插入，--apply 时重排；delta<0 为移除，仅报告不
删除（无法安全重排，交人工核对）。

本文件不 import 项目任何模块，独立可运行（位于 tools/ 下）。

用法：
    python tools/sync_okww_dungeons.py            # 只检测，输出差异报告
    python tools/sync_okww_dungeons.py --apply    # 检测并自动重排

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


def _rebase_sequences(seqs: list[dict], delta: int) -> list[dict]:
    """最前插入 delta 个新副本时重排序列（纯函数，便于单测）。

    鸣潮新增副本恒插在最前方（F2 面板位置 1），已有副本整体后移 delta 位。
    因此别名与其副本的绑定靠「跟随滑动」维持：已有条目 ``value += delta``，
    最前方补 delta 个占位（``value = 1..delta``，display 先填数字待人工改名）。

    Args:
        seqs: 当前序列条目列表（每条含 ``display``/``value``）。
        delta: 新增副本数（必须 > 0）。

    Returns:
        重排后的序列列表，按 ``value`` 升序。
    """
    assert delta > 0, "[sync_okww] delta 必须为正"
    rebased: list[dict] = [{"display": str(v), "value": v} for v in range(1, delta + 1)]
    for s in seqs:
        rebased.append({"display": s["display"], "value": s["value"] + delta})
    rebased.sort(key=lambda s: s["value"])
    return rebased


def _apply_new(upstream: dict[str, int], current: dict[str, list[int]]) -> None:
    """按最前插入模型重排 yml 中的 ok-ww 数字分类。

    dungeon_list.yml 已由 yaml 统一管理（无注释、格式幂等），
    直接 load→改→dump 即可，重写后 diff 只含真实增量。仅处理新增
    （delta>0）类别；移除（delta<0）不在此处理，交由报告人工核对。
    """
    with open(_DUNGEON_PATH, encoding="utf-8") as f:
        data = _yaml.load(f)
    for cat, total in upstream.items():
        old_count = len(current.get(cat, []))
        delta = total - old_count
        if delta <= 0:
            continue  # 无新增；移除不在此处理
        dungeon = next(d for d in data[_OKWW_KEY]["dungeons"] if d["name"] == cat)
        dungeon["sequences"] = _rebase_sequences(dungeon["sequences"], delta)
    with open(_DUNGEON_PATH, "w", encoding="utf-8") as f:
        _yaml.dump(data, f)


def main() -> int:
    apply = "--apply" in sys.argv
    upstream = _fetch_totals()
    current = _load_okww()

    deltas: dict[str, int] = {}
    for cat, total in upstream.items():
        old_count = len(current.get(cat, []))
        delta = total - old_count
        if delta != 0:
            deltas[cat] = delta

    if not deltas:
        print("[sync_okww_dungeons] 无差异")
        return 0

    print(
        "[sync_okww_dungeons] 上游总数："
        + "、".join(f"{cat}={total}" for cat, total in upstream.items())
    )
    for cat, delta in deltas.items():
        if delta > 0:
            print(
                f"最前新增 {delta} 个副本 [{cat}]：位置 1..{delta} 为占位（待人工改友好名），"
                f"已有别名整体后移 {delta} 位"
            )
        else:
            print(
                f"移除 {-delta} 个副本（仅报告不删除）[{cat}]：别名无法安全重排，请人工核对"
            )

    if not apply:
        print("[sync_okww_dungeons] 检测到差异，未应用（加 --apply 自动重排）")
        return 1

    _apply_new(upstream, current)
    print("[sync_okww_dungeons] 已重排：新增副本插最前、已有别名后移")
    return 0


if __name__ == "__main__":
    sys.exit(main())
