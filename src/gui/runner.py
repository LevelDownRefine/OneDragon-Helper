"""ScriptChainer 启动命令构造与后台运行线程。"""
import logging
import subprocess
import sys

from PySide6.QtCore import QThread, Signal

from src.utils import get_path_under_onedragon

logger = logging.getLogger(__name__)


def run_chain_command(chain_name: str) -> int:
    """构造并同步运行 ScriptChainer 启动命令，返回退出码。"""
    cwd = get_path_under_onedragon("src")
    command = [
        sys.executable,
        "-m",
        "script_chainer.win_exe.launcher",
        "--onedragon",
        "--chain",
        chain_name,
    ]
    logger.info("[runner] 运行脚本链: %s (cwd=%s)", " ".join(command), cwd)
    res = subprocess.run(command, cwd=cwd)
    return res.returncode


class ScriptChainRunner(QThread):
    """后台运行 ScriptChainer"""
    finished_signal = Signal(int)

    def __init__(self, chain_name="88"):
        super().__init__()
        self.chain_name = chain_name

    def run(self):
        # 线程边界：无论子进程是否抛异常，都必须 emit finished_signal，
        # 否则主线程 _on_finished 永不触发，运行按钮会卡在「运行中...」。
        try:
            self.finished_signal.emit(run_chain_command(self.chain_name))
        except Exception:
            logger.exception("[runner] 运行脚本链失败")
            self.finished_signal.emit(-1)
