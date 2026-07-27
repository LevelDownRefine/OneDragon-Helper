"""测试 src/gui/runner.py：命令构造、run_chain_command 的 script_index 约束、运行线程的 for 循环。"""
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

# 在导入 PySide6 之前设置 offscreen 平台插件（CI 无显示器环境）
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import yaml

from src.gui.runner import ScriptChainRunner, build_chain_command, run_chain_command
from src.utils import get_path_under_onedragon


class TestBuildChainCommand(unittest.TestCase):
    """验证命令构造与 script_index → --debug-index 的映射。"""

    def test_build_chain_command_includes_debug_index(self):
        command, cwd = build_chain_command("88", 2)
        self.assertEqual(command[0], sys.executable)
        self.assertIn("-m", command)
        self.assertIn("script_chainer.win_exe.launcher", command)
        self.assertIn("--onedragon", command)
        self.assertIn("--chain", command)
        self.assertIn("88", command)
        idx = command.index("--debug-index")
        self.assertEqual(command[idx - 2], "--chain")
        self.assertEqual(command[idx - 1], "88")
        self.assertEqual(command[idx + 1], "2")
        self.assertEqual(cwd, get_path_under_onedragon("src"))


class TestRunChainCommandScriptIndex(unittest.TestCase):
    """验证 run_chain_command 要求非 None 的 script_index，并透传到 subprocess。"""

    def test_script_index_passed_to_subprocess(self):
        with mock.patch("src.gui.runner.subprocess.run") as run:
            run.return_value.returncode = 0
            rc = run_chain_command("88", script_index=3)
        self.assertEqual(rc, 0)
        command = run.call_args.args[0]
        self.assertIn("--debug-index", command)
        self.assertEqual(command[command.index("--debug-index") + 1], "3")
        self.assertEqual(run.call_args.kwargs["cwd"], get_path_under_onedragon("src"))

    def test_run_chain_command_asserts_on_none(self):
        """script_index=None 属编程错误：run_chain_command 必须 assert。"""
        with self.assertRaises(AssertionError):
            run_chain_command("88", script_index=None)


class TestResolveScriptSpecs(unittest.TestCase):
    """验证规格 (下标, 是否阻塞) 始终从 chain config 读取，含 block。"""

    def _write_cfg(self, data):
        d = tempfile.mkdtemp()
        cfg = os.path.join(d, "88.yml")
        with open(cfg, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f)
        return cfg

    def test_reads_specs_including_block(self):
        cfg = self._write_cfg({"script_list": [
            {"display_name": "a"},
            {"display_name": "b", "block": False},
            {"display_name": "c"},
        ]})
        with mock.patch("src.gui.runner._chain_config_path", return_value=cfg):
            r = ScriptChainRunner("88")
            self.assertEqual(r._resolve_script_specs(), [(0, True), (1, False), (2, True)])

    def test_missing_block_defaults_true(self):
        cfg = self._write_cfg({"script_list": [{"display_name": "a"}]})
        with mock.patch("src.gui.runner._chain_config_path", return_value=cfg):
            self.assertEqual(ScriptChainRunner("88")._resolve_script_specs(), [(0, True)])

    def test_missing_chain_config_asserts(self):
        with mock.patch("src.gui.runner._chain_config_path", return_value="/no/such/88.yml"):
            r = ScriptChainRunner("88")
            with self.assertRaises(AssertionError):
                r._resolve_script_specs()

    def test_missing_script_list_asserts(self):
        cfg = self._write_cfg({"other": 1})
        with mock.patch("src.gui.runner._chain_config_path", return_value=cfg):
            r = ScriptChainRunner("88")
            with self.assertRaises(AssertionError):
                r._resolve_script_specs()


class TestScriptChainRunnerInit(unittest.TestCase):
    """验证构造参数。"""

    def test_runner_stores_chain_name(self):
        r = ScriptChainRunner("88")
        self.assertEqual(r.chain_name, "88")


