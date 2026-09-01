"""脚本链配置生成（纯逻辑，无 Qt 依赖）。

复刻 ``MainWindow._generate_config`` 的核心，但去掉 QWidget 依赖：
- 启用脚本集合由调用方以 ``enabled_names`` 传入；
- 副本/序列选择来自子脚本 config（GUI/CLI 编辑期经 set_config 实时落盘），
  按 dungeon_list 选项校验。

脚本配置合法性校验（对齐 runner invalid_message）见 ``src.utils_runner``。
自 ``src.gui.chain`` 迁出：不依赖 Qt，收编到 service 层便于无头测试与 GUI/CLI 共用。
"""

import copy
import logging

from src.config.subscript import DEFAULT_RUN_TIMEOUT, get_script_name
from src.utils import (
    get_path_under_root,
    safe_path_join,
)
from src.utils_weekly import get_week_num
from src.utils_yaml import dump_yaml

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


def resolve_weekly_start(weekly_start_map: dict, script_name: str) -> int | None:
    """取脚本的周常起始日（1=周一 ~ 7=周日），未设置返回 None。

    周常开关（enabled）是 GUI 内存态，不参与链生成；GUI 与 CLI 统一按
    「今天周几 >= 起始日」由 set_config 判断启用/停用写入脚本配置
    （与日常副本选择落盘不受日常开关影响的模型一致）。

    起始日来源为 weekly_start.yml（运行时由 ScriptService 持久化），经
    weekly_start_map 传入。

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


def generate_chain_config(
    all_config_data: dict,
    enabled_keys: set[str],
    chain_name: str = "today",
    out_path: str | None = None,
    weekly_timeouts: dict | None = None,
) -> str:
    """生成 ScriptChainer 配置文件（仅含启用的脚本）。

    脚本自身的副本/序列、周常起始日对应的周本开关，均由 GUI / CLI 在编辑期实时落盘
    （见 ``set_config``）；其中「按周几起决定开启/关闭」这类必须在运行期按当天星期
    计算的周本开关写盘，已抽出为 ``ScheduledRun`` 的 pre_run 步骤（由 ``build_pre_run_pipeline`` 在运行前统一写回），
    故本函数只负责按星期过滤脚本并生成链 yml，不再写任何子脚本 config。

    weekly_timeouts 由调用方（ChainService）通过 ScriptService 加载后传入，不再直接读取磁盘文件。

    Args:
        all_config_data: config.yml 完整数据（含 script_list）。
        enabled_keys: 要纳入链的脚本唯一标识集合。
        chain_name: 链配置文件名（不含扩展名）。
        out_path: 输出路径；None 时默认 config/script_chain/<chain_name>.yml。
        weekly_timeouts: weekly_timeouts.yml 的全量字典（默认空 dict）。

    Returns:
        输出文件路径。
    """
    weekly_timeouts = weekly_timeouts or {}
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
            script.setdefault("block", True)
            filtered.append(script)

    data["script_list"] = filtered

    output_file = out_path or safe_path_join(
        get_path_under_root("config", "script_chain"), f"{chain_name}.yml"
    )
    dump_yaml(output_file, data)
    return output_file
