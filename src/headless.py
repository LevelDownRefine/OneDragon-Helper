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
    "settings.view": ("settings_view", (), ()),
    "startup.view": ("settings_view", (), ()),
    "plan.view": ("daily_plan_view", (), ()),
    "plan.save": ("save_daily_plan", ("plan",), ()),
    "settings.startup_save": ("save_startup_settings", ("options",), ()),
    "settings.run_save": ("save_run_settings", ("options",), ()),
    "run.saved": ("saved_run", ("script_names",), ()),
    "run.view": ("run_view", ("script_names",), ()),
    "run.prepare": ("prepare_run", ("script_names", "options", "confirm_invalid"), ()),
    "script.view": ("script_view", ("script_name",), ()),
    "script.target": ("resolve_script_target", ("script_name", "target"), ()),
    "script.icon_path": ("game_icon_path", ("script_name",), ()),
    "script.launch_target": ("resolve_launch_target", ("script_name", "target"), ()),
    "script.edit_view": ("script_edit_view", ("script_name",), ()),
    "script.add": ("add_script_path", ("file_path",), ()),
    "script.remove": ("remove_script_entry", ("script_name",), ()),
    "script.reorder": ("reorder_scripts", ("script_names",), ()),
    "script.edit_save": (
        "save_script_edit",
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


def handle_request(service, request) -> dict:
    """串行分发，协议输入先校验；业务异常保留诊断并返回明确失败。"""
    from src.service.background_job import InvalidBackgroundJob
    from src.service.run_service import InvalidRunRequest
    from src.service.script_edit import InvalidScriptEdit
    from src.service.script_list import DuplicateScript, InvalidScriptList
    from src.service.task_service import InvalidTaskSelection

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
        # 参数值原样转发；取值校验和空操作语义由原 service 接口负责。
        mutating = method not in (
            "app.snapshot",
            "job.poll",
            "settings.view",
            "startup.view",
            "plan.view",
            "run.saved",
            "run.view",
            "script.view",
            "script.target",
            "script.icon_path",
            "script.launch_target",
            "script.edit_view",
        )
        # 保护协议 stdout，包括适配器或第三方库的意外输出。
        with redirect_stdout(sys.stderr):
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
        InvalidScriptEdit,
        InvalidScriptList,
        InvalidRunRequest,
        InvalidBackgroundJob,
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
                    and request["method"] != "job.poll"
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
    if method in {"backup.start", "restore.start", "job.poll"}:
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
                service = AppService()
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
        if args.command in ("run", "daily"):
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
