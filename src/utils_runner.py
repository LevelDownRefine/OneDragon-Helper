"""Runner 相关纯工具（无 Qt 依赖）。

- 配置校验：复刻 runner ``ScriptConfig.invalid_message``，基于 config.yml 的 dict 条目；
- 命令构造与运行：构造 Runner 启动命令（frozen / 开发态统一处理）并运行脚本链子进程。

合并自 ``src.config.utils_runner`` 与 ``src.service.runner_cmds``：两者都是 runner 相关、
无 Qt 的纯逻辑，被 GUI 与 service 多处直接引用，收拢到 src 顶层便于共用。
"""

import ctypes
import logging
import os
import subprocess
import sys
import time
from pathlib import PureWindowsPath

from src.config.subscript import resolve_script_path
from src.utils import get_root_dir

logger = logging.getLogger(__name__)

_CHECK_DONE_VALUES = {"game_closed", "script_closed", "game_or_script_closed"}


# ---------------------------------------------------------------------------
# 配置校验（对齐 runner ScriptConfig.invalid_message，GUI 侧 dict 数据形态）
# ---------------------------------------------------------------------------


def _normalize_process_name(name: str) -> str:
    """规范化单个进程名，自动补齐 Windows 下的 `.exe` 后缀。

    对齐 runner script_chainer.utils.process_name_utils.normalize_process_name。
    """
    normalized = (name or "").strip()
    if not normalized:
        return ""
    if sys.platform == "win32" and not normalized.lower().endswith(".exe"):
        normalized = f"{normalized}.exe"
    return normalized


def _normalize_process_names(value) -> list[str]:
    """规范化进程名列表（去空白、补 .exe、去重）。

    对齐 runner script_chainer.utils.process_name_utils.normalize_process_names。
    """
    if value is None:
        return []
    raw_items = [value] if isinstance(value, str) else list(value)
    result: list[str] = []
    seen: set[str] = set()
    for raw_name in raw_items:
        name = _normalize_process_name(raw_name)
        if not name:
            continue
        dedupe_key = name.lower() if sys.platform == "win32" else name
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        result.append(name)
    return result


def _process_name_equals(left: str | None, right: str | None) -> bool:
    """判断两个进程名是否相等，Windows 下按不区分大小写处理。

    对齐 runner script_chainer.utils.process_name_utils.process_name_equals。
    """
    if left is None or right is None:
        return left == right
    if sys.platform == "win32":
        return (
            _normalize_process_name(left).lower()
            == _normalize_process_name(right).lower()
        )
    return _normalize_process_name(left) == _normalize_process_name(right)


def script_invalid_message(script: dict) -> str | None:
    """校验单条脚本配置（config.yml 中的 script_list 条目），返回不合法原因或 None。

    与 runner ``ScriptConfig.invalid_message`` 对齐，但基于 dict 条目（GUI 侧数据形态），
    路径解析复用 ``resolve_script_path``（相对路径按项目根解析）。
    返回 ``None`` 表示合法。
    """
    script_type = script.get("script_type", "external")
    script_path = script.get("script_path") or ""

    if script_type == "python":
        if not script_path:
            return "Python 脚本路径为空"
        resolved = resolve_script_path(script_path)
        if not os.path.exists(resolved):
            return f"Python 脚本不存在 {script_path}"
        return None

    if not script_path:
        return "脚本路径为空"
    resolved = resolve_script_path(script_path)
    if not os.path.exists(resolved):
        return f"脚本路径不存在 {script_path}"

    check_done = script.get("check_done", "")
    if check_done not in _CHECK_DONE_VALUES:
        return f"检查完成方式非法 {check_done}"

    game_process_name = _normalize_process_name(script.get("game_process_name", ""))
    if (
        check_done in ("game_or_script_closed", "game_closed")
        or script.get("kill_game_after_done", False)
    ) and not game_process_name:
        return "游戏进程名称为空"

    script_process_names = _normalize_process_names(script.get("script_process_name"))
    if (
        script.get("launcher_mode", False)
        and (
            check_done in ("game_or_script_closed", "script_closed")
            or script.get("kill_script_after_done", True)
        )
        and not script_process_names
    ):
        return "启动后实际运行的程序为空"

    if script.get("launcher_mode", False) and script_path:
        launch_name = PureWindowsPath(script_path).name
        if any(
            _process_name_equals(item, launch_name) for item in script_process_names
        ):
            return f"启动后实际运行的程序不能包含启动程序本体 {launch_name}"

    run_timeout = script.get("run_timeout_seconds", 3600)
    if not run_timeout or int(run_timeout) <= 0:
        return "运行超时时间必须大于0"

    return None


