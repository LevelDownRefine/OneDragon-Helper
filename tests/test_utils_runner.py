"""测试 src/utils_runner.py：脚本配置合法性校验与命令构造/运行。"""

import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from src.utils import get_root_dir
from src.utils_runner import (
    _to_signed_32,
    build_chain_command,
    build_script_command,
    build_shutdown_extra_args,
    collect_invalid_script_messages,
    run_chain_command,
    script_invalid_message,
)

CHAIN_PATH = "config/script_chain/01.yml"


def _external_entry(**overrides):
    entry = {
        "display_name": "测试脚本",
        "script_type": "external",
        "script_path": "",
        "script_process_name": [],
        "game_process_name": "",
        "launcher_mode": False,
        "run_timeout_seconds": 3600,
        "check_done": "script_closed",
        "kill_script_after_done": True,
        "kill_game_after_done": False,
    }
    entry.update(overrides)
    return entry


class TestScriptInvalidMessage(unittest.TestCase):
    """script_invalid_message：各分支与 runner invalid_message 对齐"""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.existing = os.path.join(self.tmp_dir.name, "run.bat")
        with open(self.existing, "w", encoding="utf-8") as f:
            f.write("@echo off\n")
        self.missing = os.path.join(self.tmp_dir.name, "missing.bat")

    def test_external_valid(self):
        entry = _external_entry(script_path=self.existing)
        self.assertIsNone(script_invalid_message(entry))

    def test_external_path_empty(self):
        self.assertEqual(
            script_invalid_message(_external_entry(script_path="")), "脚本路径为空"
        )

    def test_external_path_missing(self):
        entry = _external_entry(script_path=self.missing)
        self.assertEqual(
            script_invalid_message(entry), f"脚本路径不存在 {self.missing}"
        )

    def test_python_path_empty(self):
        entry = _external_entry(script_type="python", script_path="")
        self.assertEqual(script_invalid_message(entry), "Python 脚本路径为空")

    def test_python_path_missing(self):
        entry = _external_entry(script_type="python", script_path=self.missing)
        self.assertEqual(
            script_invalid_message(entry), f"Python 脚本不存在 {self.missing}"
        )

    def test_check_done_invalid(self):
        entry = _external_entry(script_path=self.existing, check_done="bogus")
        self.assertEqual(script_invalid_message(entry), "检查完成方式非法 bogus")

    def test_game_process_name_empty_when_kill_game(self):
        """kill_game_after_done=True 但 game_process_name 为空 → 游戏进程名称为空"""
        entry = _external_entry(
            script_path=self.existing,
            check_done="script_closed",
            kill_game_after_done=True,
            game_process_name="",
        )
        self.assertEqual(script_invalid_message(entry), "游戏进程名称为空")

    def test_game_process_name_required_by_check_done(self):
        """check_done=game_closed 但 game_process_name 为空 → 游戏进程名称为空"""
        entry = _external_entry(
            script_path=self.existing,
            check_done="game_closed",
            kill_game_after_done=False,
            game_process_name="",
        )
        self.assertEqual(script_invalid_message(entry), "游戏进程名称为空")

    def test_game_process_name_filled_ok(self):
        entry = _external_entry(
            script_path=self.existing,
            check_done="game_closed",
            kill_game_after_done=False,
            game_process_name="Game.exe",
        )
        self.assertIsNone(script_invalid_message(entry))

    def test_launcher_mode_script_process_empty(self):
        entry = _external_entry(
            script_path=self.existing,
            launcher_mode=True,
            script_process_name=[],
            check_done="script_closed",
            kill_script_after_done=True,
        )
        self.assertEqual(script_invalid_message(entry), "启动后实际运行的程序为空")

    def test_launcher_mode_script_process_contains_launcher(self):
        launcher = os.path.join(self.tmp_dir.name, "launcher.exe")
        with open(launcher, "w", encoding="utf-8") as f:
            f.write("MZ")
        entry = _external_entry(
            script_path=launcher,
            launcher_mode=True,
            script_process_name=["launcher.exe"],
            check_done="script_closed",
        )
        self.assertEqual(
            script_invalid_message(entry),
            "启动后实际运行的程序不能包含启动程序本体 launcher.exe",
        )

    def test_run_timeout_seconds_le_zero(self):
        entry = _external_entry(script_path=self.existing, run_timeout_seconds=0)
        self.assertEqual(script_invalid_message(entry), "运行超时时间必须大于0")

    def test_run_timeout_missing_uses_default(self):
        """缺 run_timeout_seconds 时按 runner 默认 3600 处理，不误报。"""
        entry = _external_entry(script_path=self.existing)
        entry.pop("run_timeout_seconds", None)
        self.assertIsNone(script_invalid_message(entry))


class TestCollectInvalidScriptMessages(unittest.TestCase):
    """collect_invalid_script_messages：仅返回不合法项"""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.existing = os.path.join(self.tmp_dir.name, "run.bat")
        with open(self.existing, "w", encoding="utf-8") as f:
            f.write("@echo off\n")

    def test_mixed_list_returns_only_invalid(self):
        good = _external_entry(display_name="好脚本", script_path=self.existing)
        bad = _external_entry(
            display_name="坏脚本",
            script_path="",
            kill_game_after_done=True,
        )
        result = collect_invalid_script_messages([good, bad])
        self.assertEqual(result, [("坏脚本", "脚本路径为空")])

    def test_all_valid_returns_empty(self):
        good = _external_entry(script_path=self.existing)
        self.assertEqual(collect_invalid_script_messages([good]), [])


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
    """验证 run_chain_command 整链用法正确透传到 subprocess。"""

    def test_whole_chain_passed_to_subprocess(self):
        with mock.patch("src.utils_runner.subprocess.run") as run:
            run.return_value.returncode = 0
            rc = run_chain_command(CHAIN_PATH)
        self.assertEqual(rc, 0)
        command = run.call_args.args[0]
        self.assertIn("--chain", command)
        self.assertIn(CHAIN_PATH, command)
        self.assertNotIn("--debug-index", command)
        self.assertEqual(run.call_args.kwargs["cwd"], get_root_dir())
        self.assertIn(
            os.path.join("src", "runner"), run.call_args.kwargs["env"]["PYTHONPATH"]
        )

    def test_large_returncode_clamped_to_signed(self):
        """大无符号退出码（>=2^31）在出口被 clamp，供 Qt Signal(int) 直接 emit。"""
        with mock.patch("src.utils_runner.subprocess.run") as run:
            run.return_value.returncode = 0xC0000005
            rc = run_chain_command(CHAIN_PATH)
        self.assertEqual(rc, -1073741819)


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


