"""全局设置的无 Qt 表单边界；保存动作与启动动作分开。"""

from dataclasses import asdict

from src.service.daily_plan import load_daily_plan
from src.service.run_service import InvalidRunRequest, parse_options
from src.service.schedule import (
    MAX_STARTUP_DELAY_SECONDS,
    StartupOptions,
    apply_run_options,
    apply_startup_options,
    load_run_options,
    load_startup_options,
)
from src.utils.utils_shutdown import rust_shutdown_supported


def settings_view() -> dict:
    return {
        "startup": asdict(load_startup_options()),
        "daily_enabled": load_daily_plan().enabled,
        "run_options": asdict(load_run_options()),
        "shutdown_supported": rust_shutdown_supported(),
    }


def save_startup(options: dict) -> None:
    if not isinstance(options, dict) or set(options) != {"enabled", "delay_seconds"}:
        raise InvalidRunRequest("启动选项字段无效")
    assert "enabled" in options and "delay_seconds" in options
    if (
        type(options["enabled"]) is not bool
        or type(options["delay_seconds"]) is not int
        or not 1 <= options["delay_seconds"] <= MAX_STARTUP_DELAY_SECONDS
    ):
        raise InvalidRunRequest("自动启动需要布尔开关与 1～3600 秒倒计时")
    apply_startup_options(StartupOptions(**options))


def save_run_options(options: dict) -> None:
    apply_run_options(parse_options(options))
