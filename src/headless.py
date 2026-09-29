"""无 Qt 的任务卡 CLI：一次性 call 或随 GUI 启动的 serve --stdio。"""

import argparse
import json
import logging
import os
import sys
from contextlib import contextmanager, nullcontext, redirect_stderr, redirect_stdout
from pathlib import Path

logger = logging.getLogger(__name__)
PROTOCOL_VERSION = 1
# 首期只开放短配置操作；长任务必须另行设计进度与取消协议。
METHODS = {
    "app.snapshot": ("app_snapshot", (), ()),
    "backup.start": ("start_backup", (), ()),
    "restore.start": ("start_restore", ("zip_path", "confirmed"), ()),
    "job.poll": ("poll_job", ("job_id",), ()),
    "job.cancel": ("cancel_job", ("job_id",), ()),
    "update.view": ("update_view", (), ()),
    "update.check": ("start_update_check", (), ()),
    "update.download": ("start_update_download", (), ()),
    "update.install": ("start_update_install", (), ()),
    "settings.view": ("settings_view", (), ()),
    "startup.view": ("settings_view", (), ()),
    "plan.view": ("daily_plan_view", (), ()),
    "plan.save": ("apply_daily_plan", ("plan",), ()),
    "settings.startup_save": ("apply_startup_options", ("options",), ()),
    "settings.run_save": ("apply_run_options", ("options",), ()),
    "run.saved": ("saved_run", ("script_names",), ()),
    "run.view": ("run_view", ("script_names",), ()),
    "run.prepare": ("prepare_run", ("script_names", "options", "confirm_invalid"), ()),
    "script.view": ("script_view", ("script_name",), ()),
    "script.target": ("resolve_script_target", ("script_name", "target"), ()),
    "script.icon_path": ("game_icon_path", ("script_name",), ()),
    "wallpaper.current": ("wallpaper_view", ("script_name",), ()),
    "wallpaper.view": ("wallpaper_view", ("script_name",), ()),
    "wallpaper.set": ("set_wallpaper", ("script_name", "file_path"), ()),
    "wallpaper.cache": (
        "save_wallpaper_cache",
        ("script_name", "token", "jpeg_base64"),
        (),
    ),
    "script.launch_target": ("resolve_launch_target", ("script_name", "target"), ()),
    "script.edit_view": ("script_edit_view", ("script_name",), ()),
    "script.add": ("add_script", ("file_path",), ()),
    "script.remove": ("remove_script", ("script_name",), ()),
    "script.reorder": ("reorder_scripts", ("script_names",), ()),
    "script.edit_save": (
        "update_script",
        ("script_name", "display_name", "config_patch", "weekly_timeouts", "switches"),
        (),
    ),
    "daily.select": (
        "select_daily",
        ("script_name",),
        ("daily_name", "task_name", "sequence"),
    ),
    "daily.enable": ("enable_daily", ("script_name", "daily_name", "enabled"), ()),
    "weekly.select": ("select_weekly", ("script_name", "weekly_name", "task_name"), ()),
    "weekly.start": ("start_weekly", ("script_name", "weekly_name", "start_day"), ()),
}


