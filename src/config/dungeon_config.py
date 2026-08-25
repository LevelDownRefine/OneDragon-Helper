from typing import Any

from src.utils import get_root_dir, safe_path_join
from src.utils_yaml import load_yaml_optional

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
