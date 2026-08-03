"""测试日志解析器"""

import logging as _logging
import os
import sys
import tempfile
import unittest
from unittest import mock

import yaml

# python_script/ 位于项目根（非 src/ 下），追加根目录到 sys.path 以便导入。
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from python_script import collect_log, rerun
from python_script.collect_log import (
    BGILogParser,
    M7ALogParser,
    OkEfLogParser,
    OkNteLogParser,
    OkWwLogParser,
    ScriptLogStatus,
    ZZZLogParser,
    parse_log,
)


class TestLogParser(unittest.TestCase):
    def test_parse_ok_ef_success(self):
        parser = OkEfLogParser()
        log_content = """日常任务执行情况汇总 - 2026-07-19 21:08:34
==================================================
执行状态: 完成
执行轮数: 1"""
        self.assertEqual(parser.parse_content(log_content), ScriptLogStatus.SUCCESS)

    def test_parse_ok_ef_failed(self):
        parser = OkEfLogParser()
        log_content = """日常任务执行情况汇总 - 2026-07-19 21:08:34
==================================================
执行状态: 异常结束"""
        self.assertEqual(parser.parse_content(log_content), ScriptLogStatus.FAILED)

    def test_parse_ok_ef_exception_message(self):
        parser = OkEfLogParser()
        log_content = """日常任务执行情况汇总
异常信息: xxx"""
        self.assertEqual(parser.parse_content(log_content), ScriptLogStatus.FAILED)

    def test_parse_ok_ww_success(self):
        parser = OkWwLogParser()
        log_content = "2026-07-19 14:15:01,484 INFO TaskExecutor TaskExecutor:Successfully Executed Task"
        self.assertEqual(parser.parse_content(log_content), ScriptLogStatus.SUCCESS)

    def test_parse_ok_ww_task_completed(self):
        parser = OkWwLogParser()
        log_content = (
            "2026-07-19 14:15:01,481 INFO TaskExecutor DailyTask:Task completed"
        )
        self.assertEqual(parser.parse_content(log_content), ScriptLogStatus.SUCCESS)

    def test_parse_ok_ww_failed(self):
        parser = OkWwLogParser()
        log_content = "ERROR: Something went wrong"
        self.assertEqual(parser.parse_content(log_content), ScriptLogStatus.FAILED)

    def test_parse_m7a_success(self):
        parser = M7ALogParser()
        log_content = """2026-07-19 15:24:49,204 | INFO | 游戏终止：StarRail
------------------------------------------------------- 完成 --------------------------------------------------------
2026-07-19 15:24:50,234 | ERROR | 发生错误 [WinError 233]"""
        self.assertEqual(parser.parse_content(log_content), ScriptLogStatus.SUCCESS)

    def test_parse_m7a_failed(self):
        parser = M7ALogParser()
        log_content = """ERROR: 任务执行失败
ERROR: 另一个错误"""
        self.assertEqual(parser.parse_content(log_content), ScriptLogStatus.FAILED)

    def test_parse_m7a_no_game_terminate(self):
        parser = M7ALogParser()
        log_content = "INFO: 开始执行任务"
        self.assertEqual(parser.parse_content(log_content), ScriptLogStatus.FAILED)

    def test_parse_m7a_ignores_errors_after_terminate(self):
        """游戏终止后的收尾报错（WinError 233 + 截图失败）属良性，应忽略 → SUCCESS。

        对应真实场景：游戏正常跑完后关闭，助手收尾步骤碰不到已关闭的窗口而产生
        多个 ERROR，但这些不应把整日判为失败。注意报错位于「游戏终止」之后。
        """
        parser = M7ALogParser()
        log_content = """2026-08-02 05:24:33,436 | INFO | 切换到：星际和平指南-生存索引
游戏终止：StarRail
------------------------------------------------------- 完成 --------------------------------------------------------
2026-08-02 05:31:23,466 | ERROR | 发生错误 [WinError 233] 管道的另一端上无任何进程。
2026-08-02 05:31:23,467 | ERROR | 截图失败：没有找到游戏窗口"""
        self.assertEqual(parser.parse_content(log_content), ScriptLogStatus.SUCCESS)

    def test_parse_m7a_fails_on_errors_before_terminate(self):
        """游戏终止之前确有多个真实错误（如界面无法识别）时仍应判失败。"""
        parser = M7ALogParser()
        log_content = """2026-07-30 06:08:43,639 | WARNING | 未识别出任何界面
2026-07-30 06:09:09,076 | ERROR | 当前界面：未知
2026-07-30 06:09:10,078 | ERROR | 获取当前界面超时
游戏终止：StarRail"""
        self.assertEqual(parser.parse_content(log_content), ScriptLogStatus.FAILED)

    def test_parse_log_not_supported(self):
        result = parse_log("MAA")
        self.assertEqual(result["status"], "不支持的脚本")

    def test_parse_ok_nte_success(self):
        parser = OkNteLogParser()
        log_content = "2026-07-19 14:15:01,484 INFO TaskExecutor TaskExecutor:Successfully Executed Task"
        self.assertEqual(parser.parse_content(log_content), ScriptLogStatus.SUCCESS)

    def test_parse_ok_nte_task_completed(self):
        parser = OkNteLogParser()
        log_content = (
            "2026-07-19 14:15:01,481 INFO TaskExecutor DailyTask:Task completed"
        )
        self.assertEqual(parser.parse_content(log_content), ScriptLogStatus.SUCCESS)

    def test_parse_ok_nte_failed(self):
        parser = OkNteLogParser()
        log_content = "ERROR: Something went wrong"
        self.assertEqual(parser.parse_content(log_content), ScriptLogStatus.FAILED)

    def test_parse_bgi_success(self):
        parser = BGILogParser()
        log_content = "[13:56:13.291] [INF] BetterGenshinImpact.ViewModel.Pages.OneDragonFlowViewModel\n一条龙和配置组任务结束"
        self.assertEqual(parser.parse_content(log_content), ScriptLogStatus.SUCCESS)

    def test_parse_bgi_failed_unclaimed(self):
        parser = BGILogParser()
        log_content = '[13:56:11.603] [WRN] BetterGenshinImpact.GameTask.Common.TaskControl\n检查每日奖励结果："未领取"，请手动检查！\n[13:56:13.291] [INF] BetterGenshinImpact.ViewModel.Pages.OneDragonFlowViewModel\n一条龙和配置组任务结束'
        self.assertEqual(parser.parse_content(log_content), ScriptLogStatus.FAILED)

    def test_parse_bgi_failed_error(self):
        parser = BGILogParser()
        log_content = "[ERR] 任务执行失败"
        self.assertEqual(parser.parse_content(log_content), ScriptLogStatus.FAILED)

    def test_parse_bgi_failed_exception(self):
        parser = BGILogParser()
        log_content = "异常: 未知错误"
        self.assertEqual(parser.parse_content(log_content), ScriptLogStatus.FAILED)

    def test_parse_zzz_success(self):
        parser = ZZZLogParser()
        log_content = "[15:06:58.724] [operation.py 675] [INFO]: 指令[ 一条龙 ] 执行成功 返回状态 全部结束"
        self.assertEqual(parser.parse_content(log_content), ScriptLogStatus.SUCCESS)

    def test_parse_zzz_success_app_group(self):
        parser = ZZZLogParser()
        log_content = "[15:06:58.722] [operation.py 675] [INFO]: 指令[ 执行应用组 one_dragon ] 执行成功 返回状态 全部结束"
        self.assertEqual(parser.parse_content(log_content), ScriptLogStatus.SUCCESS)

    def test_parse_zzz_failed_error(self):
        parser = ZZZLogParser()
        log_content = "[ERROR] 任务执行失败"
        self.assertEqual(parser.parse_content(log_content), ScriptLogStatus.FAILED)

    def test_parse_zzz_failed_no_success(self):
        parser = ZZZLogParser()
        log_content = (
            "[20:08:32.067] [one_dragon_context.py 471] [INFO]: 开始加载实例配置 1"
        )
        self.assertEqual(parser.parse_content(log_content), ScriptLogStatus.FAILED)


