"""周常相关工具：日期数学 + 运行期参数读写（无 Qt 依赖）。

两类职责：
- 日期数学：``next_target_datetime`` / ``get_week_num`` / ``is_weekly_start_reached``（周几判定）；
- 运行期参数读写：``weekly.yml`` 内的 ``weekly_start``（周几起）+ ``weekly_timeouts``（每周超时）两段。

不含周本声明——各游戏「有哪些周常、可选哪些副本」由 src.config.dungeon_config 模块函数读
weekly_list.yml 提供；本模块只管「周几起 / 每天超时多久」这类运行期参数。

``weekly.yml`` 是单一文件、内含两大段；写回任一段时均保留另一段（读全量→改一段→写全量）。

脚本标识统一用脚本唯一标识 script_name（exe 为进程名、脚本文件为 display_name）。
"""

import logging
from datetime import datetime, timedelta

from src.utils import get_weekly_yml_path_under_root
from src.utils.utils_sub_config import DEFAULT_RUN_TIMEOUT, get_script_name
from src.utils.utils_yaml import dump_yaml, load_yaml_optional

logger = logging.getLogger(__name__)


# ---- 日期数学 ----


def next_target_datetime(target_time: str, now: datetime | None = None) -> datetime:
    """返回下一个等于 target_time 的时刻：今天未到取今天，已过取明天（跨午夜）。

    Args:
        target_time: ``"HH:MM"`` 形式的目标时刻。
        now: 基准时间，默认当前时间（可注入以便测试）。

    Returns:
        下一个 ``target_time`` 对应的 ``datetime``。
    """
    hours, minutes = (int(x) for x in target_time.split(":"))
    now = now or datetime.now()
    candidate = now.replace(hour=hours, minute=minutes, second=0, microsecond=0)
    if now < candidate:
        return candidate
    return candidate + timedelta(days=1)


def get_week_num() -> int:
    """返回星期数字：0周一 ~ 6周日（凌晨 4 点为界，4 点前归前一天）。

    周常「周几以后开始执行」与 weekly_timeouts 的「当天」判定共用此规则，
    各脚本统一以凌晨 4 点为新一天起点。
    """
    return (datetime.now() - timedelta(hours=4)).weekday()


def is_weekly_start_reached(start_day: int) -> bool:
    """判断今天是否已到周常起始日（今天周几 >= 起始日）。

    Args:
        start_day: 周常起始日（1=周一 ~ 7=周日）。

    Returns:
        True 表示今天起可以执行周常。
    """
    assert 1 <= start_day <= 7, f"[utils_weekly] 非法周常起始日: {start_day}"
    return get_week_num() + 1 >= start_day


# ---- weekly.yml 的 weekly_start 段 / weekly.yml 的 weekly_timeouts 段 读写 ----


def _load_weekly_file() -> dict:
    """读取 weekly.yml 全量（含 weekly_start / weekly_timeouts 两段）。

    weekly.yml 是运行期生成的用户文件（由 config_workflow 从 weekly.example.yml 生成），
    CI 干净 checkout 或单测直接走 schedule_run 路径时可能尚未生成；与 schedule.yml 一致，
    缺失即回退空结构而非 assert 崩溃。文件存在却为空 / 非 dict 仍 assert——损坏属编程错误。

    setdefault 两段空结构：缺失文件或某段缺失时，写回不会把整个段丢掉（等价空 {}）。
    """
    weekly_path = get_weekly_yml_path_under_root()
    data = load_yaml_optional(weekly_path)
    data.setdefault("weekly_start", {})
    data.setdefault("weekly_timeouts", {})
    return data


def _dump_weekly_file(data: dict) -> None:
    """写回 weekly.yml 全量（含 weekly_start / weekly_timeouts 两段）。"""
    weekly_path = get_weekly_yml_path_under_root()
    dump_yaml(weekly_path, data)


def _load_weekly() -> dict:
    """读取 weekly.yml 的 weekly_timeouts 段（各脚本每周 7 格超时）。

    文件缺失段时回退空 dict，由调用方（save_weekly / ensure_weekly_entry 等）按需建条目。
    """
    return _load_weekly_file().get("weekly_timeouts", {}) or {}


def _dump_weekly(timeouts_map: dict) -> None:
    """写回 weekly.yml 的 weekly_timeouts 段，保留 weekly_start 段。"""
    data = _load_weekly_file()
    data["weekly_timeouts"] = timeouts_map
    _dump_weekly_file(data)


def _load_weekly_start() -> dict:
    """读取 weekly.yml 的 weekly_start 段（各脚本周常起始日，{script_name: 1~7}）。

    文件缺失段时回退空 dict。
    """
    return _load_weekly_file().get("weekly_start", {}) or {}


