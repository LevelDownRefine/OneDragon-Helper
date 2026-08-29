"""测试 src/utils_runner.py：脚本配置合法性校验与命令构造/运行。"""

import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from unittest import mock

import psutil

from src.utils import get_root_dir
from src.utils_runner import (
    _collect_process_names,
    _to_signed_32,
    apply_mute_config,
    apply_shutdown_config,
    apply_timed_run_config,
    build_chain_command,
    build_run_chain_command,
    build_script_command,
    collect_invalid_script_messages,
    kill_processes_by_names,
    parse_mute_run,
    parse_shutdown,
    parse_timed_run,
    run_chain_command,
    script_invalid_message,
    spawn_schedule_run,
)
from src.utils_weekly import next_target_datetime

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


class TestBuildRunChainCommand(unittest.TestCase):
    """build_run_chain_command：构造脚本链启动命令（GUI 不再拼命令）。

    关机不再经此（改由 service 的 post_run 在全部运行结束后触发，见 src.utils_shutdown）；
    静音由主仓在 pre_run/post_run 直接操作系统音频，不再透传 --mute 给 runner。
    """

    def test_plain_chain_no_extra_flags(self):
        command, cwd, env = build_run_chain_command(CHAIN_PATH)
        self.assertIn("--chain", command)
        self.assertIn(CHAIN_PATH, command)
        self.assertNotIn("--shutdown", command)
        self.assertNotIn("--mute", command)

    def test_pythonw_replaced_with_python(self):
        """冻结态 GUI exe 若为 pythonw.exe，应替换为 python.exe 以保证子进程控制台。"""
        with mock.patch(
            "src.utils_runner.build_script_command",
            return_value=(["/app/pythonw.exe", "--chain", CHAIN_PATH], "/app", None),
        ):
            command, cwd, env = build_run_chain_command(CHAIN_PATH)
        self.assertEqual(command[0], "/app/python.exe")
        self.assertNotIn("pythonw.exe", command[0])


class TestParseShutdown(unittest.TestCase):
    """parse_shutdown：config 的 shutdown 嵌套配置 -> 延迟秒数（None 表示不关机）。

    after_run 默认 False，delay 须为正整型，否则 None（不关机）。
    供 GUI 读取延迟秒数后作为 post_run 关机步骤（见 src.utils_shutdown）。
    """

    def test_missing_field_returns_none(self):
        self.assertIsNone(parse_shutdown({}))

    def test_after_run_default_false(self):
        self.assertIsNone(parse_shutdown({"shutdown": {"delay_seconds": 45}}))

    def test_zero_delay_returns_none(self):
        self.assertIsNone(
            parse_shutdown({"shutdown": {"after_run": True, "delay_seconds": 0}})
        )

    def test_negative_delay_returns_none(self):
        self.assertIsNone(
            parse_shutdown({"shutdown": {"after_run": True, "delay_seconds": -1}})
        )

    def test_non_int_delay_returns_none(self):
        self.assertIsNone(
            parse_shutdown({"shutdown": {"after_run": True, "delay_seconds": "45"}})
        )

    def test_positive_delay_returns_int(self):
        self.assertEqual(
            parse_shutdown({"shutdown": {"after_run": True, "delay_seconds": 45}}), 45
        )

    def test_switch_explicit_false_returns_none(self):
        self.assertIsNone(
            parse_shutdown({"shutdown": {"after_run": False, "delay_seconds": 45}})
        )

    def test_switch_non_bool_returns_none(self):
        self.assertIsNone(
            parse_shutdown({"shutdown": {"after_run": "false", "delay_seconds": 45}})
        )


class _FakeProc:
    """模拟 psutil.Process：记录 terminate/wait/kill 调用，name() 返回预设名。"""

    def __init__(self, name, on_wait_raise=None):
        self._name = name
        self.terminated = False
        self.killed = False
        self._on_wait_raise = on_wait_raise

    def name(self):
        return self._name

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        if self._on_wait_raise is not None:
            raise self._on_wait_raise
        return 0

    def kill(self):
        self.killed = True


class TestKillProcessesByNames(unittest.TestCase):
    """kill_processes_by_names：优雅终止匹配的进程，安全跳过无关/已退出进程。"""

    def _patch_iter(self, procs):
        return mock.patch(
            "src.utils_runner.psutil.process_iter", return_value=iter(procs)
        )

    def test_empty_names_no_iteration(self):
        with self._patch_iter([_FakeProc("x.exe")]) as mock_iter:
            # 列表为空时立即返回 0，且不遍历进程。
            self.assertEqual(kill_processes_by_names([]), 0)
        mock_iter.assert_not_called()

    def test_terminates_matching_case_insensitive(self):
        target = _FakeProc("GAME.EXE")
        other = _FakeProc("unrelated.exe")
        with self._patch_iter([other, target]):
            killed = kill_processes_by_names("game.exe")
        self.assertEqual(killed, 1)
        self.assertTrue(target.terminated)
        self.assertFalse(other.terminated)

    def test_kill_on_wait_timeout(self):
        # wait 超时（TimeoutExpired）→ 退化为 kill。
        target = _FakeProc(
            "game.exe", on_wait_raise=psutil.TimeoutExpired("game.exe", 3)
        )
        with self._patch_iter([target]):
            killed = kill_processes_by_names(["game.exe"])
        self.assertEqual(killed, 1)
        self.assertTrue(target.killed)

    def test_no_match_returns_zero(self):
        with self._patch_iter([_FakeProc("other.exe")]):
            self.assertEqual(kill_processes_by_names(["game.exe"]), 0)