class TestCollectLogSetup(unittest.TestCase):
    """测试 collect_log 的日志落盘配置（独立、仅标准库）。"""

    def test_get_root_dir_points_to_project_root(self):
        """_get_root_dir 向上 2 层应落在项目根（含 config/config.example.yml 与 python_script）。"""
        root = collect_log._get_root_dir()
        self.assertTrue(os.path.isdir(os.path.join(root, "python_script")))
        self.assertTrue(
            os.path.isfile(os.path.join(root, "config", "config.example.yml"))
        )

    def test_setup_logging_writes_to_logs_collect_log(self):
        """_setup_logging 应把日志写入 <root>/logs/collect_log.log（用临时根避免污染真实 logs）。"""
        tmp = tempfile.mkdtemp()
        orig = collect_log._get_root_dir
        collect_log._get_root_dir = lambda: tmp  # type: ignore[assignment]
        collect_log._LOG_CONFIGURED = False
        before = {id(h) for h in _logging.getLogger().handlers}
        try:
            collect_log._setup_logging()
            _logging.getLogger("__test_collect_log__").info("HELLO_FROM_TEST")
            for h in _logging.getLogger().handlers:
                h.flush()

            log_file = os.path.join(tmp, "logs", "collect_log.log")
            self.assertTrue(os.path.exists(log_file))
            with open(log_file, encoding="utf-8") as f:
                self.assertIn("HELLO_FROM_TEST", f.read())

            targets = [
                getattr(h, "baseFilename", "") for h in _logging.getLogger().handlers
            ]
            self.assertTrue(any("collect_log.log" in t for t in targets))
        finally:
            after = {id(h) for h in _logging.getLogger().handlers}
            for h in list(_logging.getLogger().handlers):
                if id(h) in (after - before):
                    _logging.getLogger().removeHandler(h)
                    h.close()
            collect_log._LOG_CONFIGURED = False
            collect_log._get_root_dir = orig

    def test_setup_logging_is_idempotent(self):
        """重复调用 _setup_logging 不会重复添加指向 collect_log.log 的 handler。"""
        tmp = tempfile.mkdtemp()
        orig = collect_log._get_root_dir
        collect_log._get_root_dir = lambda: tmp  # type: ignore[assignment]
        collect_log._LOG_CONFIGURED = False
        try:
            collect_log._setup_logging()
            collect_log._setup_logging()
            count = sum(
                1
                for h in _logging.getLogger().handlers
                if "collect_log.log" in getattr(h, "baseFilename", "")
            )
            self.assertEqual(count, 1)
        finally:
            before_ids = {id(h) for h in _logging.getLogger().handlers}
            for h in list(_logging.getLogger().handlers):
                if "collect_log.log" in getattr(h, "baseFilename", ""):
                    _logging.getLogger().removeHandler(h)
                    h.close()
            collect_log._LOG_CONFIGURED = False
            collect_log._get_root_dir = orig
            _ = before_ids


