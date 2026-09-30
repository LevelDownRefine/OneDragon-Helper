"""无 Qt 助手入口；JSON-RPC 2.0 分发由 jsonrpcserver 处理。"""

import argparse
import json
import logging
import os
import sys
from contextlib import contextmanager, nullcontext, redirect_stderr, redirect_stdout
from dataclasses import asdict, fields
from functools import wraps
from pathlib import Path

from jsonrpcserver import Error, Success, dispatch_to_serializable

logger = logging.getLogger(__name__)


class InvalidParams(ValueError):
    """助手表单的字段类型或取值无效。"""


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


def _parse_run_options(values: dict, *, require_shutdown_ui: bool = True):
    """将完整 JSON 表单转换为 RunOptions，检查类型、范围和前端能力。"""
    from src.service.schedule import RunOptions
    from src.utils.utils_shutdown import shutdown_ui_supported

    if not isinstance(values, dict) or set(values) != {
        field.name for field in fields(RunOptions)
    }:
        raise InvalidParams("运行选项字段不完整或包含未知字段")
    for key, default in asdict(RunOptions()).items():
        assert key in values
        if type(values[key]) is not type(default):
            raise InvalidParams(f"运行选项 {key} 类型无效")
    options = RunOptions(
        **{
            key: value.strip() if isinstance(value, str) else value
            for key, value in values.items()
        }
    )
    if not 0 <= options.shutdown_delay <= 86400:
        raise InvalidParams("关机延迟须为 0～86400 秒")
    if require_shutdown_ui and options.shutdown_enabled and not shutdown_ui_supported():
        raise InvalidParams("关机确认入口不可用，请关闭自动关机或重新启动前端")
    if options.smtp_port and (
        not options.smtp_port.isdecimal() or not 1 <= int(options.smtp_port) <= 65535
    ):
        raise InvalidParams("SMTP 端口须为 1～65535")
    if options.auth_code and not options.email:
        raise InvalidParams("填写授权码时请同时填写邮箱")
    return options


def _run_target(script_names: list[str], options) -> dict:
    """构造独立 CLI 运行命令，脚本名单和选项只经 stdin 传递。"""
    from src.utils import get_root_dir
    from src.utils.utils_shutdown import SHUTDOWN_UI_ARGS_ENV, SHUTDOWN_UI_ENV

    args = ["run"]
    if not getattr(sys, "frozen", False):
        args = ["-m", "src.headless", *args]
    return {
        "kind": "command",
        "program": sys.executable,
        "args": args,
        "cwd": (
            get_root_dir()
            if getattr(sys, "frozen", False)
            else os.path.join(get_root_dir(), "python-backend")
        ),
        "env": (
            {
                key: os.environ[key]
                for key in (SHUTDOWN_UI_ENV, SHUTDOWN_UI_ARGS_ENV)
                if key in os.environ
            }
            if SHUTDOWN_UI_ENV in os.environ
            else {}
        ),
        "console": True,
        "input": json.dumps(
            {"script_names": script_names, "options": asdict(options)},
            ensure_ascii=False,
        ),
    }


def _daily_task():
    """计划任务只保存 CLI 入口与前端路径，每次触发读取最新配置。"""
    from src.service.daily_plan import WindowsDailyTask
    from src.utils.utils_shutdown import SHUTDOWN_UI_ARGS_ENV, SHUTDOWN_UI_ENV

    frontend = ""
    if SHUTDOWN_UI_ENV in os.environ:
        frontend = os.environ[SHUTDOWN_UI_ENV]
    args = ["daily", "--shutdown-ui", frontend]
    if SHUTDOWN_UI_ARGS_ENV in os.environ:
        args.extend(["--shutdown-ui-args", os.environ[SHUTDOWN_UI_ARGS_ENV]])
    if not getattr(sys, "frozen", False):
        args = ["-m", "src.headless", *args]
    return WindowsDailyTask(entry=(sys.executable, args))


