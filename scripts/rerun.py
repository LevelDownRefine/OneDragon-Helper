"""失败游戏重跑：先调 collect_log 收集当日失败脚本，再以子进程调 Runner 重跑。

本模块是"重跑"职责的入口，依赖 collect_log（只做日志收集与打印）来判定哪些游戏失败。
与 collect_log 一致，本模块本身不 import 任何项目（src/）模块，仅依赖标准库与 yaml。
"""

import logging
import os
import subprocess
import sys

import collect_log
import yaml

logger = logging.getLogger(__name__)

# 默认脚本链配置文件（runner 真正用来启动各游戏的那条链）。
_DEFAULT_CHAIN_REL = os.path.join("config", "script_chain", "today.yml")

# 冻结（PyInstaller）模式下 Runner 的可执行文件名（与 src/gui/runner.py 一致）。
_RUNNER_EXE_NAME = "OneDragon-Helper-Runner.exe"


def _resolve_chain_path(chain_path: str | None) -> str:
    """解析脚本链配置文件路径为绝对路径（缺省用项目根下的 today.yml）。"""
    rel = chain_path or _DEFAULT_CHAIN_REL
    if os.path.isabs(rel):
        return rel
    return os.path.join(collect_log._get_root_dir(), rel)


def _find_chain_index(display_name: str, chain_path: str) -> int | None:
    """在脚本链配置中按 display_name 查找失败游戏的下标。

    仅匹配 enabled 非 false 的脚本；找不到或文件缺失返回 None（调用方跳过）。
    直接 yaml.safe_load 读取，保持不 import 项目模块。
    """
    try:
        with open(chain_path, encoding="utf-8") as f:
            chain_data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.warning("[rerun] 脚本链配置不存在，跳过失败重跑: %s", chain_path)
        return None
    except Exception:
        logger.exception("[rerun] 读取脚本链配置失败，跳过失败重跑: %s", chain_path)
        return None

    for idx, entry in enumerate(chain_data.get("script_list", []) or []):
        if not isinstance(entry, dict):
            continue
        if entry.get("display_name") != display_name:
            continue
        if entry.get("enabled", True) is False:
            continue
        return idx
    return None


def _build_rerun_command(
    index: int, chain_path: str
) -> tuple[list[str], str, dict | None]:
    """构造重跑指定下标脚本的 Runner 命令，返回 (命令列表, 工作目录, 环境变量)。

    - 冻结模式：<exe目录>/OneDragon-Helper-Runner.exe --chain <abs> --debug-index <idx>
    - 开发模式：python -m src.runner.launcher ...（cwd=项目根，PYTHONPATH 注入 src/runner）
    不 import 项目模块，frozen/dev 分支仅依赖 sys/os。
    """
    chain_abs = os.path.abspath(chain_path)
    # frozen/dev 两分支共用尾部：--chain <abs> --debug-index <idx>
    tail = ["--chain", chain_abs, "--debug-index", str(index)]

    if getattr(sys, "frozen", False):
        runner_exe = os.path.join(os.path.dirname(sys.executable), _RUNNER_EXE_NAME)
        return [runner_exe, *tail], os.path.dirname(sys.executable), None

    root = collect_log._get_root_dir()
    runner_pkg_dir = os.path.join(root, "src", "runner")
    existing_pp = os.environ.get("PYTHONPATH", "")
    env = {
        **os.environ,
        "PYTHONPATH": runner_pkg_dir
        + (os.pathsep + existing_pp if existing_pp else ""),
    }
    command = [sys.executable, "-m", "src.runner.launcher", *tail]
    return command, root, env


def _rerun_failed_script(display_name: str, chain_path: str) -> bool:
    """对单个失败游戏触发一次阻塞重跑（subprocess 调 Runner）。

    返回 True=已发起（命令已执行），False=无法定位/跳过。仅重跑一次，不重判成败。
    """
    index = _find_chain_index(display_name, chain_path)
    if index is None:
        logger.warning("[rerun] 未在脚本链中找到可重跑的「%s」，跳过", display_name)
        return False

    command, cwd, env = _build_rerun_command(index, chain_path)
    logger.info(
        "[rerun] 重跑失败脚本「%s」（脚本链下标 %d）: %s",
        display_name,
        index,
        " ".join(command),
    )
    try:
        subprocess.run(command, cwd=cwd, env=env, check=False)
    except Exception:
        logger.exception("[rerun] 重跑「%s」时命令执行失败", display_name)
        return False
    return True


def rerun_failed_games() -> None:
    """收集当日失败 / 无日志游戏并逐个重跑。

    先调 collect_log.parse_logs(do_log=False) 静默拿到需重跑列表
    （含 FAILED 与 NO_LOG），再各重跑一次；重跑本身的日志由 Runner 输出，
    因此这里不重复打印分析报表（避免噪声，也利于 agent 调用时保持输出干净）。
    """
    targets = collect_log.parse_logs(do_log=False)
    if not targets:
        logger.info("[rerun] 无失败脚本，无需重跑")
        return
    chain = _resolve_chain_path(None)
    logger.info("[rerun] 开始重跑 %d 个脚本: %s", len(targets), "、".join(targets))
    for name in targets:
        _rerun_failed_script(name, chain)


if __name__ == "__main__":
    rerun_failed_games()