class TestScriptChainRunnerRunLoop(unittest.TestCase):
    """验证 run 逐 (下标,阻塞) 循环，block 直接透传；单条失败不影响其余，
    finished_signal 一定 emit。"""

    def _run_with_specs(self, specs):
        received = []
        with mock.patch("src.gui.runner.run_chain_command", return_value=0) as rc, \
             mock.patch.object(ScriptChainRunner, "_resolve_script_specs", return_value=specs):
            r = ScriptChainRunner("88")
            r.finished_signal.connect(lambda c: received.append(c))
            r.run()
        return rc, received

    def test_run_passes_block_directly(self):
        """规格中的 block 直接透传：block=True 等待，block=False 非阻塞。"""
        rc, received = self._run_with_specs([(0, True), (1, False), (2, True)])
        self.assertEqual(rc.call_count, 3)
        blocks = [c.kwargs["block"] for c in rc.call_args_list]
        self.assertEqual(blocks, [True, False, True])
        self.assertEqual(received, [0])

    def test_run_carries_last_failure_code(self):
        with mock.patch("src.gui.runner.run_chain_command", side_effect=[0, 1, 0]), \
             mock.patch.object(ScriptChainRunner, "_resolve_script_specs", return_value=[(0, True), (1, True), (2, True)]):
            received = []
            r = ScriptChainRunner("88")
            r.finished_signal.connect(lambda c: received.append(c))
            r.run()
        self.assertEqual(received, [1])

    def test_run_continues_on_per_script_exception(self):
        """for 循环内 try 包裹单条运行：某条抛异常后继续运行其余，并以 -1 收尾。"""
        with mock.patch("src.gui.runner.run_chain_command", side_effect=[0, RuntimeError("boom"), 0]), \
             mock.patch.object(ScriptChainRunner, "_resolve_script_specs", return_value=[(0, True), (1, True), (2, True)]):
            received = []
            r = ScriptChainRunner("88")
            r.finished_signal.connect(lambda c: received.append(c))
            r.run()
        self.assertEqual(received, [-1])

    def test_run_always_emits_even_on_resolve_failure(self):
        with mock.patch.object(ScriptChainRunner, "_resolve_script_specs", side_effect=RuntimeError("boom")):
            received = []
            r = ScriptChainRunner("88")
            r.finished_signal.connect(lambda c: received.append(c))
            r.run()
        self.assertEqual(received, [-1])


class TestNonBlocking(unittest.TestCase):
    """验证 run_chain_command 的 block 分支；block=False 以 Popen 即起即返。"""

    def test_nonblock_uses_popen_and_returns_zero(self):
        with mock.patch("src.gui.runner.subprocess.run") as run, \
             mock.patch("src.gui.runner.subprocess.Popen") as popen:
            rc = run_chain_command("88", script_index=2, block=False)
        self.assertEqual(rc, 0)
        popen.assert_called_once()
        run.assert_not_called()
        _, kwargs = popen.call_args
        self.assertEqual(kwargs["stdout"], subprocess.DEVNULL)
        self.assertEqual(kwargs["stderr"], subprocess.DEVNULL)

    def test_block_true_uses_subprocess_run(self):
        with mock.patch("src.gui.runner.subprocess.run") as run, \
             mock.patch("src.gui.runner.subprocess.Popen") as popen:
            run.return_value.returncode = 0
            run_chain_command("88", script_index=2, block=True)
        run.assert_called_once()
        popen.assert_not_called()

    def test_runner_runs_nonblocking_script(self):
        """chain 中 block=False 的脚本应以 block=False 运行。"""
        with mock.patch("src.gui.runner.run_chain_command", return_value=0) as rc, \
             mock.patch.object(ScriptChainRunner, "_resolve_script_specs", return_value=[(0, False)]):
            ScriptChainRunner("88").run()
        self.assertEqual(rc.call_args.kwargs["block"], False)

    def test_runner_runs_blocking_script(self):
        """chain 中 block=True 的脚本应以 block=True 运行。"""
        with mock.patch("src.gui.runner.run_chain_command", return_value=0) as rc, \
             mock.patch.object(ScriptChainRunner, "_resolve_script_specs", return_value=[(0, True)]):
            ScriptChainRunner("88").run()
        self.assertEqual(rc.call_args.kwargs["block"], True)


if __name__ == '__main__':
    unittest.main()
