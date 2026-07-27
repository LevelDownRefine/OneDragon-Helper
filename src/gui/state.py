"""UI 状态持久化（config/gui_state.json）与星期计算。"""
import json
import os
from datetime import datetime, timedelta

from src.utils import get_root_dir, safe_path_join

_STATE_FILE = safe_path_join(get_root_dir(), "config", "gui_state.json")


def load_ui_state() -> dict:
    """读取上次保存的 UI 状态"""
    if os.path.exists(_STATE_FILE):
        with open(_STATE_FILE, encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_ui_state(state: dict):
    """保存 UI 状态"""
    with open(_STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def get_week_num() -> int:
    """返回星期数字：0周一 ~ 6周日。

    以凌晨 4 点为界：4 点前归前一天，例如周一 03:00 仍按上周日(6)计。
    """
    return (datetime.now() - timedelta(hours=4)).weekday()


DEFAULT_RUN_TIMEOUT = 3600
"""脚本运行默认超时秒数。当 weekly_timeouts.yml 无条目或不足 7 格时作为 fallback。"""


def apply_weekly_timeout(script: dict, weekly_timeouts: dict) -> None:
    """根据 weekly_timeouts.yml 就地设置 script['run_timeout_seconds']。

    - 有完整 7 格 → 取当天值，且不低于 10（避免 0 秒杀脚本）。
    - 无条目 / 不足 7 格 → fallback 到 DEFAULT_RUN_TIMEOUT。
    """
    assert 'display_name' in script, "[state] script_list 条目缺少 display_name 字段"
    timeouts = weekly_timeouts.get(script['display_name'])
    if timeouts and len(timeouts) == 7:
        script['run_timeout_seconds'] = max(timeouts[get_week_num()], 10)
    else:
        script['run_timeout_seconds'] = DEFAULT_RUN_TIMEOUT
