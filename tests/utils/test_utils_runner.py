"""测试 src/utils_runner.py：脚本配置合法性校验与命令构造/运行。"""

import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from unittest import mock

from src.utils import get_root_dir
from src.utils.utils_runner import (
    ProcessTarget,
    build_chain_command,
    build_run_chain_command,
    build_script_command,
    collect_invalid_script_messages,
    collect_process_targets,
    kill_processes,
    run_chain_command,
    script_invalid_message,
    spawn_schedule_run,
)
from src.utils.utils_weekly import next_target_datetime
from tests.support.process_sim import SimProcess

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

    def test_required_script_path_by_type(self):
        for kind, empty, missing in (
            ("external", "脚本路径为空", f"脚本路径不存在 {self.missing}"),
            ("python", "Python 脚本路径为空", f"Python 脚本不存在 {self.missing}"),
        ):
            for path, expected in (("", empty), (self.missing, missing)):
                with self.subTest(kind=kind, path=path):
                    entry = _external_entry(script_type=kind, script_path=path)
                    self.assertEqual(script_invalid_message(entry), expected)

    def test_check_done_invalid(self):
        entry = _external_entry(script_path=self.existing, check_done="bogus")
        self.assertEqual(script_invalid_message(entry), "检查完成方式非法 bogus")

    def test_game_process_required_for_kill_or_completion_check(self):
        for kill, check in ((True, "script_closed"), (False, "game_closed")):
            with self.subTest(kill=kill, check=check):
                entry = _external_entry(
                    script_path=self.existing,
                    check_done=check,
                    kill_game_after_done=kill,
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


class TestRunChainCommandInvocation(unittest.TestCase):
    """验证 run_chain_command 整链用法正确透传到 subprocess。"""

    def test_blocking_command_preserves_environment_and_returns_signed_exit_code(self):
        for raw, expected in (
            (0, 0),
            (-1, -1),
            (-9, -9),
            (0xC0000005, -1073741819),
            (0xFFFFFFFF, -1),
            (0x80000000, -2147483648),
        ):
            with (
                self.subTest(returncode=raw),
                mock.patch("src.utils.utils_runner.subprocess.run") as run,
                mock.patch("src.utils.utils_runner.subprocess.Popen") as popen,
            ):
                run.return_value.returncode = raw
                self.assertEqual(run_chain_command(CHAIN_PATH), expected)
                run.assert_called_once()
                popen.assert_not_called()
                self.assertEqual(
                    run.call_args.args[0],
                    [
                        sys.executable,
                        "-m",
                        "src.runner.launcher",
                        "--chain",
                        CHAIN_PATH,
                    ],
                )
                self.assertEqual(run.call_args.kwargs["cwd"], get_root_dir())
                self.assertIn(
                    os.path.join("src", "runner"),
                    run.call_args.kwargs["env"]["PYTHONPATH"],
                )


class TestNonBlocking(unittest.TestCase):
    """验证 run_chain_command 的 block 分支；block=False 以 Popen 即起即返。"""

    def test_nonblock_uses_popen_and_returns_zero(self):
        with (
            mock.patch("src.utils.utils_runner.subprocess.run") as run,
            mock.patch("src.utils.utils_runner.subprocess.Popen") as popen,
            mock.patch("src.utils.utils_runner.time.sleep"),
        ):
            rc = run_chain_command(CHAIN_PATH, block=False)
        self.assertEqual(rc, 0)
        popen.assert_called_once()
        run.assert_not_called()
        _, kwargs = popen.call_args
        self.assertEqual(kwargs["stdout"], subprocess.DEVNULL)
        self.assertEqual(kwargs["stderr"], subprocess.DEVNULL)


class TestBuildChainCommandFrozen(unittest.TestCase):
    """验证 PyInstaller 冻结模式下 build_chain_command 调用同目录 Runner exe。

    不需要实际的 exe 文件——通过 mock sys.frozen 和 sys.executable 模拟冻结环境。
    """

    FAKE_EXE = os.path.join(os.sep, "app", "OneDragon-Helper.exe")
    EXPECTED_RUNNER = os.path.join(os.sep, "app", "OneDragon-Helper-Runner.exe")

    def test_frozen_command_uses_sibling_runner_and_inherits_environment(self):
        with (
            mock.patch("sys.frozen", True, create=True),
            mock.patch("sys.executable", self.FAKE_EXE),
        ):
            command, cwd, env = build_chain_command(CHAIN_PATH)
        self.assertEqual(command, [self.EXPECTED_RUNNER, "--chain", CHAIN_PATH])
        self.assertEqual(cwd, os.path.dirname(self.FAKE_EXE))
        self.assertIsNone(env)


class TestBuildScriptInvocationFrozen(unittest.TestCase):
    """验证 build_script_command(["--script", ...]) 在 frozen/非 frozen 下一致。

    不需要实际的 exe 文件——通过 mock sys.frozen 和 sys.executable 模拟冻结环境。
    """

    FAKE_EXE = os.path.join(os.sep, "app", "OneDragon-Helper.exe")
    EXPECTED_RUNNER = os.path.join(os.sep, "app", "OneDragon-Helper-Runner.exe")
    SCRIPT = "D:/scripts/foo.py"

    def test_frozen_script_command_and_environment(self):
        with (
            mock.patch("sys.frozen", True, create=True),
            mock.patch("sys.executable", self.FAKE_EXE),
        ):
            command, cwd, env = build_script_command(["--script", self.SCRIPT])
        self.assertEqual(command, [self.EXPECTED_RUNNER, "--script", self.SCRIPT])
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

    关机不再经此（改由 service 的 post_run 在全部运行结束后触发，见 src.utils.utils_shutdown）；
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
            "src.utils.utils_runner.build_script_command",
            return_value=(["/app/pythonw.exe", "--chain", CHAIN_PATH], "/app", None),
        ):
            command, cwd, env = build_run_chain_command(CHAIN_PATH)
        self.assertEqual(command[0], "/app/python.exe")
        self.assertNotIn("pythonw.exe", command[0])


