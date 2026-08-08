"""脚本链配置生成（纯逻辑，无 Qt 依赖）。

复刻 ``MainWindow._generate_config`` 的核心，但去掉 QWidget 依赖：
- 启用脚本集合由调用方以 ``enabled_names`` 传入；
- 副本/序列选择从 ``gui_state.json``（UI 状态）读取，并按 dungeon_list 选项校验，
  与 ``ScriptItem.__init__`` 构造时的取数逻辑一致。

脚本配置合法性校验（对齐 runner invalid_message）见 ``src.utils_runner``。
自 ``src.gui.chain`` 迁出：不依赖 Qt，收编到 service 层便于无头测试与 GUI/CLI 共用。
"""

import copy
import logging
import os
from datetime import datetime, timedelta
from typing import Any

import yaml

from src.config.dungeon_config import (
    load_dungeon_map,
    parse_dungeon_config,
    restore_sequence_type,
)
from src.config.set_config import set_config
from src.config.subscript import DEFAULT_RUN_TIMEOUT
from src.utils import (
    get_path_under_root,
    get_weekly_timeouts_yml_path_under_root,
    safe_path_join,
)

logger = logging.getLogger(__name__)


def _get_week_num() -> int:
    """返回星期数字：0周一 ~ 6周日（凌晨 4 点为界，4 点前归前一天）。"""
    return (datetime.now() - timedelta(hours=4)).weekday()


def _apply_weekly_timeout(script: dict, weekly_timeouts: dict) -> None:
    """根据 weekly_timeouts.yml 就地设置 script['run_timeout_seconds']。

    - 有完整 7 格 → 取当天值，且不低于 10（避免 0 秒杀脚本）。
    - 无条目 / 不足 7 格 → fallback 到 DEFAULT_RUN_TIMEOUT。
    """
    assert "display_name" in script, (
        "[chain_gen] script_list 条目缺少 display_name 字段"
    )
    name = script["display_name"]
    if name not in weekly_timeouts:
        script["run_timeout_seconds"] = DEFAULT_RUN_TIMEOUT
        return
    timeouts = weekly_timeouts[name]
    if timeouts and len(timeouts) == 7:
        script["run_timeout_seconds"] = max(timeouts[_get_week_num()], 10)
    else:
        script["run_timeout_seconds"] = DEFAULT_RUN_TIMEOUT


def _collect_enabled_selections(
    all_config_data: dict,
    enabled_names: set[str],
    ui_state: dict,
    dungeon_map: dict,
) -> tuple[dict[str, str], dict[str, Any]]:
    """收集启用脚本的副本/序列选择。

    Args:
        all_config_data: config.yml 完整数据（含 script_list）。
        enabled_names: 要纳入链的脚本 display_name 集合。
        ui_state: gui_state.json 的 UI 状态（副本/序列选择）。
        dungeon_map: dungeon_list.yml 的副本配置映射。

    Returns:
        (enabled_dungeons, enabled_sequences)，仅含在 dungeon 选项内的选择。
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
    """生成 ScriptChainer 配置文件（仅含启用的脚本）。

    Args:
        all_config_data: config.yml 完整数据（含 script_list）。
        enabled_names: 要纳入链的脚本 display_name 集合。
        chain_name: 链配置文件名（不含扩展名）。
        ui_state: gui_state.json 的 UI 状态（副本/序列选择）。
        out_path: 输出路径；None 时默认 config/script_chain/<chain_name>.yml。

    Returns:
        输出文件路径。
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
            _apply_weekly_timeout(script, weekly_timeouts)
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