class TestParseLogsRerunList(unittest.TestCase):
    """测试 parse_logs 返回的重跑列表（含 NO_LOG）与 do_log 开关。"""

    def _make_config(self, tmp: str, scripts: list[dict]) -> None:
        cfg_dir = os.path.join(tmp, "config")
        os.makedirs(cfg_dir, exist_ok=True)
        with open(os.path.join(cfg_dir, "config.yml"), "w", encoding="utf-8") as f:
            yaml.safe_dump({"script_list": scripts}, f)

    def _fake_exe(self, tmp: str) -> str:
        # 游戏父目录不放 logs，使 parse 判定为 NO_LOG（未正常启动）。
        game_dir = os.path.join(tmp, "fake_game")
        os.makedirs(game_dir, exist_ok=True)
        script_path = os.path.join(game_dir, "fake.exe")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write("")
        return script_path

    def _run_parse(self, tmp: str, do_log: bool = True) -> list[str]:
        orig = collect_log._get_root_dir
        collect_log._get_root_dir = lambda: tmp  # type: ignore[assignment]
        collect_log._LOG_CONFIGURED = False
        try:
            return collect_log.parse_logs(do_log=do_log)
        finally:
            for h in list(_logging.getLogger().handlers):
                if "collect_log.log" in getattr(h, "baseFilename", ""):
                    _logging.getLogger().removeHandler(h)
                    h.close()
            collect_log._LOG_CONFIGURED = False
            collect_log._get_root_dir = orig

    def test_parse_logs_includes_no_log_in_rerun_list(self):
        """无日志（NO_LOG）的游戏应被纳入重跑列表（可能未正常启动）。"""
        tmp = tempfile.mkdtemp()
        script_path = self._fake_exe(tmp)
        self._make_config(tmp, [{"display_name": "崩铁", "script_path": script_path}])
        self.assertEqual(self._run_parse(tmp), ["崩铁"])

    def test_parse_logs_do_log_false_suppresses_print(self):
        """do_log=False 时不应调用 logger.info，但仍返回重跑列表。"""
        tmp = tempfile.mkdtemp()
        script_path = self._fake_exe(tmp)
        self._make_config(tmp, [{"display_name": "崩铁", "script_path": script_path}])
        with mock.patch.object(collect_log.logger, "info") as info:
            result = self._run_parse(tmp, do_log=False)
        info.assert_not_called()
        self.assertEqual(result, ["崩铁"])