def collect_invalid_script_messages(script_list: list[dict]) -> list[tuple[str, str]]:
    """遍历脚本列表，返回 ``[(display_name, invalid_message), ...]``（仅不合法项）。

    供 GUI 运行前与 CLI 生成前校验使用；合法脚本不出现在结果里。

    Args:
        script_list: 脚本配置条目列表。

    Returns:
        (display_name, invalid_message) 列表，仅含不合法项。
    """
    result: list[tuple[str, str]] = []
    for script in script_list:
        message = script_invalid_message(script)
        if message is not None:
            result.append((script.get("display_name") or "(未命名)", message))
    return result


# ---------------------------------------------------------------------------
# 命令构造与运行（frozen / 开发态统一处理）
# ---------------------------------------------------------------------------


def _to_signed_32(code: int) -> int:
    """将退出码转补码有符号 32 位整数。"""
    return ctypes.c_int32(code & 0xFFFFFFFF).value


def build_script_command(extra_args: list[str]) -> tuple[list[str], str, dict | None]:
    """构造 Runner 启动命令（frozen / 开发态统一处理）。

    Args:
        extra_args: 追加在 runner 命令后的参数（如 ``["--chain", path]``）。

    Returns:
        (命令列表, 工作目录, 环境变量)。冻结态调用同目录 Runner exe；
        开发态用 ``python -m src.runner.launcher`` 并注入 ``PYTHONPATH``。
    """
    if getattr(sys, "frozen", False):
        runner_exe = os.path.join(
            os.path.dirname(sys.executable), "OneDragon-Helper-Runner.exe"
        )
        return [runner_exe, *extra_args], os.path.dirname(sys.executable), None

    cwd = get_root_dir()
    runner_pkg_dir = os.path.join(cwd, "src", "runner")
    existing_pp = os.environ.get("PYTHONPATH", "")
    env = {
        **os.environ,
        "PYTHONPATH": runner_pkg_dir
        + (os.pathsep + existing_pp if existing_pp else ""),
    }
    command = [sys.executable, "-m", "src.runner.launcher", *extra_args]
    return command, cwd, env


def build_chain_command(
    chain_config_path: str, extra_args: list[str] | None = None
) -> tuple[list[str], str, dict | None]:
    """构造脚本链启动命令（``--chain <path>``）。

    Args:
        chain_config_path: 脚本链配置文件路径。
        extra_args: 透传给 runner 的额外参数（如 ``["--shutdown", "60"]``）。

    Returns:
        (命令列表, 工作目录, 环境变量)。
    """
    return build_script_command(["--chain", chain_config_path] + (extra_args or []))


def run_chain_command(
    chain_config_path: str, block: bool = True, extra_args: list[str] | None = None
) -> int:
    """运行一条脚本链。

    Args:
        chain_config_path: 脚本链配置文件路径。
        block: True 等待子进程结束并返回退出码；False 用 Popen 即起即返。
        extra_args: 透传给 runner 的额外参数（如 ``["--shutdown", "60"]``）。

    Returns:
        退出码（有符号 32 位）；block=False 时返回 0 表示已启动。
    """
    command, cwd, env = build_chain_command(chain_config_path, extra_args)
    logger.info(
        "[runner] 运行脚本链: %s (cwd=%s, block=%s)", " ".join(command), cwd, block
    )
    if block:
        res = subprocess.run(command, cwd=cwd, env=env)
        return _to_signed_32(res.returncode)
    subprocess.Popen(
        command, cwd=cwd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    time.sleep(10)
    return 0


def build_shutdown_extra_args(config_data: dict) -> list[str]:
    """按 config 生成 ``--shutdown`` 参数；shutdown_after_run 默认开启、delay 须为正整型。

    Args:
        config_data: 完整配置字典。

    Returns:
        满足条件时返回 ``["--shutdown", N]``，否则返回空列表。
    """
    if "shutdown_after_run" in config_data and (
        not isinstance(config_data["shutdown_after_run"], bool)
        or not config_data["shutdown_after_run"]
    ):
        return []
    if "shutdown_delay_seconds" not in config_data:
        return []
    delay = config_data["shutdown_delay_seconds"]
    if not isinstance(delay, int) or delay <= 0:
        return []
    return ["--shutdown", str(delay)]