class TestCollectProcessNames(unittest.TestCase):
    """_collect_process_names：汇总脚本自身进程 + 游戏进程，去重。"""

    def test_exe_script_and_game(self):
        script = {
            "display_name": "A",
            "script_process_name": "ABot.exe",
            "script_path": "C:/x/run.exe",
            "game_process_name": "AGame.exe",
        }
        self.assertEqual(
            _collect_process_names(script),
            ["ABot.exe", "run.exe", "AGame.exe"],
        )

    def test_python_script_path_is_noop_name(self):
        # .py 形态：script_path 文件名不会匹配 python.exe，仅作占位。
        script = {"display_name": "A", "script_path": "scripts/foo.py"}
        self.assertEqual(_collect_process_names(script), ["foo.py"])

    def test_empty_when_no_names(self):
        self.assertEqual(_collect_process_names({"display_name": "A"}), [])

    def test_dedup_case_insensitive(self):
        script = {
            "script_process_name": "Game.exe",
            "game_process_name": "game.exe",
        }
        self.assertEqual(_collect_process_names(script), ["Game.exe"])


if __name__ == "__main__":
    unittest.main()


class TestApplyShutdownConfig(unittest.TestCase):
    """apply_shutdown_config：启用/关闭都直接落盘完整块。"""

    def test_enabled_writes_after_run_and_delay(self):
        data: dict = {}
        apply_shutdown_config(data, enabled=True, delay_seconds=120)
        self.assertEqual(data["shutdown"], {"after_run": True, "delay_seconds": 120})

    def test_disabled_writes_after_run_and_delay(self):
        # 关闭也落盘：delay_seconds 以弹窗给定值原样写入，行为单一稳定。
        data: dict = {}
        apply_shutdown_config(data, enabled=False, delay_seconds=45)
        self.assertEqual(data["shutdown"], {"after_run": False, "delay_seconds": 45})


class TestApplyTimedRunConfig(unittest.TestCase):
    """apply_timed_run_config：原地写回顶层 timed_run 映射。"""

    def test_enabled_writes_valid_target(self):
        data: dict = {}
        apply_timed_run_config(data, enabled=True, target_time="04:10")
        self.assertEqual(data["timed_run"], {"enabled": True, "target_time": "04:10"})

    def test_disabled_drops_target_to_empty(self):
        data = {"timed_run": {"enabled": True, "target_time": "08:00"}}
        apply_timed_run_config(data, enabled=False, target_time="08:00")
        self.assertEqual(data["timed_run"], {"enabled": False, "target_time": ""})

    def test_enabled_with_illegal_target_falls_back(self):
        data: dict = {}
        apply_timed_run_config(data, enabled=True, target_time="25:99")
        self.assertEqual(data["timed_run"], {"enabled": True, "target_time": "04:10"})


class TestParseTimedRun(unittest.TestCase):
    """parse_timed_run：缺失/非法配置安全降级。

    统一经 ruamel（YAML 1.2）读写 config.yml，target_time 始终为字符串，
    无需再处理 PyYAML 1.1 把 08:00 误成 480.0 的旧兼容分支。
    """

    def test_disabled_when_missing_block(self):
        self.assertEqual(parse_timed_run({"script_list": []}), (False, None))

    def test_disabled_when_enabled_false(self):
        cfg = {"timed_run": {"enabled": False, "target_time": "08:00"}}
        self.assertEqual(parse_timed_run(cfg), (False, None))

    def test_enabled_with_valid_time(self):
        cfg = {"timed_run": {"enabled": True, "target_time": "08:30"}}
        self.assertEqual(parse_timed_run(cfg), (True, "08:30"))

    def test_illegal_time_string_degrades(self):
        cfg = {"timed_run": {"enabled": True, "target_time": "25:99"}}
        self.assertEqual(parse_timed_run(cfg), (False, None))

    def test_numeric_target_degrades(self):
        """ruamel 下 target_time 不会是数值；若配置损坏出现数值则安全降级。"""
        cfg = {"timed_run": {"enabled": True, "target_time": 480.0}}
        self.assertEqual(parse_timed_run(cfg), (False, None))


