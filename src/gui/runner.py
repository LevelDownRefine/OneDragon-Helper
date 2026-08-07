"""脚本链后台运行线程（运行器已 vendored 到 src/runner）。

命令构造与子进程运行等无 Qt 逻辑见 :mod:`src.utils_runner`（GUI 与 CLI 共用，
由调用方直接 import）；本模块仅保留 ``ScriptChainRunner`` 线程包装。
"""

import logging
import os

from PySide6.QtCore import QThread, Signal

from src.utils_runner import run_chain_command

logger = logging.getLogger(__name__)


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
            # run_chain_command 已返回有符号 32 位退出码，可直接 emit（Signal(int) 为 qint32）
            code = run_chain_command(self.chain_config_path)
        except Exception:
            logger.exception("[runner] 运行脚本链失败")
            self.finished_signal.emit(-1)
            return
        self.finished_signal.emit(code)
