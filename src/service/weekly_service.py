"""WeeklyService：脚本周运行配置服务（无 Qt 依赖）。

管理两个「脚本周维度」的持久化配置：
- weekly_timeouts.yml：每个脚本的周超时设置（7 天 × N 脚本）
- weekly_start.yml：每个脚本的周起始日（1~7）

设计为纯数据读写层，不含 config.yml 查询或其他脚本级逻辑。
调用方（ScriptService / ChainService）负责跨文件校验与业务编排。

内部标识统一用**脚本唯一标识 script_name**（exe 脚本为进程名、脚本文件为
display_name），display_name 仅用于展示。
"""

import logging
import os

from src.config.subscript import DEFAULT_RUN_TIMEOUT
from src.utils import (
    get_weekly_start_yml_path_under_root,
    get_weekly_timeouts_yml_path_under_root,
)
from src.utils_yaml import dump_yaml, load_yaml

logger = logging.getLogger(__name__)


def _load_weekly() -> dict:
    """读取 weekly_timeouts.yml（随包发布、必存在）。

    assert 存在且为 dict，损坏直接暴露而非静默兜底。
    """
    weekly_path = get_weekly_timeouts_yml_path_under_root()
    assert os.path.exists(weekly_path), f"[service] 周常超时配置缺失: {weekly_path}"
    data = load_yaml(weekly_path)
    assert isinstance(data, dict), (
        f"[service] 周常超时配置应为 dict（空文件或格式错误）: {weekly_path}"
    )
    return data


def _dump_weekly(weekly_map: dict) -> None:
    """写回 weekly_timeouts.yml。"""
    weekly_path = get_weekly_timeouts_yml_path_under_root()
    dump_yaml(weekly_path, weekly_map)


def _load_weekly_start() -> dict:
    """读取 weekly_start.yml（周常起始日持久化配置，进 git，必存在）。

    结构：{script_name: 1~7}。assert 存在且为 dict，损坏直接暴露而非静默兜底。
    """
    weekly_start_path = get_weekly_start_yml_path_under_root()
    assert os.path.exists(weekly_start_path), (
        f"[service] 周常起始日配置缺失: {weekly_start_path}"
    )
    data = load_yaml(weekly_start_path)
    assert isinstance(data, dict), (
        f"[service] 周常起始日配置应为 dict（空文件或格式错误）: {weekly_start_path}"
    )
    return data


def _dump_weekly_start(data: dict) -> None:
    """写回 weekly_start.yml（覆盖式）。"""
    weekly_start_path = get_weekly_start_yml_path_under_root()
    dump_yaml(weekly_start_path, data)


def _resolve_weekly_timeouts(timeouts: list[int | None]) -> list[int]:
    """把弹窗输入的超时列表规范化：None（空输入）转默认超时，低值（<10）原样保留。

    低值不再 clamp，由 chain_gen 在生成链时按「当天 <10 秒不运行」语义跳过脚本。

    Args:
        timeouts: 7 格输入值，空输入为 None。

    Returns:
        规范化后的 7 格超时值列表。
    """
    return [DEFAULT_RUN_TIMEOUT if v is None else v for v in timeouts]


