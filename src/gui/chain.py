"""脚本链配置生成（纯逻辑，GUI 与 CLI 共用）。

复刻 ``MainWindow._generate_config`` 的核心，但去掉 QWidget 依赖：
- 启用脚本集合由调用方以 ``enabled_names`` 传入；
- 副本/序列选择从 ``gui_state.json``（UI 状态）读取，并按 dungeon_list 选项校验，
  与 ``ScriptItem.__init__`` 构造时的取数逻辑一致。
"""

import copy
import logging
import os
from typing import Any

import yaml

from src.config.dungeon_config import (
    load_dungeon_map,
    parse_dungeon_config,
    restore_sequence_type,
)
from src.config.set_config import set_config
from src.gui.utils import apply_weekly_timeout
from src.utils import (
    get_path_under_root,
    get_weekly_timeouts_yml_path_under_root,
    safe_path_join,
)

logger = logging.getLogger(__name__)


def _collect_enabled_selections(
    all_config_data: dict,
    enabled_names: set[str],
    ui_state: dict,
    dungeon_map: dict,
) -> tuple[dict[str, str], dict[str, Any]]:
    """返回 ``(enabled_dungeons, enabled_sequences)``。

    取数逻辑对齐 ``ScriptItem.__init__``：副本来自 ``gui_state.json`` 的 saved_state，
    且必须落在 ``parse_dungeon_config`` 给出的 dungeon 选项内才生效。
    """
    enabled_dungeons: dict[str, str] = {}
    enabled_sequences: dict[str, Any] = {}
    for script in all_config_data["script_list"]:
        name = script["display_name"]
        if name not in enabled_names:
            continue
        dungeon_cfg = dungeon_map.get(name)
        options, seq_map, _ = parse_dungeon_config(dungeon_cfg)
        saved = ui_state.get(name)
        if saved:
            saved = restore_sequence_type(saved, seq_map)
        if saved and saved.get("dungeon") and saved["dungeon"] in (options or []):
            enabled_dungeons[name] = saved["dungeon"]
            if saved.get("sequence"):
                enabled_sequences[name] = saved["sequence"]
    return enabled_dungeons, enabled_sequences


def generate_chain_config(
    all_config_data: dict,
    enabled_names: set[str],
    chain_name: str = "88",
    ui_state: dict | None = None,
    out_path: str | None = None,
) -> str:
    """生成 ScriptChainer 配置文件（仅含启用的脚本），返回输出路径。

    对齐 ``MainWindow._generate_config``：按当天星期套超时、把副本/序列下发到各脚本
    内部 config（``set_config``），写出链 yml。``out_path`` 指定则写该路径，否则默认
    ``config/script_chain/<chain_name>.yml``。
    """
    ui_state = ui_state or {}
    dungeon_map = load_dungeon_map()

    weekly_timeouts: dict = {}
    weekly_path = get_weekly_timeouts_yml_path_under_root()
    if os.path.exists(weekly_path):
        with open(weekly_path, encoding="utf-8") as f:
            weekly_timeouts = yaml.safe_load(f) or {}

    enabled_dungeons, enabled_sequences = _collect_enabled_selections(
        all_config_data, enabled_names, ui_state, dungeon_map
    )

    data = copy.deepcopy(all_config_data)
    filtered = []
    for script in data["script_list"]:
        name = script["display_name"]
        if name in enabled_names:
            apply_weekly_timeout(script, weekly_timeouts)
            set_config(
                name,
                dungeon_name=enabled_dungeons.get(name),
                sequence=enabled_sequences.get(name),
            )
            script.setdefault("block", True)
            filtered.append(script)

    data["script_list"] = filtered

    output_file = out_path or safe_path_join(
        get_path_under_root("config", "script_chain"), f"{chain_name}.yml"
    )
    with open(output_file, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False)
    return output_file
