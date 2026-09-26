"""无 Qt 的任务卡 CLI：一次性 call 或随 GUI 启动的 serve --stdio。"""

import argparse
import json
import logging
import sys
from contextlib import redirect_stdout
from pathlib import Path

logger = logging.getLogger(__name__)
PROTOCOL_VERSION = 1
# 首期只开放短配置操作；长任务必须另行设计进度与取消协议。
METHODS = {
    "app.snapshot": ("app_snapshot", (), ()),
    "script.view": ("script_view", ("script_name",), ()),
    "daily.select": (
        "select_daily",
        ("script_name", "daily_name", "task_name"),
        ("sequence",),
    ),
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
        for key in required:
            assert key in params
            if not isinstance(params[key], str) or not params[key].strip():
                raise ProtocolError("invalid_params", f"{key} 必须是非空字符串")
        if "sequence" in params and type(params["sequence"]) not in (
            str,
            int,
            bool,
            type(None),
        ):
            raise ProtocolError(
                "invalid_params", "sequence 必须是字符串、整数、布尔或 null"
            )
        mutating = method == "daily.select"
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
    except InvalidTaskSelection as exc:
        return _error(request_id, "invalid_params", str(exc))
    except Exception:  # noqa: BLE001 -- IPC 边界必须回复；写入可能已部分完成。
        logger.exception("任务卡请求失败，id=%r", request_id)
        return _error(
            request_id,
            "operation_failed",
            "操作失败，详情见 stderr 或助手日志",
            refresh_required=mutating,
        )


def _emit(response: dict) -> None:
    sys.stdout.write(json.dumps(response, ensure_ascii=False, allow_nan=False) + "\n")
    sys.stdout.flush()


def _serve(service) -> int:
    for line in sys.stdin:
        try:
            request = _parse_json(line)
        except ValueError as exc:
            _emit(_error(None, "parse_error", str(exc)))
            continue
        _emit(handle_request(service, request))
    return 0


def _call(service, method: str) -> int:
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