class TestNonBlocking(unittest.TestCase):
    """验证 run_chain_command 的 block 分支；block=False 以 Popen 即起即返。"""

    def test_nonblock_uses_popen_and_returns_zero(self):
        with (
            mock.patch("src.utils_runner.subprocess.run") as run,
            mock.patch("src.utils_runner.subprocess.Popen") as popen,
        ):
            rc = run_chain_command(CHAIN_PATH, block=False)
        self.assertEqual(rc, 0)
        popen.assert_called_once()
        run.assert_not_called()
        _, kwargs = popen.call_args
        self.assertEqual(kwargs["stdout"], subprocess.DEVNULL)
        self.assertEqual(kwargs["stderr"], subprocess.DEVNULL)

    def test_block_true_uses_subprocess_run(self):
        with (
            mock.patch("src.utils_runner.subprocess.run") as run,
            mock.patch("src.utils_runner.subprocess.Popen") as popen,
        ):
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
        with (
            mock.patch("sys.frozen", True, create=True),
            mock.patch("sys.executable", self.FAKE_EXE),
        ):
            command, cwd, env = build_chain_command(CHAIN_PATH)
        # 命令首元素应是 Runner exe，而非 sys.executable（Python 解释器）
        self.assertEqual(command[0], self.EXPECTED_RUNNER)
        self.assertNotIn("-m", command)
        self.assertNotIn("src.runner.launcher", command)

    def test_frozen_passes_chain_arg(self):
        with (
            mock.patch("sys.frozen", True, create=True),
            mock.patch("sys.executable", self.FAKE_EXE),
        ):
            command, cwd, env = build_chain_command(CHAIN_PATH)
        self.assertIn("--chain", command)
        self.assertIn(CHAIN_PATH, command)
        self.assertNotIn("--debug-index", command)

    def test_frozen_cwd_is_exe_dir(self):
        with (
            mock.patch("sys.frozen", True, create=True),
            mock.patch("sys.executable", self.FAKE_EXE),
        ):
            command, cwd, env = build_chain_command(CHAIN_PATH)
        self.assertEqual(cwd, os.path.dirname(self.FAKE_EXE))

    def test_frozen_env_is_none(self):
        """冻结模式下 env=None，让 subprocess 继承父进程环境（不丢 PATH 等）。"""
        with (
            mock.patch("sys.frozen", True, create=True),
            mock.patch("sys.executable", self.FAKE_EXE),
        ):
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
        with (
            mock.patch("sys.frozen", True, create=True),
            mock.patch("sys.executable", self.FAKE_EXE),
        ):
            command, cwd, env = build_script_command(["--script", self.SCRIPT])
        self.assertEqual(command[0], self.EXPECTED_RUNNER)
        self.assertEqual(command[1], "--script")
        self.assertEqual(command[2], self.SCRIPT)
        self.assertNotIn("-m", command)
        self.assertNotIn("src.runner.launcher", command)

    def test_frozen_cwd_is_exe_dir_and_env_none(self):
        with (
            mock.patch("sys.frozen", True, create=True),
            mock.patch("sys.executable", self.FAKE_EXE),
        ):
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


class TestBuildShutdownExtraArgs(unittest.TestCase):
    """build_shutdown_extra_args：按 config 生成 --shutdown 参数。"""

    def test_missing_field_returns_empty(self):
        self.assertEqual(build_shutdown_extra_args({}), [])

    def test_zero_delay_returns_empty(self):
        self.assertEqual(build_shutdown_extra_args({"shutdown_delay_seconds": 0}), [])

    def test_negative_delay_returns_empty(self):
        self.assertEqual(build_shutdown_extra_args({"shutdown_delay_seconds": -1}), [])

    def test_non_int_delay_returns_empty(self):
        self.assertEqual(
            build_shutdown_extra_args({"shutdown_delay_seconds": "45"}), []
        )

    def test_positive_delay_returns_shutdown_flag(self):
        self.assertEqual(
            build_shutdown_extra_args({"shutdown_delay_seconds": 45}),
            ["--shutdown", "45"],
        )

    def test_switch_explicit_false_disables_shutdown(self):
        self.assertEqual(
            build_shutdown_extra_args(
                {"shutdown_after_run": False, "shutdown_delay_seconds": 45}
            ),
            [],
        )

    def test_switch_explicit_true_enables_shutdown(self):
        self.assertEqual(
            build_shutdown_extra_args(
                {"shutdown_after_run": True, "shutdown_delay_seconds": 45}
            ),
            ["--shutdown", "45"],
        )

    def test_switch_non_bool_disables_shutdown(self):
        self.assertEqual(
            build_shutdown_extra_args(
                {"shutdown_after_run": "false", "shutdown_delay_seconds": 45}
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