def _dump_weekly_start(start_map: dict) -> None:
    """写回 weekly.yml 的 weekly_start 段，保留 weekly_timeouts 段。"""
    data = _load_weekly_file()
    data["weekly_start"] = start_map
    _dump_weekly_file(data)


def _resolve_weekly_timeouts(timeouts: list[int | None]) -> list[int]:
    """把弹窗输入的超时列表规范化：None（空输入）转默认超时，低值（<10）原样保留。

    低值不再 clamp，由 chain_gen 在生成链时按「当天 <10 秒不运行」语义跳过脚本。

    Args:
        timeouts: 7 格输入值，空输入为 None。

    Returns:
        规范化后的 7 格超时值列表。
    """
    return [DEFAULT_RUN_TIMEOUT if v is None else v for v in timeouts]


def load_all_weekly() -> dict:
    """返回 weekly.yml 的 weekly_timeouts 段完整字典（文件随包发布，必存在）。

    key 为脚本唯一标识。
    """
    return _load_weekly()


def get_weekly_start(script_name: str) -> int | None:
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
        f"[utils_weekly] {script_name} 非法 weekly_start: {start_day!r}（应为整数 1~7）"
    )
    assert 1 <= start_day <= 7, (
        f"[utils_weekly] {script_name} 非法 weekly_start: {start_day}（应为 1~7）"
    )
    return start_day


def get_weekly_start_map() -> dict:
    """返回 weekly.yml 的 weekly_start 段全量（{脚本标识: 1~7}）。"""
    return _load_weekly_start()


def set_weekly_start(script_name: str, start_day: int | None) -> None:
    """持久化某脚本的周常起始日（周几起）到 weekly.yml 的 weekly_start 段。

    start_day 为 1~7 时写入；为 None 时移除该脚本条目（对应弹窗「不设置」）。

    Args:
        script_name: 脚本唯一标识。
        start_day: 周常起始日（1~7）；None 表示清除。
    """
    if start_day is not None:
        assert 1 <= start_day <= 7, (
            f"[utils_weekly] 非法 weekly_start: {start_day}（应为 1~7）"
        )
    data = _load_weekly_start()
    if start_day is None:
        if script_name not in data:
            return
        data.pop(script_name, None)
    else:
        data[script_name] = start_day
    _dump_weekly_start(data)


def save_weekly(script_name: str, timeouts: list[int | None]) -> None:
    """保存单个脚本的每周超时（空输入转默认超时；低值原样保留表示当天不运行）。

    Args:
        script_name: 脚本唯一标识。
        timeouts: 7 格超时输入值（必须恰好 7 格），空输入为 None。
    """
    assert len(timeouts) == 7, (
        f"[utils_weekly] weekly 超时必须为 7 格，实际 {len(timeouts)}"
    )
    weekly = _load_weekly()
    weekly[script_name] = _resolve_weekly_timeouts(timeouts)
    _dump_weekly(weekly)


def rename_weekly_in_timeouts(old_script_name: str, new_script_name: str) -> None:
    """脚本标识变更时迁移 weekly.yml 的 weekly_timeouts 段 中的条目。

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


def ensure_weekly_entry(script_name: str) -> None:
    """为该脚本在 weekly.yml 的 weekly_timeouts 段 创建 7 格默认条目（已存在则跳过）。

    Args:
        script_name: 脚本唯一标识。
    """
    weekly = _load_weekly()
    if script_name in weekly:
        return
    weekly[script_name] = [DEFAULT_RUN_TIMEOUT] * 7
    _dump_weekly(weekly)


def weekly_inputs(script_name: str) -> list[int]:
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


def check_weekly(config: dict) -> dict:
    """校验 weekly.yml 的 weekly_timeouts 段与 config.yml 脚本条目的一致性。

    Args:
        config: config.yml 完整数据（含 script_list）。

    Returns:
        {"status": "ok"|"inconsistent", "missing_or_short": [...], "orphans": [...]}。
        weekly_timeouts 中不是 7 格条目的脚本标识进 missing_or_short；
        config 已删除的孤儿 key 进 orphans（均为脚本唯一标识）。
    """
    config_keys = [get_script_name(s) for s in config.get("script_list", [])]
    weekly = _load_weekly()

    missing = [name for name in config_keys if len(weekly.get(name) or []) != 7]
    orphans = [name for name in weekly if name not in config_keys]

    return {
        "status": "ok" if not missing and not orphans else "inconsistent",
        "missing_or_short": missing,
        "orphans": orphans,
    }


def delete_weekly(script_name: str) -> None:
    """删除脚本时清理 weekly.yml 的 weekly_timeouts 段 中该脚本的孤儿条目。

    Args:
        script_name: 要清理 weekly 条目的脚本唯一标识。
    """
    weekly = _load_weekly()
    if script_name in weekly:
        weekly.pop(script_name)
        _dump_weekly(weekly)
