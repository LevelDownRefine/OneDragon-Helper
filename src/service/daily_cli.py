"""每日计划的无 Qt 表单和系统任务入口。"""

import logging
import os
import sys
from dataclasses import asdict

from src.service.daily_plan import (
    DailyPlanOptions,
    WindowsDailyTask,
    apply_daily_plan,
    load_daily_plan,
)
from src.service.run_service import InvalidRunRequest, parse_options
from src.service.schedule import is_valid_target_time
from src.utils.utils_shutdown import RUST_CONFIRM_ENV, rust_shutdown_supported

logger = logging.getLogger(__name__)


def _task() -> WindowsDailyTask:
    frontend = ""
    if RUST_CONFIRM_ENV in os.environ:
        frontend = os.environ[RUST_CONFIRM_ENV]
    args = ["daily", "--shutdown-ui", frontend]
    if not getattr(sys, "frozen", False):
        args = ["-m", "src.headless", *args]
    return WindowsDailyTask(entry=(sys.executable, args))


def daily_view() -> dict:
    state = None
    error = None
    try:
        state = asdict(_task().read())
    except OSError as exc:
        logger.warning("[daily] 系统任务读取失败 %s(%s)", type(exc).__name__, exc)
        error = str(exc)
    return {
        "plan": asdict(load_daily_plan()),
        "state": state,
        "state_error": error,
        "supported": sys.platform == "win32",
        "shutdown_supported": rust_shutdown_supported(),
    }


def save_daily(plan: dict) -> None:
    if not isinstance(plan, dict) or set(plan) != {
        "enabled",
        "target_time",
        "run_options",
    }:
        raise InvalidRunRequest("每日计划字段不完整")
    assert "enabled" in plan and "target_time" in plan and "run_options" in plan
    if type(plan["enabled"]) is not bool or not is_valid_target_time(
        plan["target_time"]
    ):
        raise InvalidRunRequest("计划需要布尔开关与有效的 HH:MM 时间")
    if plan["enabled"] and not rust_shutdown_supported():
        raise InvalidRunRequest("启用每日计划需要有效的 Windows Rust 前端")
    options = parse_options(plan["run_options"], require_shutdown_ui=plan["enabled"])
    apply_daily_plan(
        DailyPlanOptions(plan["enabled"], plan["target_time"], options), task=_task()
    )