class TestNextTargetDatetime(unittest.TestCase):
    """next_target_datetime：今天未到取今天，已过取明天（跨午夜）。"""

    def test_later_today(self):
        now = datetime(2026, 8, 23, 7, 0)
        self.assertEqual(
            next_target_datetime("08:00", now=now),
            datetime(2026, 8, 23, 8, 0),
        )

    def test_already_passed_rolls_to_tomorrow(self):
        now = datetime(2026, 8, 23, 9, 0)
        self.assertEqual(
            next_target_datetime("08:00", now=now),
            datetime(2026, 8, 24, 8, 0),
        )

    def test_exactly_now_runs_tomorrow(self):
        now = datetime(2026, 8, 23, 8, 0)
        self.assertEqual(
            next_target_datetime("08:00", now=now),
            datetime(2026, 8, 24, 8, 0),
        )


class TestSpawnScheduleRun(unittest.TestCase):
    """spawn_schedule_run：子进程命令拼装（dev / frozen 两种入口，参数透传）。

    本类是对「定时计划闪退」回归的护栏：命令必须走与 GUI 相同的入口
    （开发态 ``python -m src.launcher`` / 冻结态 ``sys.executable``），且目标时刻
    须作为 ``--schedule-run`` 的参数（**不是** ``--at``），否则子进程会被 argparse
    拒掉而一启动就退出。此前缺失该测试，导致命令拼写错误未被任何用例捕获。
    """

    def _capture_command(self, *, frozen=False, enabled_keys="today", **kwargs):
        """调用 spawn_schedule_run 并返回实际拼出的命令列表。"""
        with (
            mock.patch("subprocess.Popen", return_value=mock.MagicMock()) as popen_mock,
            mock.patch.object(sys, "frozen", frozen, create=True),
        ):
            spawn_schedule_run(enabled_keys, "08:00", **kwargs)
        return popen_mock.call_args.args[0]

    def test_dev_entry_uses_src_launcher(self):
        cmd = self._capture_command(frozen=False)
        self.assertEqual(cmd[0], sys.executable)
        self.assertEqual(cmd[1:3], ["-m", "src.launcher"])
        self.assertIn("--schedule-run", cmd)
        self.assertNotIn("src.cli", cmd)  # 入口必须是 launcher，不是 cli 模块

    def test_frozen_entry_uses_exe_directly(self):
        cmd = self._capture_command(frozen=True)
        self.assertEqual(cmd[0], sys.executable)
        # 冻结态无 ``-m src.launcher``，直接复用 exe（其入口即 launcher.main）。
        self.assertNotIn("-m", cmd)
        self.assertNotIn("src.launcher", cmd)

    def test_target_time_is_schedule_run_value(self):
        cmd = self._capture_command(frozen=False)
        idx = cmd.index("--schedule-run")
        self.assertEqual(cmd[idx + 1], "08:00")  # 目标时刻是 --schedule-run 的值
        self.assertNotIn("--at", cmd)  # ← 曾用 --at 导致 argparse 拒掉而闪退

    def test_name_flag(self):
        cmd = self._capture_command(frozen=False, chain_name="weekend")
        idx = cmd.index("--name")
        self.assertEqual(cmd[idx + 1], "weekend")

    def test_mute_and_shutdown_passthrough(self):
        cmd = self._capture_command(frozen=False, mute=True, shutdown_delay=60)
        self.assertIn("--mute", cmd)
        idx = cmd.index("--shutdown")
        self.assertEqual(cmd[idx + 1], "60")

    def test_close_running_passthrough(self):
        # 默认启用 → 透传 --close-running；显式关闭 → 不传。
        cmd_on = self._capture_command(frozen=False, close_running=True)
        self.assertIn("--close-running", cmd_on)
        cmd_off = self._capture_command(frozen=False, close_running=False)
        self.assertNotIn("--close-running", cmd_off)

    def test_enable_sorted_comma_joined(self):
        cmd = self._capture_command(frozen=False, enabled_keys={"b", "a", "c"})
        idx = cmd.index("--enable")
        self.assertEqual(cmd[idx + 1], "a,b,c")  # 排序后逗号连接

    def test_enable_none_raises(self):
        """enabled_keys 必须显式传入具体集合；None 是契约错误（不再表示『全部』）。"""
        with self.assertRaises(AssertionError):
            self._capture_command(frozen=False, enabled_keys=None)


class TestMuteConfig(unittest.TestCase):
    """parse_mute_run / apply_mute_config：顶层 mute 映射读写。"""

    def test_parse_enabled(self):
        self.assertTrue(parse_mute_run({"mute": {"enabled": True}}))

    def test_parse_missing_block_disabled(self):
        self.assertFalse(parse_mute_run({"script_list": []}))

    def test_parse_non_bool_disabled(self):
        self.assertFalse(parse_mute_run({"mute": {"enabled": "yes"}}))

    def test_apply_writes_enabled(self):
        data: dict = {}
        apply_mute_config(data, enabled=True)
        self.assertEqual(data["mute"], {"enabled": True})

    def test_apply_disabled(self):
        data = {"mute": {"enabled": True}}
        apply_mute_config(data, enabled=False)
        self.assertEqual(data["mute"], {"enabled": False})
