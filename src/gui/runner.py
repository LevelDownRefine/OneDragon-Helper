"""ScriptChainer 启动命令构造与后台运行线程。"""
import subprocess
import sys

from PySide6.QtCore import QThread, Signal

from src.utils import get_path_under_onedragon


def build_chain_command(chain_name: str) -> tuple:
    """构造 ScriptChainer 启动命令与运行目录（GUI 与无界面模式共用）"""
    cwd = get_path_under_onedragon("src")
    command = [
        sys.executable,
        "-m",
        "script_chainer.win_exe.launcher",
        "--onedragon",
        "--chain",
        chain_name,
    ]
    return command, cwd


class ScriptChainRunner(QThread):
    """后台运行 ScriptChainer"""
    finished_signal = Signal(int)

    def __init__(self, chain_name="88"):
        super().__init__()
        self.chain_name = chain_name

    def run(self):
        command, cwd = build_chain_command(self.chain_name)
        res = subprocess.run(command, cwd=cwd)
        self.finished_signal.emit(res.returncode)
