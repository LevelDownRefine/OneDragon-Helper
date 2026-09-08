"""Runner 相关纯工具（无 Qt 依赖）。

- 配置校验：复刻 runner ``ScriptConfig.invalid_message``，基于 config.yml 的 dict 条目；
- 命令构造与运行：构造 Runner 启动命令（frozen / 开发态统一处理）并运行脚本链子进程。

合并自 ``src.config.utils_runner`` 与 ``src.service.runner_cmds``：两者都是 runner 相关、
无 Qt 的纯逻辑，被 GUI 与 service 多处直接引用，收拢到 src 顶层便于共用。
"""

import contextlib
import ctypes
import logging
import os
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PureWindowsPath

import psutil

from src.utils import get_root_dir
from src.utils.utils_sub_config import resolve_script_path

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
    """判断两个进程名是否相等，按不区分大小写处理。

    配置里写的进程名与运行期实际进程名大小写可能不一致（如 ``Game.exe`` vs
    ``game.exe``），故比较始终忽略大小写；跨平台一致（Windows 进程名本就不区分
    大小写，Linux 下则作为健壮性处理）。``.exe`` 后缀补全是 Windows 专属，仍由
    :func:`_normalize_process_name` 单独处理。

    对齐 runner script_chainer.utils.process_name_utils.process_name_equals。
    """
    if left is None or right is None:
        return left == right
    return (
        _normalize_process_name(left).lower() == _normalize_process_name(right).lower()
    )


@dataclass(frozen=True)
class ProcessTarget:
    """进程匹配条件（对齐 runner 子模块 ``ProcessInfo`` 的 AND 语义）。

    Attributes:
        name: 进程名（不区分大小写，Windows 补 ``.exe``）。
        cmdline_contains: 命令行须包含的子串（不区分大小写）。用于认出「启动器拉起的
            真身」——启动器 exe（如 ``ok-nte.exe``）常只负责拉起真身（自带
            ``pythonw.exe`` 跑 ``working/main.py``），真身进程名与启动器无关且多为
            通用解释器名，只能靠命令行里的脚本安装根目录识别，无需额外配置。
            runner 用的是 cmdline 全等，此处放宽为子串：启动参数顺序 / 大小写变化
            不影响匹配。
    """

    name: str | None = None
    cmdline_contains: str | None = None


def _safe_name(proc: psutil.Process) -> str:
    """读取进程名；无权访问或已退出返回空串。"""
    try:
        return proc.name() or ""
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return ""


def _safe_cmdline(proc: psutil.Process) -> str:
    """读取进程命令行；无权访问或已退出返回空串。"""
    try:
        return " ".join(proc.cmdline())
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return ""


def _describe(proc: psutil.Process) -> str:
    """进程描述：``名字(pid)``；名字不可读时退化为 ``pid=<pid>``。"""
    name = _safe_name(proc)
    return f"{name}({proc.pid})" if name else f"pid={proc.pid}"


def _match_process(target: ProcessTarget, name: str, cmdline: str) -> bool:
    """所有非 None 条件都满足才算匹配（对齐 runner ``match_process``）。

    ``name`` / ``cmdline`` 由调用方**按进程预算好**再传入：二者都是系统调用，
    逐 target 各取一次会让开销随 target 数线性增长（``cmdline()`` 约 5.9ms/次，
    8 条 cmdline 条件 × 349 进程 ≈ 16s）。

    Args:
        target: 匹配条件。
        name: 该进程名，取不到时为空串。
        cmdline: 该进程命令行，取不到时为空串。
    """
    if target.name is not None and not _process_name_equals(name, target.name):
        return False
    if target.cmdline_contains is not None:
        if target.cmdline_contains.lower() not in cmdline.lower():
            return False
    return True


def collect_process_targets(script: dict) -> list[ProcessTarget]:
    """汇总某脚本需要关闭的进程匹配条件：脚本进程 + 启动器真身 + 游戏进程。

    - 脚本进程：``script_process_name`` 显式配置，或 ``script_path`` 文件名（启动器本体）；
    - 启动器真身：命令行含 ``script_path`` 的**安装根目录**（详见
      :class:`ProcessTarget` 的 ``cmdline_contains``）；
    - 游戏进程：``game_process_name`` 显式配置。
    结果按（进程名小写, 命令行标记）去重；无任何配置项时返回空列表。
    """
    targets: list[ProcessTarget] = []
    for name in _normalize_process_names(script.get("script_process_name", "")):
        targets.append(ProcessTarget(name=name))
    script_path = script.get("script_path") or ""
    if script_path:
        targets.append(ProcessTarget(name=PureWindowsPath(script_path).name))
        root_dir = str(PureWindowsPath(script_path).parent)
        if root_dir and root_dir != ".":
            targets.append(ProcessTarget(cmdline_contains=root_dir))
    for name in _normalize_process_names(script.get("game_process_name", "")):
        targets.append(ProcessTarget(name=name))
    seen: set[tuple[str | None, str | None]] = set()
    out: list[ProcessTarget] = []
    for target in targets:
        key = (target.name.lower() if target.name else None, target.cmdline_contains)
        if key not in seen:
            seen.add(key)
            out.append(target)
    return out