class WeeklyService:
    """脚本周运行配置服务：weekly_timeouts + weekly_start 读写。

    脚本内部标识为**脚本唯一标识**（get_script_name）：exe 脚本用进程名，
    python/bat 等脚本文件用 display_name。所有方法入参均为此标识。
    """

    def load_all_weekly(self) -> dict:
        """返回 weekly_timeouts.yml 的完整字典（文件随包发布，必存在）。

        key 为脚本唯一标识。
        """
        return _load_weekly()

    def get_weekly_start(self, script_name: str) -> int | None:
        """返回某脚本的周常起始日（1~7），未设置返回 None。

        Args:
            script_name: 脚本唯一标识。

        Returns:
            周常起始日（1~7），未设置返回 None。
        """
        start_map = _load_weekly_start()
        if script_name not in start_map:
            return None
        start_day = start_map[script_name]
        if start_day is None:
            return None
        assert isinstance(start_day, int), (
            f"[service] {script_name} 非法 weekly_start: {start_day!r}（应为整数 1~7）"
        )
        assert 1 <= start_day <= 7, (
            f"[service] {script_name} 非法 weekly_start: {start_day}（应为 1~7）"
        )
        return start_day

    def get_weekly_start_map(self) -> dict:
        """返回 weekly_start.yml 全量（{脚本标识: 1~7}）。"""
        return _load_weekly_start()

    def set_weekly_start(self, script_name: str, start_day: int | None) -> None:
        """持久化某脚本的周常起始日（周几起）到 weekly_start.yml。

        start_day 为 1~7 时写入；为 None 时移除该脚本条目（对应弹窗「不设置」）。

        Args:
            script_name: 脚本唯一标识。
            start_day: 周常起始日（1~7）；None 表示清除。
        """
        if start_day is not None:
            assert 1 <= start_day <= 7, (
                f"[service] 非法 weekly_start: {start_day}（应为 1~7）"
            )
        data = _load_weekly_start()
        if start_day is None:
            if script_name not in data:
                return
            data.pop(script_name, None)
        else:
            data[script_name] = start_day
        _dump_weekly_start(data)

    def save_weekly(self, script_name: str, timeouts: list[int | None]) -> None:
        """保存单个脚本的每周超时（空输入转默认超时；低值原样保留表示当天不运行）。

        Args:
            script_name: 脚本唯一标识。
            timeouts: 7 格超时输入值（必须恰好 7 格），空输入为 None。
        """
        assert len(timeouts) == 7, (
            f"[service] weekly 超时必须为 7 格，实际 {len(timeouts)}"
        )
        weekly = _load_weekly()
        weekly[script_name] = _resolve_weekly_timeouts(timeouts)
        _dump_weekly(weekly)

    def rename_weekly_in_timeouts(
        self, old_script_name: str, new_script_name: str
    ) -> None:
        """脚本标识变更时迁移 weekly_timeouts.yml 中的条目。

        旧条目存在则迁移到新名；不存在则无操作。

        Args:
            old_script_name: 原脚本唯一标识。
            new_script_name: 新脚本唯一标识。
        """
        if old_script_name == new_script_name:
            return
        weekly = _load_weekly()
        old_val = weekly.pop(old_script_name, None)
        if old_val is not None:
            weekly[new_script_name] = old_val
            _dump_weekly(weekly)

    def ensure_weekly_entry(self, script_name: str) -> None:
        """为该脚本在 weekly_timeouts.yml 创建 7 格默认条目（已存在则跳过）。

        Args:
            script_name: 脚本唯一标识。
        """
        weekly = _load_weekly()
        if script_name in weekly:
            return
        weekly[script_name] = [DEFAULT_RUN_TIMEOUT] * 7
        _dump_weekly(weekly)

    def weekly_inputs(self, script_name: str) -> list[int]:
        """返回配置弹窗 7 个超时输入框的初始值。

        Args:
            script_name: 脚本唯一标识。

        Returns:
            长度为 7 的超时值列表（无条目/不足 7 格时用默认超时补齐）。
        """
        weekly_map = _load_weekly()
        entry = weekly_map.get(script_name)
        timeouts = list(entry) if entry else [DEFAULT_RUN_TIMEOUT] * 7
        if len(timeouts) < 7:
            timeouts.extend([DEFAULT_RUN_TIMEOUT] * (7 - len(timeouts)))
        return timeouts[:7]

    def delete_weekly(self, script_name: str) -> None:
        """删除脚本时清理 weekly_timeouts.yml 中该脚本的孤儿条目。

        config.yml 的总配置移除由 ChainService.remove_script 负责；此处仅清理
        脚本级配置（weekly 超时条目），使删除行为完整、无残留。

        Args:
            script_name: 要清理 weekly 条目的脚本唯一标识。
        """
        weekly = _load_weekly()
        if script_name in weekly:
            weekly.pop(script_name)
            _dump_weekly(weekly)

    def check_weekly(self, config_keys: list[str]) -> dict:
        """校验 weekly_timeouts.yml 与 config 脚本条目的一致性。

        Args:
            config_keys: config.yml 中所有脚本的唯一标识列表。

        Returns:
            {"status": "ok"|"inconsistent", "missing_or_short": [...], "orphans": [...]}。
            weekly_timeouts 中不是 7 格条目的脚本标识进 missing_or_short；
            config 已删除的孤儿 key 进 orphans（均为脚本唯一标识）。
        """
        weekly = _load_weekly()

        missing = [name for name in config_keys if len(weekly.get(name) or []) != 7]
        orphans = [name for name in weekly if name not in config_keys]

        return {
            "status": "ok" if not missing and not orphans else "inconsistent",
            "missing_or_short": missing,
            "orphans": orphans,
        }
