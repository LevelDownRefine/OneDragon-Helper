"""测试 src/gui/runner.py：命令构造、run_chain_command 的整链/调试调用、运行线程。"""
import os
import subprocess
import sys
import unittest
from unittest import mock

# 在导入 PySide6 之前设置 offscreen 平台插件（CI 无显示器环境）
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from src.gui.runner import (
    ScriptChainRunner,
    build_script_command,
    _to_signed_32,
    build_chain_command,
    run_chain_command,
)
from src.utils import get_root_dir

CHAIN_PATH = "config/script_chain/01.yml"
CHAIN_PATH_ABS = os.path.join(get_root_dir(), CHAIN_PATH)


class TestBuildChainCommand(unittest.TestCase):
    """验证整链命令构造：用 sys.executable -m src.runner.launcher --chain <路径>。"""

    def test_whole_chain_command_shape(self):
        command, cwd, env = build_chain_command(CHAIN_PATH)
        self.assertEqual(command[0], sys.executable)
        self.assertIn("-m", command)
        self.assertIn("src.runner.launcher", command)
        self.assertIn("--chain", command)
        self.assertIn(CHAIN_PATH, command)
        self.assertNotIn("--debug-index", command)
        self.assertEqual(cwd, get_root_dir())
        self.assertIn(os.path.join("src", "runner"), env["PYTHONPATH"])


class TestRunChainCommandInvocation(unittest.TestCase):
    """验证 run_chain_command 整链/调试两种用法都正确透传到 subprocess。"""

    def test_whole_chain_passed_to_subprocess(self):
        with mock.patch("src.gui.runner.subprocess.run") as run:
            run.return_value.returncode = 0
            rc = run_chain_command(CHAIN_PATH)
        self.assertEqual(rc, 0)
        command = run.call_args.args[0]
        self.assertIn("--chain", command)
        self.assertIn(CHAIN_PATH, command)
        self.assertNotIn("--debug-index", command)
        self.assertEqual(run.call_args.kwargs["cwd"], get_root_dir())
        self.assertIn(os.path.join("src", "runner"), run.call_args.kwargs["env"]["PYTHONPATH"])


class TestScriptChainRunnerInit(unittest.TestCase):
    """验证构造参数。"""

    def test_runner_stores_chain_config_path(self):
        r = ScriptChainRunner(CHAIN_PATH)
        self.assertEqual(r.chain_config_path, CHAIN_PATH)


class TestScriptChainRunnerRun(unittest.TestCase):
    """验证 run 整链调用一次 run_chain_command；配置缺失/异常都 emit(-1)。"""

    def test_run_calls_run_chain_command_once(self):
        received = []
        with mock.patch("src.gui.runner.run_chain_command", return_value=0) as rc:
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
        with mock.patch("src.gui.runner.run_chain_command", side_effect=RuntimeError("boom")):
            r = ScriptChainRunner(CHAIN_PATH_ABS)
            r.finished_signal.connect(lambda c: received.append(c))
            r.run()
        self.assertEqual(received, [-1])


class TestToSigned32(unittest.TestCase):
    """验证 Windows 无符号 DWORD 退出码可安全转为 Qt qint32 信号值，不触发 OverflowError。"""

    def test_zero_and_negative_passthrough(self):
        self.assertEqual(_to_signed_32(0), 0)
        self.assertEqual(_to_signed_32(-1), -1)
        self.assertEqual(_to_signed_32(-9), -9)

    def test_windows_crash_code_wraps_to_negative(self):
        # 0xC0000005 = 3221225477 超过有符号 32 位上限，应回绕为 -1073741819
        self.assertEqual(_to_signed_32(0xC0000005), -1073741819)

    def test_full_dword_range(self):
        self.assertEqual(_to_signed_32(0xFFFFFFFF), -1)
        self.assertEqual(_to_signed_32(0x80000000), -2147483648)


class TestScriptChainRunnerEmitsClampedCode(unittest.TestCase):
    """验证超大无符号退出码经 clamp 后能正常 emit（不抛 OverflowError）。"""

    def test_large_unsigned_code_emitted_without_overflow(self):
        received = []
        with mock.patch("src.gui.runner.run_chain_command", return_value=0xC0000005):
            r = ScriptChainRunner(CHAIN_PATH_ABS)
            r.finished_signal.connect(lambda c: received.append(c))
            r.run()  # 此前因 emit 溢出退出码会抛 OverflowError
        self.assertEqual(received, [-1073741819])


class TestNonBlocking(unittest.TestCase):
    """验证 run_chain_command 的 block 分支；block=False 以 Popen 即起即返。"""

    def test_nonblock_uses_popen_and_returns_zero(self):
        with mock.patch("src.gui.runner.subprocess.run") as run, \
             mock.patch("src.gui.runner.subprocess.Popen") as popen:
            rc = run_chain_command(CHAIN_PATH, block=False)
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
            run_chain_command(CHAIN_PATH, block=True)
        run.assert_called_once()
        popen.assert_not_called()