class TestKillProcesses(unittest.TestCase):
    """kill_processes：按匹配条件终止进程及其子进程树，安全跳过无关/已退出进程。"""

    def _patch_iter(self, procs):
        # side_effect 而非 return_value：匹配与建树各遍历一次，需每次返回新迭代器。
        return mock.patch(
            "src.utils.utils_runner.psutil.process_iter",
            side_effect=lambda *a, **k: iter(list(procs)),
        )

    def _patch_wait(self, gone, alive):
        return mock.patch(
            "src.utils.utils_runner.psutil.wait_procs", return_value=(gone, alive)
        )

    def test_empty_targets_no_iteration(self):
        with self._patch_iter([SimProcess("x.exe")]) as mock_iter:
            # 列表为空时立即返回空列表，且不遍历进程。
            self.assertEqual(kill_processes([]), [])
        mock_iter.assert_not_called()

    def test_terminates_matching_case_insensitive(self):
        target = SimProcess("GAME.EXE")
        other = SimProcess("unrelated.exe")
        with (
            self._patch_iter([other, target]),
            self._patch_wait([target], []),
        ):
            killed = kill_processes([ProcessTarget(name="game.exe")])
        self.assertEqual(killed, [f"GAME.EXE({target.pid})"])
        self.assertTrue(target.terminated)
        self.assertFalse(other.terminated)

    def test_matches_cmdline_substring_case_insensitive(self):
        # 启动器真身：进程名是通用解释器，只能靠命令行里的安装根目录识别。
        worker = SimProcess(
            "pythonw.exe",
            cmdline=[r"D:\ok\python\pythonw.exe", r"D:\ok\working\main.py"],
        )
        other = SimProcess("pythonw.exe", cmdline=[r"D:\other\main.py"])
        with (
            self._patch_iter([other, worker]),
            self._patch_wait([worker], []),
        ):
            killed = kill_processes([ProcessTarget(cmdline_contains=r"D:\ok")])
        self.assertEqual(killed, [f"pythonw.exe({worker.pid})"])
        self.assertTrue(worker.terminated)
        self.assertFalse(other.terminated)

    def test_kill_when_wait_timeout(self):
        # wait_procs 超时后仍存活的进程 → 强制 kill。
        target = SimProcess("game.exe")
        with (
            self._patch_iter([target]),
            self._patch_wait([], [target]),
        ):
            killed = kill_processes([ProcessTarget(name="game.exe")])
        self.assertEqual(killed, [f"game.exe({target.pid})"])
        self.assertTrue(target.killed)

    def test_cmdline_fetched_once_per_process(self):
        # cmdline() 约 5.9ms/进程，是唯一昂贵调用：每条匹配条件各取一次会让开销
        # 随条件数线性增长（8 条 cmdline 条件 × 349 进程 ≈ 16s）。
        worker = SimProcess("pythonw.exe", cmdline=[r"D:\ok\main.py"])
        with (
            self._patch_iter([worker]),
            self._patch_wait([worker], []),
        ):
            kill_processes([ProcessTarget(cmdline_contains=r"D:\ok")] * 3)
        self.assertEqual(worker.cmdline_calls, 1)

    def test_cmdline_skipped_when_name_matches(self):
        # name 型条件命中即短路，不再付出 cmdline 的系统调用成本。
        target = SimProcess("game.exe", cmdline=[r"D:\x\y"])
        with (
            self._patch_iter([target]),
            self._patch_wait([target], []),
        ):
            kill_processes(
                [
                    ProcessTarget(name="game.exe"),
                    ProcessTarget(cmdline_contains=r"D:\x"),
                ]
            )
        self.assertEqual(target.cmdline_calls, 0)

    def test_scan_count_independent_of_match_count(self):
        # 全系统遍历固定 2 次（匹配 1 + 建树 1），与命中进程数无关——
        # 旧实现按命中进程逐个 children()，命中 k 个就是 k 遍全量遍历。
        roots = [SimProcess(f"r{i}.exe") for i in range(3)]
        with (
            self._patch_iter(roots) as mock_iter,
            self._patch_wait(roots, []),
        ):
            kill_processes([ProcessTarget(name=f"r{i}.exe") for i in range(3)])
        self.assertEqual(mock_iter.call_count, 2)

    def test_no_match_returns_empty(self):
        with self._patch_iter([SimProcess("other.exe")]):
            self.assertEqual(kill_processes([ProcessTarget(name="game.exe")]), [])


