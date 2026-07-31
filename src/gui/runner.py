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
    """Windows 子进程退出码是 32 位无符号 DWORD（可至 0xFFFFFFFF，如崩溃码 0xC0000005），
    可能超过 Qt 信号 ``Signal(int)`` 的 qint32 上限（2147483647），直接 emit 触发
    ``OverflowError``。转成补码有符号表示以适配信号类型（左值仍可被 ``!= 0`` 判错）。
    """
    return ctypes.c_int32(code & 0xFFFFFFFF).value


def build_chain_command(chain_config_path: str, script_index: int | None = None) -> tuple[list[str], str, dict]:
    """构造脚本链启动命令，返回 (命令列表, 工作目录, 环境变量)。

    整链调用（``script_index=None``）运行配置中的全部脚本，由 runner 按每条脚本的
    ``block`` 字段决定阻塞/非阻塞；传 ``script_index`` 则仅运行该下标脚本（调试用）。

    命令调用本项目 vendored 的运行器 ``src.runner.launcher``（不再依赖 git submodule）。
    工作目录设为项目根，并把 ``src/runner`` 加入 ``PYTHONPATH``，使 vendored 的
    ``script_chainer`` 包可被导入。``--chain`` 传入脚本链配置文件的路径。
    """
    common_args = ["--chain", chain_config_path]
    if script_index is not None:
        common_args += ["--debug-index", str(script_index)]
    cwd = get_root_dir()
    runner_pkg_dir = os.path.join(cwd, "src", "runner")
    existing_pp = os.environ.get("PYTHONPATH", "")
    env = {**os.environ, "PYTHONPATH": runner_pkg_dir + (os.pathsep + existing_pp if existing_pp else "")}
    command = [sys.executable, "-m", "src.runner.launcher", *common_args]
    return command, cwd, env


def run_chain_command(chain_config_path: str, script_index: int | None = None, block: bool = True) -> int:
    """构造并运行一条脚本链命令，返回退出码。

    ``chain_config_path`` 为脚本链配置路径；``script_index=None`` 表示整链运行
    （默认），由 runner 内部按每条脚本的 ``block`` 字段处理阻塞/非阻塞；传
    ``script_index`` 仅运行该下标脚本（调试）。``block=True``（默认）等待子进程
    结束并返回其退出码；``block=False`` 以 Popen 即起即返（返回 0 表示已启动），
    用于后台/非阻塞运行整条链。
    """
    command, cwd, env = build_chain_command(chain_config_path, script_index)
    logger.info("[runner] 运行脚本链: %s (cwd=%s, script_index=%s, block=%s)", " ".join(command), cwd, script_index, block)
    if block:
        res = subprocess.run(command, cwd=cwd, env=env)
        return res.returncode
    subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(10)
    return 0


class ScriptChainRunner(QThread):
    """后台运行整条脚本链。

    整链以单个 runner 子进程运行（``python -m src.runner.launcher --chain <path>``），
    由 runner 内部按每条脚本的 ``block`` 字段决定阻塞/非阻塞。要运行的脚本始终从
    脚本链配置文件 ``<chain_config_path>`` 的 ``script_list`` 读取。
    """

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
