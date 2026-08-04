"""脚本链启动命令构造与后台运行线程（运行器已 vendored 到 src/runner）。"""

import ctypes
import logging
import os
import subprocess
import sys
import time

from PySide6.QtCore import QThread, Signal

from src.utils import get_root_dir

logger = logging.getLogger(__name__)


def _to_signed_32(code: int) -> int:
    """将 Windows 退出码转补码有符号 32 位，以适配 ``Signal(int)``（qint32）上限，避免溢出报错。"""
    return ctypes.c_int32(code & 0xFFFFFFFF).value


def build_script_command(extra_args: list[str]) -> tuple[list[str], str, dict | None]:
    """构造 Runner 启动命令（frozen / 开发态统一处理），返回 ``(命令列表, 工作目录, 环境变量)``。

    ``extra_args`` 追加在 runner 命令后（如 ``["--chain", path]``）。冻结态用同目录的
    ``OneDragon-Helper-Runner.exe``；开发态用 ``python -m src.runner.launcher`` 并注入 ``PYTHONPATH``。
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
    """构造脚本链启动命令（``--chain <path>``），返回 ``(命令列表, cwd, env)``。

    ``extra_args`` 透传给 runner（如 ``["--shutdown", "60"]``）。
    """
    return build_script_command(["--chain", chain_config_path] + (extra_args or []))


def run_chain_command(
    chain_config_path: str, block: bool = True, extra_args: list[str] | None = None
) -> int:
    """运行一条脚本链，返回退出码。

    ``block=True``（默认）等待子进程结束并返回退出码；``block=False`` 用 Popen 即起即返
    （返回 0 表示已启动）。``extra_args`` 透传给 runner（如 ``--shutdown``）。
    """
    command, cwd, env = build_chain_command(chain_config_path, extra_args)
    logger.info(
        "[runner] 运行脚本链: %s (cwd=%s, block=%s)", " ".join(command), cwd, block
    )
    if block:
        res = subprocess.run(command, cwd=cwd, env=env)
        return res.returncode
    subprocess.Popen(
        command, cwd=cwd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    time.sleep(10)
    return 0


class ScriptChainRunner(QThread):
    """后台线程：以单个 runner 子进程运行整条脚本链（按配置文件 ``script_list``）。"""

    finished_signal = Signal(int)

    def __init__(self, chain_config_path: str):
        super().__init__()
        self.chain_config_path = chain_config_path

    def run(self):
        if not os.path.exists(self.chain_config_path):
            logger.error("[runner] 脚本链配置不存在: %s", self.chain_config_path)
            self.finished_signal.emit(-1)
            return
        try:
            code = run_chain_command(self.chain_config_path)
        except Exception:
            logger.exception("[runner] 运行脚本链失败")
            self.finished_signal.emit(-1)
            return
        self.finished_signal.emit(_to_signed_32(code))
