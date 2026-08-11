"""测试 src/gui/runner.py：ScriptChainRunner 后台运行线程。

命令构造 / run_chain_command 等纯函数已迁至 src.utils_runner，
其测试在 tests/test_utils_runner.py。
"""

import os
import unittest
from unittest import mock

# 在导入 PySide6 之前设置 offscreen 平台插件（CI 无显示器环境）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.gui.runner import ScriptChainRunner
from src.utils import get_root_dir

CHAIN_PATH = "config/script_chain/01.yml"
CHAIN_PATH_ABS = os.path.join(get_root_dir(), CHAIN_PATH)


class TestScriptChainRunnerInit(unittest.TestCase):
    """验证构造参数。"""

    def test_runner_stores_chain_config_path(self):
        r = ScriptChainRunner(CHAIN_PATH)
        self.assertEqual(r.chain_config_path, CHAIN_PATH)


class TestScriptChainRunnerRun(unittest.TestCase):
    """验证 run 整链调用一次 run_chain_command；配置缺失/异常都 emit(-1)。"""

    def test_run_calls_run_chain_command_once(self):
        received = []
        with (
            mock.patch("src.gui.runner.os.path.exists", return_value=True),
            mock.patch("src.gui.runner.run_chain_command", return_value=0) as rc,
        ):
            r = ScriptChainRunner(CHAIN_PATH_ABS)
            r.finished_signal.connect(lambda c: received.append(c))
            r.run()
        self.assertEqual(rc.call_count, 1)
        args, kwargs = rc.call_args
        self.assertEqual(args[0], CHAIN_PATH_ABS)
        self.assertTrue(kwargs.get("block", True))
        self.assertEqual(received, [0])

    def test_run_emits_minus_one_on_missing_config(self):
        received = []
        with mock.patch("src.gui.runner.run_chain_command") as rc:
            r = ScriptChainRunner("/no/such/chain.yml")
            r.finished_signal.connect(lambda c: received.append(c))
            r.run()
        rc.assert_not_called()
        self.assertEqual(received, [-1])

    def test_run_emits_minus_one_on_exception(self):
        received = []
        with (
            mock.patch("src.gui.runner.os.path.exists", return_value=True),
            mock.patch(
                "src.gui.runner.run_chain_command", side_effect=RuntimeError("boom")
            ),
        ):
            r = ScriptChainRunner(CHAIN_PATH_ABS)
            r.finished_signal.connect(lambda c: received.append(c))
            r.run()
        self.assertEqual(received, [-1])


class TestScriptChainRunnerEmitsClampedCode(unittest.TestCase):
    """验证超大无符号退出码经 clamp 后能正常 emit（不抛 OverflowError）。"""

    def test_large_unsigned_code_emitted_without_overflow(self):
        received = []
        with (
            mock.patch("src.gui.runner.os.path.exists", return_value=True),
            mock.patch("src.gui.runner.run_chain_command", return_value=0xC0000005),
        ):
            r = ScriptChainRunner(CHAIN_PATH_ABS)
            r.finished_signal.connect(lambda c: received.append(c))
            r.run()  # 此前因 emit 溢出退出码会抛 OverflowError
        self.assertEqual(received, [-1073741819])


if __name__ == "__main__":
    unittest.main()
