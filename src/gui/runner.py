"""ScriptChainer 启动命令构造与后台运行线程。"""
import logging
import os
import subprocess
import sys

import yaml
from PySide6.QtCore import QThread, Signal

from src.utils import get_path_under_onedragon, safe_path_join

logger = logging.getLogger(__name__)


def build_chain_command(chain_name: str, script_index: int) -> tuple[list[str], str]:
    """构造 ScriptChainer 启动命令，返回 (命令列表, 工作目录)。

    参数结构与子项目 OneDragon-ScriptChainer 的
    ``script_chainer.utils.runner_utils.build_runner_command`` 对齐：始终以
    ``--debug-index <script_index>`` 运行指定下标脚本（及其挂靠组）。下标相对
    脚本链配置文件 ``script_chain/<name>.yml`` 的 ``script_list`` 顺序。
    """
    common_args = ["--onedragon", "--chain", chain_name, "--debug-index", str(script_index)]
    cwd = get_path_under_onedragon("src")
    command = [sys.executable, "-m", "script_chainer.win_exe.launcher", *common_args]
    return command, cwd


def run_chain_command(chain_name: str, script_index: int) -> int:
    """构造并同步运行一条 ScriptChainer 脚本命令，返回退出码。

    ``script_index`` 为要运行的脚本下标（必填，不允许 ``None``）；调用方
    （``ScriptChainRunner.run``）以 for 循环逐条传入，便于未来单条调试。
    """
    assert script_index is not None, "[runner] script_index 不能为 None（必须指定要运行的脚本下标）"
    command, cwd = build_chain_command(chain_name, script_index)
    logger.info("[runner] 运行脚本: %s (cwd=%s, script_index=%s)", " ".join(command), cwd, script_index)
    res = subprocess.run(command, cwd=cwd)
    return res.returncode


def _chain_config_path(chain_name: str) -> str:
    """脚本链配置文件路径（OneDragon-ScriptChainer/config/script_chain/<name>.yml）。"""
    return safe_path_join(get_path_under_onedragon("config", "script_chain"), f"{chain_name}.yml")


class ScriptChainRunner(QThread):
    """后台逐条运行 ScriptChainer 脚本。

    每条脚本以 ``--debug-index <i>`` 单独启动一个独立进程，便于未来按需单条
    调试。要运行的脚本下标始终从脚本链配置文件
    ``script_chain/<name>.yml`` 的 ``script_list`` 读取（即运行链中的每个脚本）。
    """

    finished_signal = Signal(int)

    def __init__(self, chain_name="88"):
        super().__init__()
        self.chain_name = chain_name

    def _resolve_script_indices(self) -> list[int]:
        """从脚本链配置文件读取要运行的脚本下标列表。

        下标相对 ``script_chain/<name>.yml`` 的 ``script_list`` 顺序，保证与
        「实际要跑的链」严格对齐。
        """
        chain_path = _chain_config_path(self.chain_name)
        assert os.path.exists(chain_path), f"[runner] 脚本链配置不存在: {chain_path}"
        with open(chain_path, encoding='utf-8') as f:
            chain_data = yaml.safe_load(f) or {}
        assert 'script_list' in chain_data, "[runner] 脚本链配置缺少 script_list 字段"
        return list(range(len(chain_data['script_list'])))

    def run(self):
        # 解析脚本链配置：失败属前置错误，必须 emit 并退出，否则运行按钮会卡死。
        try:
            indices = self._resolve_script_indices()
        except Exception:
            logger.exception("[runner] 解析脚本链配置失败")
            self.finished_signal.emit(-1)
            return

        # 逐条以独立进程运行；单条失败不影响其余脚本继续运行。
        final_code = 0
        for script_index in indices:
            try:
                code = run_chain_command(self.chain_name, script_index)
            except Exception:
                logger.exception("[runner] 运行脚本 %s 失败", script_index)
                final_code = -1
                continue
            if code != 0:
                final_code = code
        self.finished_signal.emit(final_code)