def _self_and_ancestor_pids() -> set[int]:
    """本进程及其祖先的 PID：清理时须排除，避免把自己杀掉。"""
    pids: set[int] = set()
    proc: psutil.Process | None = psutil.Process()
    while proc is not None:
        pids.add(proc.pid)
        try:
            proc = proc.parent()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            break
    return pids


def _find_processes(targets: Sequence[ProcessTarget]) -> list[psutil.Process]:
    """按匹配条件找出所有进程（排除本进程及其祖先）；无匹配返回空列表。"""
    if not targets:
        return []
    excluded = _self_and_ancestor_pids()
    found: dict[int, psutil.Process] = {}
    for proc in psutil.process_iter(["pid"]):
        if proc.pid in excluded or proc.pid in found:
            continue
        name = _safe_name(proc)
        # cmdline 惰性且至多一次：name 型条件已命中就无需再取（它比 name() 贵约千倍）。
        cmdline: str | None = None
        for target in targets:
            if target.cmdline_contains is not None and cmdline is None:
                cmdline = _safe_cmdline(proc)
            if _match_process(target, name, cmdline or ""):
                found[proc.pid] = proc
                break
    return list(found.values())


def _build_child_map() -> dict[int, list[psutil.Process]]:
    """一次遍历建立 ``ppid -> 子进程列表``，供树查找复用。

    替代逐个调用 ``children(recursive=True)``——后者每调一次就是一遍全量遍历，
    命中 k 个进程即 k 遍。``ppid`` 与 ``name()`` 同级属廉价属性，实测整表约 0.02s
    （真正的开销是 ``cmdline()``，约 5.9ms/进程）。
    """
    kids: dict[int, list[psutil.Process]] = {}
    for proc in psutil.process_iter(["pid", "ppid"]):
        ppid = proc.info.get("ppid")
        if ppid is not None:
            kids.setdefault(ppid, []).append(proc)
    return kids


def _process_tree(
    proc: psutil.Process, child_map: dict[int, list[psutil.Process]]
) -> list[psutil.Process]:
    """进程自身 + 全部子孙（按 :func:`_build_child_map` 的 ppid 表下溯）。

    Args:
        proc: 树根进程。
        child_map: ``ppid -> 子进程列表``，由 :func:`_build_child_map` 一次建好。

    Returns:
        树根及其全部子孙；``seen`` 保证环或重复挂载下每个 pid 只出现一次。
    """
    out: list[psutil.Process] = []
    seen: set[int] = set()
    stack = [proc]
    while stack:
        item = stack.pop()
        if item.pid in seen:
            continue
        seen.add(item.pid)
        out.append(item)
        stack.extend(child_map.get(item.pid, ()))
    return out


def kill_processes(targets: Sequence[ProcessTarget]) -> int:
    """优雅终止所有匹配进程及其子进程树（对齐 runner ``ProcessManager.kill``）。

    先对整棵树 ``terminate``，等 3 秒，仍存活的强制 ``kill``。无匹配、进程已退出或
    无权访问时安全跳过，不影响其他进程。

    Args:
        targets: 进程匹配条件序列；空直接返回空列表。

    Returns:
        被终止进程的描述列表 ``["名字(pid)", ...]``（含子进程树）。
        描述在 terminate 之前采集——进程退出后名字就读不到了。
    """
    matched = _find_processes(targets)
    if not matched:
        return []
    child_map = _build_child_map()
    tree: dict[int, psutil.Process] = {}
    for proc in matched:
        for item in _process_tree(proc, child_map):
            tree.setdefault(item.pid, item)
    pending = list(tree.values())
    killed = [_describe(proc) for proc in pending]
    for proc in pending:
        with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
            proc.terminate()
    _gone, alive = psutil.wait_procs(pending, timeout=3)
    for proc in alive:
        with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
            proc.kill()
    return killed


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
    改由 service 的 ``post_run`` 在全部运行结束后统一触发（见 ``src.utils.utils_shutdown``）。
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


def spawn_schedule_run(
    enabled_keys: set[str],
    target_time: str,
    *,
    chain_name: str = "today",
    mute: bool = False,
    unmute: bool = False,
    shutdown_delay: int | None = None,
    close_running: bool = True,
) -> subprocess.Popen | None:
    """起独立控制台进程运行 ``schedule-run``（等待到点后生成并运行链）。

    等待与运行全在独立控制台进程（``CREATE_NEW_CONSOLE``）中进行，不阻塞调用方
    （GUI 主线程）；关闭该控制台即取消。进程在 GUI 退出后依旧存活，故定时运行不受
    关程序影响。链在**点火时**才生成（按当天星期），因此本方法不固定链配置。

    本函数是「壳」：只负责拼命令并拉起独立进程；真实实现（等待→生成→运行→关机）
    在 ``chain_service.schedule_run`` 中。

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
        mute: 是否运行前静音（透传 ``--mute``）。
        unmute: 是否运行后开启声音（透传 ``--unmute``）。
        shutdown_delay: 关机延迟秒数；None 表示不关机（含 0/未启用）。
        close_running: 是否运行前关闭残留进程（透传 ``--close-running``，默认启用）。

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
    if unmute:
        command.append("--unmute")
    if close_running:
        command.append("--close-running")
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
