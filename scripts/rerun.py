"""失败游戏重跑：先调 collect_log 收集当日失败脚本，再以子进程调 Runner 重跑。

本模块是"重跑"职责的入口，依赖 collect_log（只做日志收集与打印）来判定哪些游戏失败。
本项目允许复用核心代码（未来将迁入主流程），故直接复用脚本唯一标识 get_script_name
来匹配脚本链条目；其余仅依赖标准库与 ruamel.yaml（经 src.config.yaml_rt 读写 config）。
"""

import logging
import os
import subprocess
import sys

# 把项目根加入 sys.path，以便 import src.log / src.config。
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import src.log.monitor as collect_log  # noqa: E402
from src.config.subscript import get_script_name  # noqa: E402
from src.config.yaml_rt import load_yaml  # noqa: E402

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


def _find_chain_index(script_name: str, chain_path: str) -> int | None:
    """在脚本链配置中按 script_name 查找失败脚本下标；找不到或文件缺失返回 None。

    仅匹配 enabled 非 false 的脚本；按 get_script_name 匹配（与全链路标识一致）。
    """
    try:
        with open(chain_path, encoding="utf-8") as f:
            chain_data = load_yaml(f) or {}
    except FileNotFoundError:
        logger.warning("[rerun] 脚本链配置不存在，跳过失败重跑: %s", chain_path)
        return None
    except Exception:
        logger.exception("[rerun] 读取脚本链配置失败，跳过失败重跑: %s", chain_path)
        return None

    for idx, entry in enumerate(chain_data.get("script_list", []) or []):
        if not isinstance(entry, dict):
            continue
        if get_script_name(entry) != script_name:
            continue
        if entry.get("enabled", True) is False:
            continue
        return idx
    return None


def _build_rerun_command(
    index: int, chain_path: str
) -> tuple[list[str], str, dict | None]:
    """构造重跑指定下标脚本的 Runner 命令，返回 (命令列表, 工作目录, 环境变量)。

    冻结模式用 OneDragon-Helper-Runner.exe，开发模式用 python -m src.runner.launcher；
    二者共用尾部 --chain <abs> --debug-index <idx>。
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


def _rerun_failed_script(script_name: str, chain_path: str) -> bool:
    """对单个失败脚本触发一次阻塞重跑（subprocess 调 Runner）。

    返回 True=已发起（命令已执行），False=无法定位/跳过。仅重跑一次，不重判成败。
    """
    index = _find_chain_index(script_name, chain_path)
    if index is None:
        logger.warning("[rerun] 未在脚本链中找到可重跑的「%s」，跳过", script_name)
        return False

    command, cwd, env = _build_rerun_command(index, chain_path)
    logger.info(
        "[rerun] 重跑失败脚本「%s」（脚本链下标 %d）: %s",
        script_name,
        index,
        " ".join(command),
    )
    try:
        subprocess.run(command, cwd=cwd, env=env, check=False)
    except Exception:
        logger.exception("[rerun] 重跑「%s」时命令执行失败", script_name)
        return False
    return True


def rerun_failed_games() -> None:
    """收集当日未正常退出的脚本并逐个重跑（各重跑一次，不重判成败）。

    静默调 collect_log.parse_logs 拿需重跑列表（含无日志，可能未正常启动）；
    重跑日志由 Runner 输出，这里不重复打印报表。
    """
    result = collect_log.parse_logs(do_log=False)
    rerun_list = result.get("rerun", [])
    if not rerun_list:
        logger.info("[rerun] 无未正常退出的脚本，无需重跑")
        return
    chain = _resolve_chain_path(None)
    logger.info(
        "[rerun] 开始重跑 %d 个脚本: %s", len(rerun_list), "、".join(rerun_list)
    )
    for name in rerun_list:
        _rerun_failed_script(name, chain)


if __name__ == "__main__":
    rerun_failed_games()