class TestRerunFailed(unittest.TestCase):
    """测试失败重跑的底层函数（定位下标 / 命令构造 / 触发 subprocess）。

    全部通过 monkeypatch subprocess.run 或 _rerun_failed_script 验证，不真正启动游戏。
    编排层（先调 collect_log 分析再重跑）见 TestRerunGames。
    """

    def _write_chain(self, script_list: list[dict], suffix: str = ".yml") -> str:
        with tempfile.NamedTemporaryFile(
            "w", suffix=suffix, delete=False, encoding="utf-8"
        ) as chain:
            yaml.safe_dump({"script_list": script_list}, chain)
        return chain.name

    def test_find_chain_index_matches_enabled(self):
        """按 display_name 命中 enabled 脚本，返回其在 script_list 中的下标。"""
        path = self._write_chain(
            [
                {"display_name": "静音", "enabled": True},
                {"display_name": "原神", "enabled": True},
            ]
        )
        self.assertEqual(rerun._find_chain_index("静音", path), 0)
        self.assertEqual(rerun._find_chain_index("原神", path), 1)

    def test_find_chain_index_missing_returns_none(self):
        """display_name 不在脚本链中时返回 None，调用方据此跳过。"""
        path = self._write_chain([{"display_name": "原神", "enabled": True}])
        self.assertIsNone(rerun._find_chain_index("崩铁", path))

    def test_find_chain_index_skips_disabled(self):
        """被禁用（enabled: false）的脚本不计入重跑候选，返回 None。"""
        path = self._write_chain([{"display_name": "原神", "enabled": False}])
        self.assertIsNone(rerun._find_chain_index("原神", path))

    def test_find_chain_index_missing_file_returns_none(self):
        """脚本链文件不存在时优雅返回 None（仅告警），不抛异常。"""
        self.assertIsNone(
            rerun._find_chain_index("原神", "/no/such/file.yml")
        )

    def test_build_rerun_command_dev(self):
        """开发模式：构造 `python -m src.runner.launcher --chain <abs> --debug-index N`。"""
        with mock.patch.object(sys, "frozen", False, create=True):
            cmd, cwd, env = rerun._build_rerun_command(2, "/tmp/88.yml")
        self.assertEqual(
            cmd[:3], [sys.executable, "-m", "src.runner.launcher"]
        )
        self.assertEqual(
            cmd[3:],
            ["--chain", os.path.abspath("/tmp/88.yml"), "--debug-index", "2"],
        )
        self.assertEqual(cwd, collect_log._get_root_dir())
        self.assertIsNotNone(env)
        self.assertIn("PYTHONPATH", env)

    def test_build_rerun_command_frozen(self):
        """冻结模式：构造 `<exe_dir>/OneDragon-Helper-Runner.exe --chain <abs> --debug-index N`。"""
        with mock.patch.object(
            sys, "frozen", True, create=True
        ), mock.patch.object(
            sys,
            "executable",
            "/fake/exe/OneDragon-Helper-Runner.exe",
            create=True,
        ):
            cmd, cwd, env = rerun._build_rerun_command(3, "/tmp/88.yml")
        # os.path.join 在 Windows 上用反斜杠，用 normpath 归一化后再比，避免分隔符差异。
        self.assertEqual(
            os.path.normpath(cmd[0]),
            os.path.normpath("/fake/exe/OneDragon-Helper-Runner.exe"),
        )
        self.assertEqual(
            cmd[1:],
            ["--chain", os.path.abspath("/tmp/88.yml"), "--debug-index", "3"],
        )
        self.assertEqual(cwd, "/fake/exe")
        self.assertIsNone(env)

    def test_rerun_failed_script_invokes_subprocess(self):
        """_rerun_failed_script 应定位下标并真正发起一次 subprocess.run。"""
        path = self._write_chain(
            [
                {"display_name": "崩铁", "enabled": True},
                {"display_name": "原神", "enabled": True},
            ]
        )
        calls: list = []

        def fake_run(cmd, cwd, env, check):
            calls.append((cmd, cwd, env))
            return None

        with mock.patch.object(rerun.subprocess, "run", fake_run):
            ok = rerun._rerun_failed_script("原神", path)
        self.assertTrue(ok)
        self.assertEqual(len(calls), 1)
        # 原神在 script_list 下标 1
        self.assertEqual(calls[0][0][-2:], ["--debug-index", "1"])

    def test_rerun_failed_script_skips_when_not_found(self):
        """定位不到可重跑脚本时返回 False，且不应发起 subprocess。"""
        path = self._write_chain([{"display_name": "原神", "enabled": True}])
        calls: list = []
        with mock.patch.object(
            rerun.subprocess, "run", lambda *a, **k: calls.append(a)
        ):
            ok = rerun._rerun_failed_script("崩铁", path)
        self.assertFalse(ok)
        self.assertEqual(calls, [])

class TestRerunGames(unittest.TestCase):
    """测试 rerun.py 的编排：先调 collect_log 分析拿需重跑列表（FAILED + NO_LOG），再逐个重跑。"""

    def test_rerun_failed_games_reruns_collected_failures(self):
        """rerun_failed_games 应把 collect_log.parse_logs 返回的需重跑项逐个重跑。"""
        with mock.patch.object(
            collect_log, "parse_logs", return_value=["原神", "崩铁"]
        ), mock.patch.object(
            rerun, "_rerun_failed_script", return_value=True
        ) as run:
            rerun.rerun_failed_games()
        called = [c.args[0] for c in run.call_args_list]
        self.assertEqual(set(called), {"原神", "崩铁"})

    def test_rerun_failed_games_noop_when_no_failures(self):
        """无失败脚本时不应发起任何重跑。"""
        with mock.patch.object(
            collect_log, "parse_logs", return_value=[]
        ), mock.patch.object(rerun, "_rerun_failed_script") as run:
            rerun.rerun_failed_games()
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