class TestBuildChainCommandFrozen(unittest.TestCase):
    """验证 PyInstaller 冻结模式下 build_chain_command 调用同目录 Runner exe。

    不需要实际的 exe 文件——通过 mock sys.frozen 和 sys.executable 模拟冻结环境。
    """

    FAKE_EXE = os.path.join(os.sep, "app", "OneDragon-Helper.exe")
    EXPECTED_RUNNER = os.path.join(os.sep, "app", "OneDragon-Helper-Runner.exe")

    def test_frozen_calls_runner_exe_not_python(self):
        with mock.patch("sys.frozen", True, create=True), \
             mock.patch("sys.executable", self.FAKE_EXE):
            command, cwd, env = build_chain_command(CHAIN_PATH)
        # 命令首元素应是 Runner exe，而非 sys.executable（Python 解释器）
        self.assertEqual(command[0], self.EXPECTED_RUNNER)
        self.assertNotIn("-m", command)
        self.assertNotIn("src.runner.launcher", command)

    def test_frozen_passes_chain_arg(self):
        with mock.patch("sys.frozen", True, create=True), \
             mock.patch("sys.executable", self.FAKE_EXE):
            command, cwd, env = build_chain_command(CHAIN_PATH)
        self.assertIn("--chain", command)
        self.assertIn(CHAIN_PATH, command)
        self.assertNotIn("--debug-index", command)

    def test_frozen_cwd_is_exe_dir(self):
        with mock.patch("sys.frozen", True, create=True), \
             mock.patch("sys.executable", self.FAKE_EXE):
            command, cwd, env = build_chain_command(CHAIN_PATH)
        self.assertEqual(cwd, os.path.dirname(self.FAKE_EXE))

    def test_frozen_env_is_none(self):
        """冻结模式下 env=None，让 subprocess 继承父进程环境（不丢 PATH 等）。"""
        with mock.patch("sys.frozen", True, create=True), \
             mock.patch("sys.executable", self.FAKE_EXE):
            command, cwd, env = build_chain_command(CHAIN_PATH)
        self.assertIsNone(env)

    def test_non_frozen_unchanged(self):
        """非冻结模式行为不变：用 sys.executable -m src.runner.launcher。"""
        command, cwd, env = build_chain_command(CHAIN_PATH)
        self.assertEqual(command[0], sys.executable)
        self.assertIn("-m", command)
        self.assertIn("src.runner.launcher", command)
        self.assertIn(os.path.join("src", "runner"), env["PYTHONPATH"])


class TestBuildScriptInvocationFrozen(unittest.TestCase):
    """验证 build_script_command(["--script", ...]) 在 frozen/非 frozen 下一致。

    不需要实际的 exe 文件——通过 mock sys.frozen 和 sys.executable 模拟冻结环境。
    """

    FAKE_EXE = os.path.join(os.sep, "app", "OneDragon-Helper.exe")
    EXPECTED_RUNNER = os.path.join(os.sep, "app", "OneDragon-Helper-Runner.exe")
    SCRIPT = "D:/scripts/foo.py"

    def test_frozen_calls_runner_exe_with_script_flag(self):
        with mock.patch("sys.frozen", True, create=True), \
             mock.patch("sys.executable", self.FAKE_EXE):
            command, cwd, env = build_script_command(["--script", self.SCRIPT])
        self.assertEqual(command[0], self.EXPECTED_RUNNER)
        self.assertEqual(command[1], "--script")
        self.assertEqual(command[2], self.SCRIPT)
        self.assertNotIn("-m", command)
        self.assertNotIn("src.runner.launcher", command)

    def test_frozen_cwd_is_exe_dir_and_env_none(self):
        with mock.patch("sys.frozen", True, create=True), \
             mock.patch("sys.executable", self.FAKE_EXE):
            command, cwd, env = build_script_command(["--script", self.SCRIPT])
        self.assertEqual(cwd, os.path.dirname(self.FAKE_EXE))
        self.assertIsNone(env)

    def test_non_frozen_uses_python_minus_m(self):
        """非冻结模式：用 sys.executable -m src.runner.launcher --script <路径>。"""
        command, cwd, env = build_script_command(["--script", self.SCRIPT])
        self.assertEqual(command[0], sys.executable)
        self.assertIn("-m", command)
        self.assertIn("src.runner.launcher", command)
        self.assertIn("--script", command)
        self.assertEqual(command[command.index("--script") + 1], self.SCRIPT)
        self.assertIn(os.path.join("src", "runner"), env["PYTHONPATH"])


if __name__ == '__main__':
    unittest.main()
