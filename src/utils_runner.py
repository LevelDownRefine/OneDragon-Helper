"""Runner 相关纯工具（无 Qt 依赖）。

- 配置校验：复刻 runner ``ScriptConfig.invalid_message``，基于 config.yml 的 dict 条目；
- 命令构造与运行：构造 Runner 启动命令（frozen / 开发态统一处理）并运行脚本链子进程。

合并自 ``src.config.utils_runner`` 与 ``src.service.runner_cmds``：两者都是 runner 相关、
无 Qt 的纯逻辑，被 GUI 与 service 多处直接引用，收拢到 src 顶层便于共用。
"""

import ctypes
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import PureWindowsPath

from src.config.subscript import resolve_script_path
from src.utils import get_root_dir

logger = logging.getLogger(__name__)

_CHECK_DONE_VALUES = {"game_closed", "script_closed", "game_or_script_closed"}

# 定时运行的目标时刻格式：HH:MM（24 小时制）。
_TIME_RE = re.compile(r"^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$")


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


def build_run_chain_command(
    chain_path: str, *, shutdown: int | None = None, mute: bool = False
) -> tuple[list[str], str, dict | None]:
    """构造『运行脚本链』命令（统一关机/静音参数构造，GUI 不再拼命令）。

    关机走 runner 的 ``--shutdown N`` flag；静音拼 ``--mute``。统一做
    ``pythonw.exe`` -> ``python.exe`` 替换，避免冻结态 GUI exe 无控制台。

    Args:
        chain_path: 脚本链配置文件路径。
        shutdown: 运行后关机延迟秒数；None 表示不关机。
        mute: 是否运行中静音。

    Returns:
        (命令列表, 工作目录, 环境变量)。
    """
    extra = ["--chain", chain_path]
    if shutdown is not None:
        extra += ["--shutdown", str(shutdown)]
    if mute:
        extra += ["--mute"]
    command, cwd, env = build_script_command(extra)
    # 冻结态 GUI exe 可能为 pythonw.exe，替换为 python.exe 以保证子进程有控制台。
    command = [command[0].replace("pythonw.exe", "python.exe"), *command[1:]]
    return command, cwd, env


def parse_shutdown(config_data: dict) -> int | None:
    """解析 config 的 shutdown 配置，返回运行后关机延迟秒数；未启用返回 None。

    缺失/非 dict / after_run 非真 / delay 缺失或非法（非正整型）一律视为未启用，
    返回 None，不抛异常、不告警。
    """
    raw = config_data.get("shutdown")
    if not isinstance(raw, dict):
        return None
    if not isinstance(raw.get("after_run"), bool) or not raw["after_run"]:
        return None
    delay = raw.get("delay_seconds")
    if not isinstance(delay, int) or delay <= 0:
        return None
    return delay


def build_shutdown_extra_args(config_data: dict) -> list[str]:
    """按 config 的 shutdown 配置生成 ``--shutdown`` 参数；after_run 默认关闭、delay 须为正整型。

    Args:
        config_data: 完整配置字典（load_config 结果）。

    Returns:
        满足条件时返回 ``["--shutdown", N]``，否则返回空列表。

    说明：shutdown 与 timed_run 同为顶层嵌套映射（子键缩进），读取风格统一——
    缺失/非 dict 视为未配置，after_run 默认 False，enabled 但 delay 缺失/非法
    同样视为未启用，不抛异常、不告警。
    """
    raw = config_data.get("shutdown")
    if not isinstance(raw, dict):
        return []
    enabled = raw.get("after_run", False)
    if not isinstance(enabled, bool) or not enabled:
        return []
    delay = raw.get("delay_seconds")
    if not isinstance(delay, int) or delay <= 0:
        return []
    return ["--shutdown", str(delay)]


# ---------------------------------------------------------------------------
# 定时运行（按 config 的 timed_run 决定「启动全部」是否先等待再重生成链）
# ---------------------------------------------------------------------------