class TestCollectProcessTargets(unittest.TestCase):
    """collect_process_targets：脚本进程 + 启动器真身(cmdline) + 游戏进程，去重。"""

    def test_exe_script_and_game_and_root_cmdline(self):
        script = {
            "display_name": "A",
            "script_process_name": "ABot.exe",
            "script_path": "C:/x/run.exe",
            "game_process_name": "AGame.exe",
        }
        self.assertEqual(
            collect_process_targets(script),
            [
                ProcessTarget(name="ABot.exe"),
                ProcessTarget(name="run.exe"),
                ProcessTarget(cmdline_contains=r"C:\x"),
                ProcessTarget(name="AGame.exe"),
            ],
        )

    def test_python_script_still_gets_root_cmdline(self):
        # .py 形态：无独立进程名，但安装根目录仍可认出启动器拉起的真身。
        script = {"display_name": "A", "script_path": "scripts/foo.py"}
        self.assertEqual(
            collect_process_targets(script),
            [ProcessTarget(name="foo.py"), ProcessTarget(cmdline_contains="scripts")],
        )

    def test_empty_when_no_config(self):
        self.assertEqual(collect_process_targets({"display_name": "A"}), [])

    def test_dedup_case_insensitive(self):
        script = {
            "script_process_name": "Game.exe",
            "game_process_name": "game.exe",
        }
        self.assertEqual(
            collect_process_targets(script), [ProcessTarget(name="Game.exe")]
        )


class TestNextTargetDatetime(unittest.TestCase):
    """next_target_datetime：今天未到取今天，已过取明天（跨午夜）；HH:MM 与 HH:MM:SS 等价。"""

    def test_next_occurrence_is_strictly_after_now(self):
        for now, target, expected in (
            ("07:00", "08:00", "2026-08-23 08:00"),
            ("09:00", "08:00", "2026-08-24 08:00"),
            ("08:00", "08:00", "2026-08-24 08:00"),
            ("08:00:10", "08:00:30", "2026-08-23 08:00:30"),
            ("08:00:40", "08:00:30", "2026-08-24 08:00:30"),
        ):
            with self.subTest(now=now, target=target):
                self.assertEqual(
                    next_target_datetime(
                        target, now=datetime.fromisoformat(f"2026-08-23 {now}")
                    ),
                    datetime.fromisoformat(expected),
                )

    def test_invalid_segment_count(self):
        with self.assertRaises(AssertionError):
            next_target_datetime("08:00:30:00")


class TestSpawnScheduleRun(unittest.TestCase):
    """开发与冻结入口均使用 launcher；时刻经 --schedule-run 传入。"""

    def _capture_command(self, *, enabled_keys, frozen=False, **kwargs):
        """调用 spawn_schedule_run 并返回实际拼出的命令列表。"""
        with (
            mock.patch("subprocess.Popen", return_value=mock.MagicMock()) as popen_mock,
            mock.patch.object(sys, "frozen", frozen, create=True),
        ):
            spawn_schedule_run(enabled_keys, "08:00", **kwargs)
        return popen_mock.call_args.args[0]

    def test_schedule_command_preserves_entrypoint_and_options(self):
        cases = (
            ("named", {"chain_name": "weekend"}, "weekend", ["--close-running"]),
            (
                "actions",
                {"mute": True, "unmute": True, "shutdown_delay": 60},
                "today",
                ["--mute", "--unmute", "--close-running", "--shutdown", "60"],
            ),
            ("keep_running", {"close_running": False}, "today", []),
        )
        for frozen in (False, True):
            for name, options, chain_name, flags in cases:
                with self.subTest(frozen=frozen, name=name):
                    cmd = self._capture_command(
                        frozen=frozen, enabled_keys={"b", "a", "c"}, **options
                    )
                    entry = (
                        [sys.executable]
                        if frozen
                        else [sys.executable, "-m", "src.launcher"]
                    )
                    self.assertEqual(
                        cmd,
                        entry
                        + ["--schedule-run", "08:00", "--name", chain_name]
                        + flags
                        + ["--enable", "a,b,c"],
                    )

    def test_enable_none_raises(self):
        """enabled_keys 必须显式传入具体集合；None 是契约错误（不再表示『全部』）。"""
        with self.assertRaises(AssertionError):
            self._capture_command(frozen=False, enabled_keys=None)


if __name__ == "__main__":
    unittest.main()
