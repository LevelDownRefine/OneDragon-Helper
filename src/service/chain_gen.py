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
from typing import Any

import yaml

from src.config.dungeon_config import (
    load_dungeon_map,
    parse_dungeon_config,
    restore_sequence_type,
)
from src.config.set_config import set_config
from src.config.subscript import DEFAULT_RUN_TIMEOUT, get_script_name
from src.utils import (
    get_path_under_root,
    safe_path_join,
)
from src.utils_weekly import get_week_num

logger = logging.getLogger(__name__)


def _resolve_daily_run(script: dict, weekly_timeouts: dict) -> bool:
    """按 weekly_timeouts.yml 解析脚本当天是否运行，运行时就地设置超时。

    weekly_timeouts 的 key 为脚本唯一标识（exe 用进程名，脚本文件用 display_name）。

    - 有完整 7 格且当天值 >= 10 → 取当天值作为 run_timeout_seconds，返回 True。
    - 当天值 < 10 → 视为「当天不运行」，不设置超时字段，返回 False。
    - 无条目 / 不足 7 格 → fallback 到 DEFAULT_RUN_TIMEOUT，返回 True。

    Returns:
        True 表示脚本当天应运行；False 表示不运行，调用方应从链中剔除。
    """
    assert "script_path" in script, "[chain_gen] script_list 条目缺少 script_path 字段"
    script_name = get_script_name(script)
    if script_name not in weekly_timeouts:
        script["run_timeout_seconds"] = DEFAULT_RUN_TIMEOUT
        return True
    timeouts = weekly_timeouts[script_name]
    if timeouts and len(timeouts) == 7:
        week_value = timeouts[get_week_num()]
        if week_value < 10:
            logger.warning(
                "[chain_gen] %s 当天超时 %s 秒低于下限 10，跳过不运行",
                script_name,
                week_value,
            )
            return False
        script["run_timeout_seconds"] = week_value
        return True
    script["run_timeout_seconds"] = DEFAULT_RUN_TIMEOUT
    return True


def _resolve_weekly_start(weekly_start_map: dict, script_name: str) -> int | None:
    """取脚本的周常起始日（1=周一 ~ 7=周日），未设置返回 None。

    周常开关（enabled）是 GUI 内存态，不参与链生成；GUI 与 CLI 统一按
    「今天周几 >= 起始日」由 set_config 判断启用/停用写入脚本配置
    （与日常副本选择落盘不受日常开关影响的模型一致）。

    起始日来源为 weekly_start.yml（运行时由 ScriptService 持久化），经
    weekly_start_map 传入，不再来自 gui_state.json。

    Args:
        weekly_start_map: weekly_start.yml 的全量映射（{脚本标识: 1~7}）。
        script_name: 脚本唯一标识（exe 为进程名、python/bat 为 display_name）。

    Returns:
        周常起始日（1~7），未设置返回 None。
    """
    if script_name not in weekly_start_map:
        return None
    weekly_start = weekly_start_map[script_name]
    assert isinstance(weekly_start, int), (
        f"[chain_gen] {script_name} 非法 weekly_start: {weekly_start!r}（应为整数 1~7）"
    )
    assert 1 <= weekly_start <= 7, (
        f"[chain_gen] {script_name} 非法 weekly_start: {weekly_start}（应为 1~7）"
    )
    return weekly_start


def _collect_enabled_selections(
    all_config_data: dict,
    enabled_keys: set[str],
    ui_state: dict,
    dungeon_map: dict,
) -> tuple[dict[str, str], dict[str, Any]]:
    """收集启用脚本的副本/序列选择。

    Args:
        all_config_data: config.yml 完整数据（含 script_list）。
        enabled_keys: 要纳入链的脚本唯一标识集合。
        ui_state: gui_state.json 的 UI 状态（副本/序列选择），key 为脚本唯一标识。
        dungeon_map: dungeon_list.yml 的副本配置映射，key 为脚本唯一标识。

    Returns:
        (enabled_dungeons, enabled_sequences)，仅含在 dungeon 选项内的选择。
    """
    enabled_dungeons: dict[str, str] = {}
    enabled_sequences: dict[str, Any] = {}
    for script in all_config_data["script_list"]:
        assert "script_path" in script, (
            "[chain_gen] script_list 条目缺少 script_path 字段"
        )
        script_name = get_script_name(script)
        if script_name not in enabled_keys:
            continue
        dungeon_cfg = dungeon_map.get(script_name)
        options, seq_map, _ = parse_dungeon_config(dungeon_cfg)
        saved = ui_state.get(script_name)
        if saved:
            saved = restore_sequence_type(saved, seq_map)
        if saved and saved.get("dungeon") and saved["dungeon"] in (options or []):
            enabled_dungeons[script_name] = saved["dungeon"]
            if saved.get("sequence"):
                enabled_sequences[script_name] = saved["sequence"]
    return enabled_dungeons, enabled_sequences


def generate_chain_config(
    all_config_data: dict,
    enabled_keys: set[str],
    chain_name: str = "today",
    ui_state: dict | None = None,
    out_path: str | None = None,
    weekly_timeouts: dict | None = None,
    weekly_start_map: dict | None = None,
) -> str:
    """生成 ScriptChainer 配置文件（仅含启用的脚本）。

    weekly_timeouts 与 weekly_start_map 均由调用方（ChainService）通过
    ScriptService 加载后传入，不再直接读取磁盘文件。

    Args:
        all_config_data: config.yml 完整数据（含 script_list）。
        enabled_keys: 要纳入链的脚本唯一标识集合。
        chain_name: 链配置文件名（不含扩展名）。
        ui_state: gui_state.json 的 UI 状态（副本/序列选择），key 为脚本唯一标识。
        out_path: 输出路径；None 时默认 config/script_chain/<chain_name>.yml。
        weekly_timeouts: weekly_timeouts.yml 的全量字典（默认空 dict）。
        weekly_start_map: weekly_start.yml 的全量映射（{脚本标识: 1~7}）。

    Returns:
        输出文件路径。
    """
    ui_state = ui_state or {}
    weekly_timeouts = weekly_timeouts or {}
    weekly_start_map = weekly_start_map or {}
    dungeon_map = load_dungeon_map()

    enabled_dungeons, enabled_sequences = _collect_enabled_selections(
        all_config_data, enabled_keys, ui_state, dungeon_map
    )

    data = copy.deepcopy(all_config_data)
    filtered = []
    for script in data["script_list"]:
        assert "script_path" in script, (
            "[chain_gen] script_list 条目缺少 script_path 字段"
        )
        script_name = get_script_name(script)
        if script_name in enabled_keys:
            if not _resolve_daily_run(script, weekly_timeouts):
                continue
            weekly_start = _resolve_weekly_start(weekly_start_map, script_name)
            set_config(
                script_name,
                dungeon_name=enabled_dungeons.get(script_name),
                sequence=enabled_sequences.get(script_name),
                weekly_start=weekly_start,
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