def parse_timed_run(config_data: dict) -> tuple[bool, str | None]:
    """解析 config 的 timed_run 配置，返回 (是否启用, 目标时刻 HH:MM 字符串)。

    Args:
        config_data: 完整配置字典（load_config 结果）。

    Returns:
        ``(True, "HH:MM")`` 表示启用且目标时刻合法；其余情况返回 ``(False, None)``，
        即「不定时、立即运行」。缺失/非法配置一律返回未启用，不抛异常、不告警。

    说明：config.yml 统一经 ruamel（YAML 1.2）读写，``04:10`` 始终解析为字符串，
    不会出现 PyYAML 1.1 把 ``04:10`` 误当六十进制数 ``250.0`` 的情形，故此处只需
    校验 ``HH:MM`` 格式。目标时刻必须形如 ``HH:MM``（24 小时制）。
    """
    raw = config_data.get("timed_run")
    if not isinstance(raw, dict):
        return (False, None)
    enabled = raw.get("enabled", False)
    if not isinstance(enabled, bool) or not enabled:
        return (False, None)

    target = raw.get("target_time")
    # enabled=True 但 target_time 缺失/非法：视为「未配置定时」，立即运行而非告警。
    if not isinstance(target, str) or not _TIME_RE.match(target):
        return (False, None)
    return (True, target)


def apply_shutdown_config(
    config_data: dict, *, enabled: bool, delay_seconds: int
) -> None:
    """把自动关机配置写回 config（原地修改顶层 shutdown 映射）。

    Args:
        config_data: 完整配置字典（load_config 结果），原地修改。
        enabled: 是否运行后关机。
        delay_seconds: 关机延迟秒数；enabled 为 True 时须为正整型，否则视为不启用。
    """
    config_data["shutdown"] = {
        "after_run": bool(enabled),
        "delay_seconds": int(delay_seconds) if enabled else 0,
    }


def apply_timed_run_config(
    config_data: dict, *, enabled: bool, target_time: str
) -> None:
    """把定时计划配置写回 config（原地修改顶层 timed_run 映射）。

    Args:
        config_data: 完整配置字典（load_config 结果），原地修改。
        enabled: 是否启用定时运行。
        target_time: 目标时刻 ``"HH:MM"``；enabled 为 True 但格式非法时回退默认 04:10。
    """
    if enabled and not _TIME_RE.match(target_time or ""):
        target_time = "04:10"
    config_data["timed_run"] = {
        "enabled": bool(enabled),
        "target_time": target_time if enabled else "",
    }


# ---------------------------------------------------------------------------
# 运行中静音（执行已下沉 runner：run_chain(mute=...) 链前后静音/恢复）
# 主仓仅做参数转发：parse/apply 读 config，build_*_extra_args 拼 --mute。
# ---------------------------------------------------------------------------


def build_mute_extra_args(config_data: dict) -> list[str]:
    """按 config 的 mute 配置生成 ``--mute`` 参数；未启用返回空列表。

    Args:
        config_data: 完整配置字典（load_config 结果）。

    Returns:
        启用时返回 ``["--mute"]``，否则返回空列表。

    说明：静音执行已由 runner 在脚本链运行前后完成（覆盖异常/强制关闭窗口），
    主仓只负责把「是否静音」的意图透传为命令行参数，不触碰音频 API。
    """
    return ["--mute"] if parse_mute_run(config_data) else []


def parse_mute_run(config_data: dict) -> bool:
    """解析 config 的 mute 配置，返回是否运行中静音。

    Args:
        config_data: 完整配置字典（load_config 结果）。

    Returns:
        启用返回 True，否则 False（缺失/非 dict/非 bool 一律视为未启用，不抛异常）。
    """
    raw = config_data.get("mute")
    if not isinstance(raw, dict):
        return False
    enabled = raw.get("enabled", False)
    return isinstance(enabled, bool) and enabled


def apply_mute_config(config_data: dict, *, enabled: bool) -> None:
    """把运行中静音配置写回 config（原地修改顶层 mute 映射）。

    Args:
        config_data: 完整配置字典（load_config 结果），原地修改。
        enabled: 是否运行中静音。
    """
    config_data["mute"] = {"enabled": bool(enabled)}


def next_target_datetime(target_time: str, now: datetime | None = None) -> datetime:
    """返回下一个等于 target_time 的时刻：今天未到取今天，已过取明天（跨午夜）。

    Args:
        target_time: ``"HH:MM"`` 形式的目标时刻。
        now: 基准时间，默认当前时间（可注入以便测试）。

    Returns:
        下一个 ``target_time`` 对应的 ``datetime``。
    """
    hours, minutes = (int(x) for x in target_time.split(":"))
    now = now or datetime.now()
    candidate = now.replace(hour=hours, minute=minutes, second=0, microsecond=0)
    if now < candidate:
        return candidate
    return candidate + timedelta(days=1)