class HeadlessApi:
    """将 CLI 表单转换为业务对象；配置读写统一经 AppService。"""

    def __init__(self, service):
        self.service = service

    def update_script(
        self, script_name, display_name, config_patch, weekly_timeouts, switches
    ):
        from src.service.script_service import ScriptEdit

        edit = ScriptEdit(
            script_name, display_name, config_patch, weekly_timeouts, switches
        )
        return {"script_name": self.service.update_script(edit)}

    def settings_view(self):
        from src.utils.utils_shutdown import shutdown_ui_supported

        return {
            **self.service.settings_view(),
            "shutdown_supported": shutdown_ui_supported(),
        }

    def save_startup(self, options):
        from src.service.schedule import MAX_STARTUP_DELAY_SECONDS, StartupOptions

        if not isinstance(options, dict) or set(options) != {
            "enabled",
            "delay_seconds",
        }:
            raise InvalidParams("启动选项字段无效")
        assert "enabled" in options and "delay_seconds" in options
        if (
            type(options["enabled"]) is not bool
            or type(options["delay_seconds"]) is not int
            or not 1 <= options["delay_seconds"] <= MAX_STARTUP_DELAY_SECONDS
        ):
            raise InvalidParams("自动启动需要布尔开关与 1～3600 秒倒计时")
        return self.service.apply_startup_options(StartupOptions(**options))

    def save_run(self, options):
        return self.service.apply_run_options(_parse_run_options(options))

    def run_view(self, script_names):
        from src.utils.utils_shutdown import shutdown_ui_supported

        return {
            **self.service.run_view(script_names),
            "shutdown_supported": shutdown_ui_supported(),
        }

    def prepare_run(self, script_names, options, confirm_invalid):
        if type(confirm_invalid) is not bool:
            raise InvalidParams("运行确认格式无效")
        saved = self.service.prepare_run(
            script_names, _parse_run_options(options), confirm_invalid
        )
        return _run_target(script_names, saved)

    def saved_run(self, script_names):
        saved = self.service.saved_run(script_names)
        return _run_target(script_names, _parse_run_options(asdict(saved)))

    def plan_view(self):
        from src.utils.utils_shutdown import shutdown_ui_supported

        return {
            **self.service.daily_plan_view(task=_daily_task()),
            "shutdown_supported": shutdown_ui_supported(),
        }

    def save_plan(self, plan):
        from src.service.daily_plan import DailyPlanOptions
        from src.service.schedule import is_valid_target_time
        from src.utils.utils_shutdown import shutdown_ui_supported

        if not isinstance(plan, dict) or set(plan) != {
            "enabled",
            "target_time",
            "run_options",
        }:
            raise InvalidParams("每日计划字段不完整")
        assert all(key in plan for key in ("enabled", "target_time", "run_options"))
        if type(plan["enabled"]) is not bool or not is_valid_target_time(
            plan["target_time"]
        ):
            raise InvalidParams("计划需要布尔开关与有效的 HH:MM 时间")
        if plan["enabled"] and not shutdown_ui_supported():
            raise InvalidParams("启用每日计划需要有效的 Windows 关机确认程序")
        options = _parse_run_options(
            plan["run_options"], require_shutdown_ui=plan["enabled"]
        )
        return self.service.apply_daily_plan(
            DailyPlanOptions(plan["enabled"], plan["target_time"], options),
            task=_daily_task(),
        )


def rpc_methods(service, *, persistent=True) -> dict:
    """显式开放助手方法，保留业务互斥和错误语义；协议和参数绑定交给库。"""
    from src.service.chain_service import InvalidRunRequest
    from src.service.script_service import DuplicateScript, InvalidScript
    from src.service.task_service import InvalidTaskSelection
    from src.utils.utils_job import InvalidJob
    from src.utils.utils_wallpaper import InvalidWallpaper

    api = HeadlessApi(service)
    methods = {
        "app.snapshot": service.app_snapshot,
        "backup.start": service.start_backup,
        "restore.start": service.start_restore,
        "job.poll": service.poll_job,
        "job.cancel": service.cancel_job,
        "update.view": service.update_view,
        "update.check": service.start_update_check,
        "update.download": service.start_update_download,
        "update.install": service.start_update_install,
        "settings.view": api.settings_view,
        "startup.view": api.settings_view,
        "plan.view": api.plan_view,
        "plan.save": api.save_plan,
        "settings.startup_save": api.save_startup,
        "settings.run_save": api.save_run,
        "run.saved": api.saved_run,
        "run.view": api.run_view,
        "run.prepare": api.prepare_run,
        "script.view": service.script_view,
        "script.target": service.resolve_script_target,
        "script.icon_path": service.game_icon_path,
        "wallpaper.current": service.wallpaper_view,
        "wallpaper.view": service.wallpaper_view,
        "wallpaper.set": service.set_wallpaper,
        "wallpaper.cache": service.save_wallpaper_cache,
        "script.launch_target": service.resolve_launch_target,
        "script.edit_view": service.script_edit_view,
        "script.add": service.add_script,
        "script.remove": service.remove_script,
        "script.reorder": service.reorder_scripts,
        "script.edit_save": api.update_script,
        "daily.select": service.select_daily,
        "daily.enable": service.enable_daily,
        "weekly.select": service.select_weekly,
        "weekly.start": service.start_weekly,
    }
    readonly = {
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
    }
    session_only = {
        "backup.start",
        "restore.start",
        "job.poll",
        "job.cancel",
        "update.check",
        "update.download",
        "update.install",
    }

    def unsupported(*args, **kwargs):
        return Error(-32600, "后台任务仅支持 serve --stdio 会话")

    def adapt(name, method):
        @wraps(method)
        def invoke(*args, **kwargs):
            if service.jobs.running and name not in {"job.poll", "job.cancel"}:
                return Error(
                    -32003, "后台操作进行中，请等待完成", {"refresh_required": False}
                )
            try:
                return Success(method(*args, **kwargs))
            except DuplicateScript as exc:
                return Error(-32001, str(exc), {"refresh_required": False})
            except (
                InvalidParams,
                InvalidTaskSelection,
                InvalidScript,
                InvalidRunRequest,
                InvalidJob,
                InvalidWallpaper,
            ) as exc:
                return Error(-32602, str(exc))
            except Exception:  # noqa: BLE001 -- 业务边界记录失败；写入可能已部分完成。
                logger.exception("助手请求失败，method=%s", name)
                return Error(
                    -32002,
                    "操作失败，详情见 stderr 或助手日志",
                    {"refresh_required": name not in readonly},
                )

        return invoke

    return {
        name: unsupported
        if not persistent and name in session_only
        else adapt(name, method)
        for name, method in methods.items()
    }


