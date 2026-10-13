"""从正式服游戏数据补充 ok-ww 已支持的无音区名称。"""

import http.client
import json
import re
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass
from urllib.parse import quote

DATA_REPO = "Arikatsu/WutheringWaves_Data"
AREA_PATH = "BinData/adventure_detect/silentareadetection.json"
TEXT_PATH = "Textmaps/zh-Hans/multi_text/MultiText.json"
# 今州七项 SortId 相同；顺序与已使用的 F2 编号一致。
_JINZHOU_IDS = (30010001, 30010009, 30010010, 30010011, 30010012, 30010013, 30010016)


@dataclass(frozen=True)
class TacetSnapshot:
    """同一提交下的名称、身份与分组。"""

    revision: str
    version: str
    structure: list[int]
    ids: list[int]
    names: list[str]


def fetch_text(url: str) -> str:
    """读取公开上游；调用方处理网络或解码失败。"""
    request = urllib.request.Request(url, headers={"User-Agent": "OneDragon-Helper"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read().decode("utf-8")
    except (OSError, http.client.HTTPException) as exc:
        raise urllib.error.URLError(f"{type(exc).__name__}: {exc}") from exc


def require_fields(row: object, fields: tuple[str, ...], context: str) -> dict:
    """外部数据字段缺失时停止本次同步。"""
    if not isinstance(row, dict) or any(field not in row for field in fields):
        raise ValueError(f"{context} 缺少字段 {fields}")
    return row


def parse_tacet_data(
    records: object, text_rows: object, expected_structure: list[int]
) -> tuple[list[int], list[str]]:
    """只解析无音清剿，按 SortId 降序生成编号并核对 ok-ww 分组。"""
    if not isinstance(records, list) or not isinstance(text_rows, list):
        raise ValueError("无音区表和中文文本表必须是列表")
    selected = []
    for item in records:
        row = require_fields(item, ("Secondary",), "副本记录")
        if row["Secondary"] != 22:
            continue
        row = require_fields(
            row, ("Id", "Name", "SortId", "DetectionTabType"), "无音区记录"
        )
        if any(
            type(row[key]) is not int for key in ("Id", "SortId", "DetectionTabType")
        ):
            raise ValueError("无音区 ID、排序与分组必须是整数")
        if not isinstance(row["Name"], str) or not row["Name"]:
            raise ValueError("无音区名称键不能为空")
        selected.append(row)
    if len(selected) != sum(expected_structure):
        raise ValueError(
            f"游戏数据有 {len(selected)} 个无音区，ok-ww 支持 "
            f"{sum(expected_structure)} 个；等待两边一致"
        )
    if len({row["Id"] for row in selected}) != len(selected):
        raise ValueError("无音区 ID 重复")
    for sort_id, count in Counter(row["SortId"] for row in selected).items():
        if count > 1:
            tied = {row["Id"] for row in selected if row["SortId"] == sort_id}
            if tied != set(_JINZHOU_IDS):
                raise ValueError(f"无音区 SortId={sort_id} 重复，需核对 F2 顺序")
    selected.sort(key=lambda row: (-row["SortId"], row["Id"]))
    tabs: list[int] = []
    structure: list[int] = []
    for row in selected:
        tab = row["DetectionTabType"]
        if not tabs or tabs[-1] != tab:
            if tab in tabs:
                raise ValueError("无音区分组不连续，需核对 F2 顺序")
            tabs.append(tab)
            structure.append(0)
        structure[-1] += 1
    if structure != expected_structure:
        raise ValueError(
            f"游戏数据分组 {structure} 与 ok-ww {expected_structure} 不一致"
        )

    wanted = {row["Name"] for row in selected}
    texts: dict[str, str] = {}
    for item in text_rows:
        row = require_fields(item, ("Id", "Content"), "中文文本")
        if not isinstance(row["Id"], str):
            raise ValueError("中文文本 ID 必须是字符串")
        key = row["Id"]
        if key not in wanted:
            continue
        name = row["Content"]
        if not isinstance(name, str) or not name.strip() or "无音区" not in name:
            raise ValueError(f"无音区中文名称无效：{key}")
        if key in texts:
            raise ValueError(f"无音区中文文本重复：{key}")
        texts[key] = name
    missing = wanted - texts.keys()
    if missing:
        raise ValueError(f"缺少无音区中文名称：{sorted(missing)}")
    names = [texts[row["Name"]] for row in selected]
    if len(set(names)) != len(names):
        raise ValueError("无音区中文名称重复")
    return [row["Id"] for row in selected], names


def fetch_tacet_snapshot(expected_structure: list[int]) -> TacetSnapshot:
    """固定正式服提交，防止两份表来自不同版本。"""
    api = f"https://api.github.com/repos/{DATA_REPO}"
    repo = require_fields(
        json.loads(fetch_text(api)), ("default_branch",), "游戏数据仓库"
    )
    branch = repo["default_branch"]
    if not isinstance(branch, str) or not re.fullmatch(r"\d+\.\d+", branch):
        raise ValueError(f"游戏数据默认分支不是正式版本：{branch}")
    commit = require_fields(
        json.loads(fetch_text(f"{api}/commits/{quote(branch, safe='')}")),
        ("sha",),
        "游戏数据提交",
    )
    revision = commit["sha"]
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("游戏数据提交 SHA 无效")
    raw = f"https://raw.githubusercontent.com/{DATA_REPO}/{revision}"
    readme = fetch_text(f"{raw}/README.md")
    if not re.search(r"Status:\s*Release\b", readme):
        raise ValueError("游戏数据不是 Release，等待正式服数据")
    match = re.search(r"Game Version:\s*(\d+\.\d+\.\d+)", readme)
    if match is None or not match[1].startswith(f"{branch}."):
        raise ValueError("游戏数据版本与默认分支不一致")
    records = json.loads(fetch_text(f"{raw}/{AREA_PATH}"))
    texts = json.loads(fetch_text(f"{raw}/{TEXT_PATH}"))
    ids, names = parse_tacet_data(records, texts, expected_structure)
    return TacetSnapshot(revision, match[1], expected_structure, ids, names)
