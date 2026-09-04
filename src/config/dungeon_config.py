import os
from typing import Any

from src.config.set_config import get_dungeon_lists
from src.utils import (
    get_root_dir,
    get_weekly_list_yml_path_under_root,
    safe_path_join,
)
from src.utils.utils_yaml import load_yaml, load_yaml_optional

DungeonOptions = list[str]
SequenceOptionsMap = dict[str, list[tuple[str, Any]]]


def get_dungeon_config_path() -> str:
    return safe_path_join(get_root_dir(), "config", "dungeon_list.yml")


def load_dungeon_map() -> dict[str, Any]:
    return load_yaml_optional(get_dungeon_config_path())


def parse_dungeon_config(
    dungeon_cfg: Any,
) -> tuple[DungeonOptions, SequenceOptionsMap, bool]:
    """
    解析单个脚本的副本配置。

    配置格式（结构化）：
    dungeons:
      - name: "副本名"
      - name: "有二级选项的副本"
        sequences:
          - display: "显示名称"
            value: 实际值

    Args:
        dungeon_cfg: 从 dungeon_list.yml 读取的配置项

    Returns:
        (options, seq_map, show_seq)
        - options: 一级副本名称列表
        - seq_map: 副本名 → [(display_name, actual_value), ...]
        - show_seq: 是否有二级选项
    """
    options: DungeonOptions = []
    seq_map: SequenceOptionsMap = {}
    show_seq = False

    if isinstance(dungeon_cfg, dict) and "dungeons" in dungeon_cfg:
        for i, dungeon in enumerate(dungeon_cfg["dungeons"]):
            assert isinstance(dungeon, dict), (
                f"第{i}个副本配置必须是字典，实际是 {type(dungeon)}"
            )
            assert "name" in dungeon, f"第{i}个副本配置缺少 'name' 字段"
            assert isinstance(dungeon["name"], str), (
                f"第{i}个副本的 'name' 必须是字符串"
            )

            name = dungeon["name"]
            options.append(name)

            sequences = dungeon.get("sequences")  # optional: 副本可能没有二级选项
            if sequences:
                assert isinstance(sequences, list), (
                    f"副本 '{name}' 的 sequences 必须是列表"
                )
                seq_map[name] = []
                for j, seq in enumerate(sequences):
                    assert isinstance(seq, dict), f"副本 '{name}' 第{j}个序列必须是字典"
                    assert "display" in seq, (
                        f"副本 '{name}' 第{j}个序列缺少 'display' 字段"
                    )
                    assert "value" in seq, f"副本 '{name}' 第{j}个序列缺少 'value' 字段"
                    assert isinstance(seq["display"], str), (
                        f"副本 '{name}' 第{j}个序列的 'display' 必须是字符串"
                    )
                    seq_map[name].append((seq["display"], seq["value"]))
                show_seq = True

    return options, seq_map, show_seq


def get_display_name(
    seq_map: SequenceOptionsMap, dungeon_name: str, actual_value: Any
) -> str:
    """
    根据实际值获取对应的显示名称。

    Args:
        seq_map: 副本名 → [(display_name, actual_value), ...]
        dungeon_name: 副本名称
        actual_value: 实际值

    Returns:
        显示名称，如果找不到则返回实际值的字符串表示
    """
    assert dungeon_name in seq_map, (
        f"[dungeon_config] 副本 '{dungeon_name}' 不在序列映射中"
    )
    seq_options = seq_map[dungeon_name]
    for display_name, val in seq_options:
        if val == actual_value:
            return display_name
    return str(actual_value)


def _load_weekly_map() -> dict:
    """读取 weekly_list.yml（周常声明配置，进 git，必存在）。

    结构：{script_name: [{"name", "dungeons"?}, ...]}。周常起始日（周几起）另存于
    weekly_start.yml，不在本文件。
    """
    weekly_list_path = get_weekly_list_yml_path_under_root()
    assert os.path.exists(weekly_list_path), (
        f"[dungeon_config] 周常声明配置缺失: {weekly_list_path}"
    )
    data = load_yaml(weekly_list_path)
    # 空文件或内容非 dict 都是声明配置损坏，直接暴露而非静默当成「无声明」。
    assert isinstance(data, dict), (
        f"[dungeon_config] 周常声明配置应为 dict（空文件或格式错误）: {weekly_list_path}"
    )
    return data


def get_weekly_map(script_name: str) -> list:
    """返回某脚本支持的周常声明清单（weekly_list.yml）。

    每项：{"name", "dungeons"?}。dungeons 存在且有内容即表示该周常需选副本。
    声明项若带 ``dungeons_source`` 标记，副本清单取自游戏脚本自身配置（运行期读取，
    get_dungeon_lists），读不到时降级为 dungeons=[]。文件缺失或该脚本无声明时返回空列表。
    """
    defs_map = _load_weekly_map()
    if script_name not in defs_map:
        return []
    defs = list(defs_map[script_name])
    for d in defs:
        source = d.get("dungeons_source")
        if source:
            # 副本清单来自外部（如 M7A 的 instance_names.json），运行期读取，不再手动维护；
            # 读不到则降级为无可选副本（has_dungeon=False）。
            names = get_dungeon_lists(script_name, d["name"], source)
            d["dungeons"] = names if names is not None else []
    return defs


def get_dungeon_map() -> dict:
    """返回日常副本/序列配置映射（dungeon_list.yml）。

    声明项若带 ``dungeons_source`` 标记，其二级序列取自游戏脚本自身配置（运行期读取，
    get_dungeon_lists），读不到时降级为 sequences=[]。文件缺失时返回空 dict。
    """
    data = load_dungeon_map()
    for script_name, cfg in data.items():
        if not isinstance(cfg, dict):
            continue
        for d in cfg.get("dungeons", []):
            if not isinstance(d, dict):
                continue
            source = d.get("dungeons_source")
            if source:
                # 二级序列来自外部（如 ok-ef 的 world_map.json），运行期读取，不手动维护；
                # 读不到则降级为无可选序列（show_seq=False）。
                names = get_dungeon_lists(script_name, d["name"], source)
                d["sequences"] = (
                    [{"display": n, "value": n} for n in names] if names else []
                )
    return data