class ProtocolError(ValueError):
    """可恢复的请求格式或参数错误。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _error(request_id, code: str, message: str, *, refresh_required=False) -> dict:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "id": request_id,
        "error": {
            "code": code,
            "message": message,
            "refresh_required": refresh_required,
        },
    }


def _reject_constant(value: str):
    raise ValueError(f"JSON 不支持常量 {value}")


def _unique_object(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"JSON 字段重复: {key}")
        result[key] = value
    return result


def _parse_json(payload: str):
    return json.loads(
        payload, parse_constant=_reject_constant, object_pairs_hook=_unique_object
    )


def _daily_task():
    """计划任务只保存 CLI 入口与前端路径，每次触发读取最新配置。"""
    from src.service.daily_plan import WindowsDailyTask
    from src.utils.utils_shutdown import RUST_CONFIRM_ENV

    frontend = ""
    if RUST_CONFIRM_ENV in os.environ:
        frontend = os.environ[RUST_CONFIRM_ENV]
    args = ["daily", "--shutdown-ui", frontend]
    if not getattr(sys, "frozen", False):
        args = ["-m", "src.headless", *args]
    return WindowsDailyTask(entry=(sys.executable, args))


def handle_request(service, request) -> dict:
    """串行分发，协议输入先校验；业务异常保留诊断并返回明确失败。"""
    from src.service.background_job import InvalidBackgroundJob
    from src.service.daily_plan import DailyPlanOptions
    from src.service.run_service import InvalidRunRequest, parse_options
    from src.service.schedule import (
        MAX_STARTUP_DELAY_SECONDS,
        StartupOptions,
        is_valid_target_time,
    )
    from src.service.script_service import DuplicateScript, InvalidScript, ScriptEdit
    from src.service.task_service import InvalidTaskSelection
    from src.service.wallpaper_service import InvalidWallpaper
    from src.utils.utils_shutdown import rust_shutdown_supported

    request_id = None
    mutating = False
    try:
        if not isinstance(request, dict):
            raise ProtocolError("invalid_request", "请求必须是 JSON 对象")
        if "id" in request and type(request["id"]) in (str, int):
            request_id = request["id"]
        if set(request) != {"protocol_version", "id", "method", "params"}:
            raise ProtocolError(
                "invalid_request", "请求需要且仅接受 protocol_version/id/method/params"
            )
        assert all(
            key in request for key in ("protocol_version", "id", "method", "params")
        )
        if (
            type(request["protocol_version"]) is not int
            or request["protocol_version"] != PROTOCOL_VERSION
        ):
            raise ProtocolError("unsupported_version", "仅支持 protocol_version=1")
        if request_id is None or request_id == "":
            raise ProtocolError("invalid_request", "id 必须是非空字符串或整数")
        method, params = request["method"], request["params"]
        if not isinstance(method, str) or method not in METHODS:
            raise ProtocolError("method_not_found", "未开放此方法")
        assert method in METHODS
        attribute, required, optional = METHODS[method]
        if not isinstance(params, dict):
            raise ProtocolError("invalid_params", "params 必须是 JSON 对象")
        if not set(required) <= set(params) or set(params) - set(required + optional):
            raise ProtocolError("invalid_params", "参数字段缺失或包含不支持的字段")
        # 传输层校验外部参数并转换数据；业务读写统一经 service。
        mutating = method not in (
            "app.snapshot",
            "job.poll",
            "update.view",
            "settings.view",
            "startup.view",
            "plan.view",
            "run.saved",
            "run.view",
            "script.view",
            "script.target",
            "script.icon_path",
            "wallpaper.current",
            "wallpaper.view",
            "script.launch_target",
            "script.edit_view",
        )
        # 保护协议 stdout，包括适配器或第三方库的意外输出。
        with redirect_stdout(sys.stderr):
            if method == "script.edit_save":
                result = {"script_name": service.update_script(ScriptEdit(**params))}
            elif method in {"settings.view", "startup.view"}:
                result = service.settings_view()
                result["shutdown_supported"] = rust_shutdown_supported()
            elif method == "settings.startup_save":
                assert "options" in params
                options = params["options"]
                if not isinstance(options, dict) or set(options) != {
                    "enabled",
                    "delay_seconds",
                }:
                    raise ProtocolError("invalid_params", "启动选项字段无效")
                assert "enabled" in options and "delay_seconds" in options
                if (
                    type(options["enabled"]) is not bool
                    or type(options["delay_seconds"]) is not int
                    or not 1 <= options["delay_seconds"] <= MAX_STARTUP_DELAY_SECONDS
                ):
                    raise ProtocolError(
                        "invalid_params", "自动启动需要布尔开关与 1～3600 秒倒计时"
                    )
                result = service.apply_startup_options(StartupOptions(**options))
            elif method == "settings.run_save":
                assert "options" in params
                result = service.apply_run_options(parse_options(params["options"]))
            elif method == "plan.view":
                result = service.daily_plan_view(task=_daily_task())
                result["shutdown_supported"] = rust_shutdown_supported()
            elif method == "plan.save":
                assert "plan" in params
                plan = params["plan"]
                if not isinstance(plan, dict) or set(plan) != {
                    "enabled",
                    "target_time",
                    "run_options",
                }:
                    raise ProtocolError("invalid_params", "每日计划字段不完整")
                assert all(
                    key in plan for key in ("enabled", "target_time", "run_options")
                )
                if type(plan["enabled"]) is not bool or not is_valid_target_time(
                    plan["target_time"]
                ):
                    raise ProtocolError(
                        "invalid_params", "计划需要布尔开关与有效的 HH:MM 时间"
                    )
                if plan["enabled"] and not rust_shutdown_supported():
                    raise ProtocolError(
                        "invalid_params", "启用每日计划需要有效的 Windows Rust 前端"
                    )
                options = parse_options(
                    plan["run_options"], require_shutdown_ui=plan["enabled"]
                )
                result = service.apply_daily_plan(
                    DailyPlanOptions(plan["enabled"], plan["target_time"], options),
                    task=_daily_task(),
                )
            else:
                result = getattr(service, attribute)(**params)
        return {
            "protocol_version": PROTOCOL_VERSION,
            "id": request_id,
            "result": result,
        }
    except ProtocolError as exc:
        return _error(request_id, exc.code, str(exc))
    except DuplicateScript as exc:
        return _error(request_id, "duplicate_script", str(exc))
    except (
        InvalidTaskSelection,
        InvalidScript,
        InvalidRunRequest,
        InvalidBackgroundJob,
        InvalidWallpaper,
    ) as exc:
        return _error(request_id, "invalid_params", str(exc))
    except Exception:  # noqa: BLE001 -- IPC 边界必须回复；写入可能已部分完成。
        logger.exception("任务卡请求失败，id=%r", request_id)
        return _error(
            request_id,
            "operation_failed",
            "操作失败，详情见 stderr 或助手日志",
            refresh_required=mutating,
        )


def _emit(response: dict, output=None) -> None:
    output = sys.stdout if output is None else output
    output.write(json.dumps(response, ensure_ascii=False, allow_nan=False) + "\n")
    output.flush()


def _serve(service) -> int:
    output = sys.stdout
    # 后台线程也可能输出诊断；整个会话的业务 stdout 指向 stderr。
    with redirect_stdout(sys.stderr):
        try:
            for line in sys.stdin:
                try:
                    request = _parse_json(line)
                except ValueError as exc:
                    _emit(_error(None, "parse_error", str(exc)), output)
                    continue
                if (
                    service.background.running
                    and isinstance(request, dict)
                    and "method" in request
                    and request["method"] not in {"job.poll", "job.cancel"}
                ):
                    request_id = None
                    if "id" in request and type(request["id"]) in (str, int):
                        request_id = request["id"]
                    _emit(
                        _error(
                            request_id, "operation_busy", "后台操作进行中，请等待完成"
                        ),
                        output,
                    )
                    continue
                _emit(handle_request(service, request), output)
        finally:
            service.close()
    return 0


def _call(service, method: str) -> int:
    if method in {
        "backup.start",
        "restore.start",
        "job.poll",
        "job.cancel",
        "update.check",
        "update.download",
        "update.install",
    }:
        _emit(_error(1, "invalid_request", "后台任务仅支持 serve --stdio 会话"))
        return 1
    try:
        params = _parse_json(sys.stdin.read())
    except ValueError as exc:
        _emit(_error(1, "parse_error", str(exc)))
        return 1
    response = handle_request(
        service,
        {
            "protocol_version": PROTOCOL_VERSION,
            "id": 1,
            "method": method,
            "params": params,
        },
    )
    _emit(response)
    return 1 if "error" in response else 0


def main(argv: list[str] | None = None) -> int:
    """更新闸门先于配置初始化；整个 stdio 会话持有运行共享锁。"""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "call", help="从 stdin 读取参数对象，输出一个响应"
    ).add_argument("method")
    commands.add_parser("serve", help="逐行处理 JSON 请求，EOF 退出").add_argument(
        "--stdio", action="store_true", required=True
    )
    commands.add_parser(
        "run", help="从 stdin 读取一次运行配置，在独立进程中执行批量任务"
    )
    commands.add_parser(
        "daily", help="系统每日计划入口，读取独立计划配置"
    ).add_argument("--shutdown-ui", required=True)
    commands.add_parser("legacy", help="原助手 CLI 参数透传").add_argument(
        "arguments", nargs=argparse.REMAINDER
    )
    args = parser.parse_args(argv)
    output = (
        _console_output()
        if args.command in ("run", "daily") and os.name == "nt"
        else nullcontext()
    )
    with output:
        return _run_command(args)


@contextmanager
def _console_output():
    """将独立运行进程的输出绑定到新控制台，stdin 留给 JSON 载荷。"""
    with (
        open("CONOUT$", "w", encoding="utf-8", buffering=1) as console,
        redirect_stdout(console),
        redirect_stderr(console),
    ):
        yield


def _run_command(args: argparse.Namespace) -> int:
    """在同一租约边界内初始化并执行一次入口。"""
    from src.update.runtime import application_lease
    from src.utils import get_root_dir

    try:
        with application_lease(Path(get_root_dir())):
            with redirect_stdout(sys.stderr):
                from src.config.generate_config import config_workflow
                from src.service.app_service import AppService
                from src.utils.utils_logger import install_crash_hooks, setup_logging

                setup_logging()
                install_crash_hooks()
                config_workflow()
                service = AppService(frontend="rust")
            if args.command == "legacy":
                from src.cli import build_parser, run_cli

                arguments = args.arguments
                if arguments and arguments[0] == "--":
                    arguments = arguments[1:]
                result = run_cli(build_parser().parse_args(arguments))
                if result is None:
                    raise ValueError("请指定 CLI 操作；图形界面由 Rust 前端启动")
                return result
            if args.command == "daily":
                from src.utils.utils_shutdown import RUST_CONFIRM_ENV

                os.environ[RUST_CONFIRM_ENV] = args.shutdown_ui
                service.run_daily_plan()
                return 0
            if args.command == "run":
                payload = _parse_json(sys.stdin.read())
                if not isinstance(payload, dict) or set(payload) != {
                    "script_names",
                    "options",
                }:
                    raise ValueError("运行载荷字段无效")
                assert "script_names" in payload and "options" in payload
                service.run_batch(payload["script_names"], payload["options"])
                return 0
            return (
                _serve(service)
                if args.command == "serve"
                else _call(service, args.method)
            )
    except BrokenPipeError:
        # 父进程已关闭管道；用 _exit 避免解释器再次 flush 同一断开的 stdout。
        os._exit(0)
    except Exception:  # noqa: BLE001 -- 入口失败须输出启动错误并释放租约。
        logger.exception("无 GUI CLI 启动或传输失败")
        if args.command in ("run", "daily", "legacy"):
            return 2
        _emit(
            _error(
                None,
                "session_failed",
                "会话无法继续，详情见 stderr 或助手日志",
                refresh_required=True,
            )
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
