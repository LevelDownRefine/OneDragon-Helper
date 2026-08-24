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
    chain_path: str,
) -> tuple[list[str], str, dict | None]:
    """构造『运行脚本链』命令（GUI 不再拼命令）。

    关机不再经 runner 的 ``--shutdown``（会抢在重跑前关机），
    改由 service 的 ``post_run`` 在全部运行结束后统一触发（见 ``src.utils_shutdown``）。
    静音由主仓在 ``pre_run``/``post_run`` 直接操作系统音频，不再透传 ``--mute`` 给 runner。
    统一做 ``pythonw.exe`` -> ``python.exe`` 替换，避免冻结态 GUI exe 无控制台。

    Args:
        chain_path: 脚本链配置文件路径。

    Returns:
        (命令列表, 工作目录, 环境变量)。
    """
    extra = ["--chain", chain_path]
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

    启用或关闭都直接落盘完整块：开关与延迟数值一并写入，不回读旧值、不区分分支。
    延迟数值以弹窗给定值为准（关闭时同样是用户最后一次设定的值），行为单一稳定。

    Args:
        config_data: 完整配置字典（load_config 结果），原地修改。
        enabled: 是否运行后关机。
        delay_seconds: 关机延迟秒数（原样写入）。
    """
    config_data["shutdown"] = {
        "after_run": bool(enabled),
        "delay_seconds": int(delay_seconds),
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


def parse_rerun_config(config_data: dict) -> bool:
    """解析 config 的 rerun 配置，返回是否运行后重跑失败脚本。

    Args:
        config_data: 完整配置字典（load_config 结果）。

    Returns:
        启用返回 True，否则 False（缺失/非 dict/非 bool 一律视为未启用，不抛异常）。
    """
    raw = config_data.get("rerun")
    if not isinstance(raw, dict):
        return False
    enabled = raw.get("enabled", False)
    return isinstance(enabled, bool) and enabled


def apply_rerun_config(config_data: dict, *, enabled: bool) -> None:
    """把重跑配置写回 config（原地修改顶层 rerun 映射）。

    Args:
        config_data: 完整配置字典（load_config 结果），原地修改。
        enabled: 是否运行后重跑失败脚本。
    """
    config_data["rerun"] = {"enabled": bool(enabled)}


def parse_notify_enabled(config_data: dict) -> bool:
    """解析 config 的 notify 配置，返回是否运行后发送邮件通知（仅看 enabled 开关）。

    邮件能否真正发送还需 email/password 齐全（由 ``chain_service._resolve_mail_config``
    在运行期校验）；本函数只解析确认弹窗关心的 enabled 勾选初始值。

    Args:
        config_data: 完整配置字典（load_config 结果）。

    Returns:
        启用返回 True，否则 False（缺失/非 dict/非 bool 一律视为未启用，不抛异常）。
    """
    raw = config_data.get("notify")
    if not isinstance(raw, dict):
        return False
    enabled = raw.get("enabled", False)
    return isinstance(enabled, bool) and enabled


def apply_notify_config(config_data: dict, *, enabled: bool) -> None:
    """把邮件通知开关写回 config（原地修改顶层 notify 映射的 enabled）。

    仅更新 ``enabled`` 开关，保留 notify 已有的 email/password 等字段，不因关闭
    通知而清空凭据。

    Args:
        config_data: 完整配置字典（load_config 结果），原地修改。
        enabled: 是否运行后发送邮件通知。
    """
    notify = config_data.get("notify")
    if not isinstance(notify, dict):
        notify = {}
        config_data["notify"] = notify
    notify["enabled"] = bool(enabled)


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


def spawn_schedule_run(
    enabled_keys: set[str],
    target_time: str,
    *,
    chain_name: str = "today",
    mute: bool = False,
    shutdown_delay: int | None = None,
) -> subprocess.Popen | None:
    """起独立控制台进程运行 ``schedule-run``（等待到点后生成并运行链）。

    等待与运行全在独立控制台进程（``CREATE_NEW_CONSOLE``）中进行，不阻塞调用方
    （GUI 主线程）；关闭该控制台即取消。进程在 GUI 退出后依旧存活，故定时运行不受
    关程序影响。链在**点火时**才生成（按当天星期），因此本方法不固定链配置。

    本函数是「壳」：只负责拼命令并拉起独立进程；真实实现（等待→生成→运行→关机）
    在 ``ChainService.schedule_run`` 中。

    子进程须走与 GUI 相同的入口（``src.launcher``，其 ``main`` 会解析参数并路由到
    ``run_cli``）：开发态用 ``python -m src.launcher``，冻结态直接复用 ``sys.executable``
    （打包 exe 的入口即 ``launcher.main``）。``--schedule-run`` 的参数是目标时刻 ``HH:MM``
    （不是 ``--at``）。

    Args:
        enabled_keys: 纳入链的脚本唯一标识集合（**必须显式传入具体集合**）；
            None 不被允许——CLI 已把 ``--enable`` 的缺省/``all`` 物化为全部脚本集合，
            GUI 永远传非空真实集合，故跨进程壳层不再用 None 表达「全部」。
        target_time: 目标时刻 ``"HH:MM"``（24 小时制），须合法（调用方已校验）。
        chain_name: 链配置文件名（不含扩展名，默认 today）。
        mute: 是否运行中静音（透传 ``--mute``）。
        shutdown_delay: 关机延迟秒数；None 表示不关机（含 0/未启用）。

    Returns:
        已启动的 CLI ``subprocess.Popen``；启动失败返回 None。
    """
    # 跨进程壳层不再接受 None：调用方（CLI 已物化 ``all``、GUI 永远传真实集合）
    # 必须显式传入具体集合。None 在此是契约错误，而非「全部」的同义。
    assert enabled_keys is not None
    if getattr(sys, "frozen", False):
        command: list[str] = [sys.executable]
    else:
        command = [sys.executable, "-m", "src.launcher"]
    command += ["--schedule-run", target_time, "--name", chain_name]
    if mute:
        command.append("--mute")
    if shutdown_delay is not None:
        command += ["--shutdown", str(shutdown_delay)]
    if enabled_keys:
        command += ["--enable", ",".join(sorted(enabled_keys))]
    creationflags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
    # 开发态需把 cwd 设到项目根，保证 ``python -m src.launcher`` 能导入 src 包。
    cwd = None if getattr(sys, "frozen", False) else get_root_dir()
    try:
        return subprocess.Popen(command, creationflags=creationflags, cwd=cwd)
    except Exception:
        logger.exception("[runner] 调度运行：启动 CLI 失败")
        return None
