"""无 Qt 的手动批量确认与独立调度入口。"""

import json
import os
import sys
from dataclasses import asdict, fields

from src.service import chain_service
from src.service.schedule import (
    RunOptions,
    _dump_run_options,
    apply_run_options,
    load_run_options,
)
from src.utils import get_root_dir
from src.utils.utils_config import load_config
from src.utils.utils_runner import collect_invalid_script_messages
from src.utils.utils_shutdown import RUST_CONFIRM_ENV, rust_shutdown_supported
from src.utils.utils_sub_config import get_script_name


class InvalidRunRequest(ValueError):
    """写入/启动前的可恢复运行请求错误。"""


def selected_scripts(script_names: list[str]) -> list[dict]:
    """只接受当前列表中的非空、无重复选择。"""
    if (
        not isinstance(script_names, list)
        or not script_names
        or any(not isinstance(name, str) or not name for name in script_names)
        or len(set(script_names)) != len(script_names)
    ):
        raise InvalidRunRequest("请选择要手动运行的脚本")
    config = load_config()
    assert "script_list" in config
    selected = [
        script
        for script in config["script_list"]
        if get_script_name(script) in script_names
    ]
    if {get_script_name(script) for script in selected} != set(script_names):
        raise InvalidRunRequest("脚本列表已变化，请刷新后重新选择")
    return selected


def parse_options(values: dict, *, require_shutdown_ui: bool = True) -> RunOptions:
    """按现有 RunOptions schema 验证 JSON 表单，不回显授权码。"""
    if not isinstance(values, dict) or set(values) != {
        field.name for field in fields(RunOptions)
    }:
        raise InvalidRunRequest("运行选项字段不完整或包含未知字段")
    defaults = asdict(RunOptions())
    for key, default in defaults.items():
        assert key in values
        if type(values[key]) is not type(default):
            raise InvalidRunRequest(f"运行选项 {key} 类型无效")
    options = RunOptions(
        **{
            key: value.strip() if isinstance(value, str) else value
            for key, value in values.items()
        }
    )
    if not 0 <= options.shutdown_delay <= 86400:
        raise InvalidRunRequest("关机延迟须为 0～86400 秒")
    if (
        require_shutdown_ui
        and options.shutdown_enabled
        and not rust_shutdown_supported()
    ):
        raise InvalidRunRequest("Rust 关机确认入口不可用，请关闭自动关机或重新启动前端")
    if options.smtp_port and (
        not options.smtp_port.isdecimal() or not 1 <= int(options.smtp_port) <= 65535
    ):
        raise InvalidRunRequest("SMTP 端口须为 1～65535")
    if options.auth_code and not options.email:
        raise InvalidRunRequest("填写授权码时请同时填写邮箱")
    return options


def run_view(script_names: list[str]) -> dict:
    """显示当前配置的运行选项与将跳过的脚本。"""
    scripts = selected_scripts(script_names)
    return {
        "script_names": [get_script_name(script) for script in scripts],
        "invalid": [
            {"name": name, "reason": reason}
            for name, reason in collect_invalid_script_messages(scripts)
        ],
        "options": asdict(load_run_options()),
        "shutdown_supported": rust_shutdown_supported(),
    }


def prepare_run(script_names: list[str], options: dict, confirm_invalid: bool) -> dict:
    """保存确认后的选项，返回独立运行进程的命令及 stdin 载荷。"""
    scripts = selected_scripts(script_names)
    parsed = parse_options(options)
    if type(confirm_invalid) is not bool:
        raise InvalidRunRequest("运行确认格式无效")
    if collect_invalid_script_messages(scripts) and not confirm_invalid:
        raise InvalidRunRequest("请先确认配置不合法的脚本将在运行时跳过")
    apply_run_options(parsed)
    return _run_target(script_names, load_run_options())


def saved_run(script_names: list[str]) -> dict:
    """自动启动只读取上次选项，不再次保存；无效脚本沿用调度器跳过语义。"""
    selected_scripts(script_names)
    options = parse_options(asdict(load_run_options()))
    return _run_target(script_names, options)


def _run_target(script_names: list[str], options: RunOptions) -> dict:
    command = (
        [sys.executable]
        if getattr(sys, "frozen", False)
        else [sys.executable, "-m", "src.headless"]
    )
    payload = {"script_names": script_names, "options": asdict(options)}
    return {
        "kind": "command",
        "program": command[0],
        "args": [*command[1:], "run"],
        "cwd": get_root_dir(),
        "env": (
            {RUST_CONFIRM_ENV: os.environ[RUST_CONFIRM_ENV]}
            if RUST_CONFIRM_ENV in os.environ
            else {}
        ),
        "console": True,
        "input": json.dumps(payload, ensure_ascii=False),
    }


def run_batch(script_names: list[str], options: dict) -> None:
    """独立进程持有运行锁，复用原链编排；此函数不在 stdio 服务中调用。"""
    scripts = selected_scripts(script_names)
    parsed = parse_options(options)
    blocks = _dump_run_options(parsed)
    assert "notify" in blocks
    chain_service.schedule_run(
        {get_script_name(script) for script in scripts},
        "now",
        mute=parsed.mute_enabled,
        unmute=parsed.unmute_enabled,
        shutdown_delay=(parsed.shutdown_delay if parsed.shutdown_enabled else None),
        close_running=parsed.close_running_enabled,
        rerun_enabled=parsed.rerun_enabled,
        smtp_config=blocks["notify"],
    )
