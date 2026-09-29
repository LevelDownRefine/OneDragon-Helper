"""无 Qt 助手入口；JSON-RPC 2.0 分发由 jsonrpcserver 处理。"""

import argparse
import json
import logging
import sys
from contextlib import redirect_stdout
from functools import wraps
from pathlib import Path

from jsonrpcserver import Error, Success, dispatch_to_serializable

logger = logging.getLogger(__name__)


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


def rpc_methods(service) -> dict:
    """显式开放助手方法，保留业务错误语义；协议和参数绑定交给库。"""
    from src.service.task_service import InvalidTaskSelection

    methods = {
        "app.snapshot": service.app_snapshot,
        "script.view": service.script_view,
        "daily.select": service.select_daily,
        "daily.enable": service.enable_daily,
        "weekly.select": service.select_weekly,
        "weekly.start": service.start_weekly,
    }

    def adapt(name, method):
        @wraps(method)
        def invoke(*args, **kwargs):
            try:
                return Success(method(*args, **kwargs))
            except InvalidTaskSelection as exc:
                return Error(-32602, str(exc))
            except Exception:  # noqa: BLE001 -- 业务边界记录失败；写入可能已部分完成。
                logger.exception("助手请求失败，method=%s", name)
                return Error(
                    -32002,
                    "操作失败，详情见 stderr 或助手日志",
                    {"refresh_required": name not in {"app.snapshot", "script.view"}},
                )

        return invoke

    return {name: adapt(name, method) for name, method in methods.items()}


def _emit(response, output=None) -> None:
    # JSON-RPC notification 没有响应；不能向管道写 null 或空行。
    if response is None:
        return
    output = sys.stdout if output is None else output
    output.write(json.dumps(response, ensure_ascii=False, allow_nan=False) + "\n")
    output.flush()


def _serve(service) -> int:
    output = sys.stdout
    # 保护协议 stdout，包括适配器或第三方库的意外输出。
    with redirect_stdout(sys.stderr):
        methods = rpc_methods(service)
        for line in sys.stdin:
            response = dispatch_to_serializable(
                line, methods=methods, deserializer=_parse_json
            )
            _emit(response, output)
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
            sys.stdin.read(), methods=rpc_methods(service), deserializer=request
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
    args = parser.parse_args(argv)
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
            return (
                _serve(service)
                if args.command == "serve"
                else _call(service, args.method)
            )
    except BrokenPipeError:
        # 父进程已关闭管道；用 _exit 避免解释器再次 flush 同一断开的 stdout。
        import os

        os._exit(0)
    except Exception:  # noqa: BLE001 -- 入口失败须输出启动错误并释放租约。
        logger.exception("无 GUI CLI 启动或传输失败")
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