def _emit(response, output=None) -> None:
    # JSON-RPC notification 没有响应；不能向管道写 null 或空行。
    if response is None:
        return
    output = sys.stdout if output is None else output
    output.write(json.dumps(response, ensure_ascii=False, allow_nan=False) + "\n")
    output.flush()


def _serve(service) -> int:
    output = sys.stdout
    # 后台线程也可能输出诊断；整个会话的业务 stdout 指向 stderr。
    with redirect_stdout(sys.stderr):
        try:
            methods = rpc_methods(service)
            for line in sys.stdin:
                response = dispatch_to_serializable(
                    line, methods=methods, deserializer=_parse_json
                )
                _emit(response, output)
        finally:
            service.close()
    return 0


def _call(service, method: str) -> int:
    def request(payload):
        return {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": _parse_json(payload),
        }

    with redirect_stdout(sys.stderr):
        response = dispatch_to_serializable(
            sys.stdin.read(),
            methods=rpc_methods(service, persistent=False),
            deserializer=request,
        )
    _emit(response)
    return 1 if "error" in response else 0


def _installed_frontend() -> str:
    """更新目标来自安装清单，与连接 CLI 的前端无关。"""
    from src.update.package import MANIFEST, load_manifest, manifest_frontend
    from src.utils import get_root_dir

    root = Path(get_root_dir())
    return (
        manifest_frontend(load_manifest(root)) if (root / MANIFEST).is_file() else "qt"
    )


def main(argv: list[str] | None = None) -> int:
    """更新闸门先于配置初始化；整个 stdio 会话持有运行共享锁。"""
    arguments = sys.argv[1:] if argv is None else argv
    if getattr(sys, "frozen", False):
        from src.update.package import APP_EXE
        from src.utils.utils_shutdown import SHUTDOWN_UI_ENV

        os.environ.setdefault(
            SHUTDOWN_UI_ENV, str(Path(sys.executable).parent / APP_EXE)
        )
    if not arguments or arguments[0] not in {"call", "serve", "run", "daily", "legacy"}:
        arguments = ["legacy", "--", *arguments]
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
    daily = commands.add_parser("daily", help="系统每日计划入口，读取独立计划配置")
    daily.add_argument("--shutdown-ui", required=True)
    daily.add_argument("--shutdown-ui-args", default="[]")
    commands.add_parser("legacy", help="原助手 CLI 参数透传").add_argument(
        "arguments", nargs=argparse.REMAINDER
    )
    args = parser.parse_args(arguments)
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
                service = AppService(frontend=_installed_frontend())
            if args.command == "legacy":
                from src.cli import build_parser, run_cli

                arguments = args.arguments
                if arguments and arguments[0] == "--":
                    arguments = arguments[1:]
                result = run_cli(build_parser().parse_args(arguments))
                if result is None:
                    raise ValueError("请指定 CLI 操作；请启动图形界面入口")
                return result
            if args.command == "daily":
                from src.utils.utils_shutdown import (
                    SHUTDOWN_UI_ARGS_ENV,
                    SHUTDOWN_UI_ENV,
                )

                os.environ[SHUTDOWN_UI_ENV] = args.shutdown_ui
                os.environ[SHUTDOWN_UI_ARGS_ENV] = args.shutdown_ui_args
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
                service.run_batch(
                    payload["script_names"], _parse_run_options(payload["options"])
                )
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
            {
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32004,
                    "message": "会话无法继续，详情见 stderr 或助手日志",
                    "data": {"refresh_required": True},
                },
            }
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
