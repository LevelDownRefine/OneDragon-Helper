"""测试日志解析器"""

import logging as _logging
import os
import tempfile
import unittest
from datetime import datetime as _dt_real
from pathlib import Path
from unittest import mock

import src.log.monitor as collect_log
import src.utils_logger
from src.config.subscript import get_script_name
from src.log import (
    BGILogParser,
    M7ALogParser,
    OkEfLogParser,
    OkNteLogParser,
    OkWwLogParser,
    ScriptLogStatus,
    ZZZLogParser,
    parse_log,
)
from src.utils_yaml import dump_yaml_file, load_yaml


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

    def test_parse_log_rejects_unsupported(self):
        """不支持的脚本在 parse_logs 入口已过滤，进入 parse_log 即不可能 → 断言失败。"""
        with self.assertRaises(AssertionError):
            parse_log("MAA")

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
        """_get_root_dir 应落在项目根（含 src/ 与 config/config.example.yml）。"""
        root = collect_log._get_root_dir()
        self.assertTrue(os.path.isdir(os.path.join(root, "src")))
        self.assertTrue(
            os.path.isfile(os.path.join(root, "config", "config.example.yml"))
        )

    def test_setup_logging_writes_to_framework_log(self):
        """monitor 复用框架 setup_logging，日志写入 <root>/logs/onedragon_helper.log
        （用临时根避免污染真实 logs），且不写 collect_log.log。"""
        tmp = tempfile.mkdtemp()
        orig = src.utils_logger.get_root_dir
        configured_saved = src.utils_logger._configured
        src.utils_logger.get_root_dir = lambda: tmp  # type: ignore[assignment]
        src.utils_logger._configured = False
        before = {id(h) for h in _logging.getLogger().handlers}
        try:
            collect_log.setup_logging()
            _logging.getLogger("__test_collect_log__").info("HELLO_FROM_TEST")
            for h in _logging.getLogger().handlers:
                h.flush()

            log_file = os.path.join(tmp, "logs", "onedragon_helper.log")
            self.assertTrue(os.path.exists(log_file))
            with open(log_file, encoding="utf-8") as f:
                self.assertIn("HELLO_FROM_TEST", f.read())

            targets = [
                getattr(h, "baseFilename", "") for h in _logging.getLogger().handlers
            ]
            self.assertTrue(any("onedragon_helper.log" in t for t in targets))
            self.assertFalse(any("collect_log.log" in t for t in targets))
        finally:
            after = {id(h) for h in _logging.getLogger().handlers}
            for h in list(_logging.getLogger().handlers):
                if id(h) in (after - before):
                    _logging.getLogger().removeHandler(h)
                    h.close()
            src.utils_logger._configured = configured_saved
            src.utils_logger.get_root_dir = orig

    def test_setup_logging_is_idempotent(self):
        """重复调用复用框架 setup_logging 不会重复添加 onedragon_helper.log handler。"""
        tmp = tempfile.mkdtemp()
        orig = src.utils_logger.get_root_dir
        configured_saved = src.utils_logger._configured
        src.utils_logger.get_root_dir = lambda: tmp  # type: ignore[assignment]
        src.utils_logger._configured = False
        before = {id(h) for h in _logging.getLogger().handlers}
        try:
            collect_log.setup_logging()
            collect_log.setup_logging()
            # 幂等：本次调用（首次因 _configured 被置 False 而添加，第二次 no-op）
            # 仅新增 1 个指向 onedragon_helper.log 的 handler；不依赖全局计数，
            # 避免被其它测试残留的 handler 干扰。
            added = {id(h) for h in _logging.getLogger().handlers} - before
            added_count = sum(
                1
                for h in _logging.getLogger().handlers
                if id(h) in added
                and "onedragon_helper.log" in getattr(h, "baseFilename", "")
            )
            self.assertEqual(added_count, 1)
        finally:
            after = {id(h) for h in _logging.getLogger().handlers}
            for h in list(_logging.getLogger().handlers):
                if id(h) in (after - before):
                    _logging.getLogger().removeHandler(h)
                    h.close()
            src.utils_logger._configured = configured_saved
            src.utils_logger.get_root_dir = orig


class TestParseLogsRerunList(unittest.TestCase):
    """测试 parse_logs 返回的重跑列表（含 NO_LOG）与 do_log 开关。"""

    def _make_config(self, tmp: str, scripts: list[dict]) -> None:
        cfg_dir = os.path.join(tmp, "config")
        os.makedirs(cfg_dir, exist_ok=True)
        dump_yaml_file(os.path.join(cfg_dir, "config.yml"), {"script_list": scripts})

    def _fake_exe(self, tmp: str, name: str = "fake.exe") -> str:
        # 游戏父目录不放 logs，使 parse 判定为 NO_LOG（未正常启动）。
        # name 默认 fake.exe；传入 "March7th Assistant.exe" 可构造崩铁（脚本标识 March7th-Assistant）。
        game_dir = os.path.join(tmp, os.path.splitext(name)[0])
        os.makedirs(game_dir, exist_ok=True)
        script_path = os.path.join(game_dir, name)
        with open(script_path, "w", encoding="utf-8") as f:
            f.write("")
        return script_path

    def _run_parse(self, tmp: str, do_log: bool = True) -> list[str]:
        # parse_logs 读 config 用的是 collect_log._get_root_dir()，并非
        # src.utils_logger.get_root_dir，故此处 patch 前者才能让临时 config 生效。
        orig = collect_log._get_root_dir
        collect_log._get_root_dir = lambda: tmp  # type: ignore[assignment]
        # 诊断视图覆盖全部脚本：显式传 config 全部脚本集合（parse_logs 的 None/空=跳过）。
        config_data = load_yaml(os.path.join(tmp, "config", "config.yml"))
        candidate = {get_script_name(s) for s in config_data.get("script_list", [])}
        before = {id(h) for h in _logging.getLogger().handlers}
        try:
            return collect_log.parse_logs(
                do_log=do_log, candidate_script_names=candidate
            )
        finally:
            after = {id(h) for h in _logging.getLogger().handlers}
            for h in list(_logging.getLogger().handlers):
                if id(h) in (after - before):
                    _logging.getLogger().removeHandler(h)
                    h.close()
            collect_log._get_root_dir = orig

    def test_parse_logs_includes_no_log_in_rerun_list(self):
        """无日志（NO_LOG）的游戏应被纳入重跑列表（可能未正常启动）。"""
        tmp = tempfile.mkdtemp()
        script_path = self._fake_exe(tmp, "March7th Assistant.exe")
        self._make_config(
            tmp, [{"display_name": "崩坏：星穹铁道", "script_path": script_path}]
        )
        # 脚本唯一标识为进程名 March7th-Assistant（非 display_name）。
        result = self._run_parse(tmp)
        # 无日志 → 未正常退出 → 纳入重跑；但无报错 → 不纳入通知。
        self.assertEqual(result["rerun"], ["March7th-Assistant"])
        self.assertEqual(result["notify"], [])

    def test_parse_logs_do_log_false_suppresses_print(self):
        """do_log=False 时不应调用 logger.info，但仍返回重跑列表。"""
        tmp = tempfile.mkdtemp()
        script_path = self._fake_exe(tmp, "March7th Assistant.exe")
        self._make_config(
            tmp, [{"display_name": "崩坏：星穹铁道", "script_path": script_path}]
        )
        with mock.patch.object(collect_log.logger, "info") as info:
            result = self._run_parse(tmp, do_log=False)
        info.assert_not_called()
        self.assertEqual(result["rerun"], ["March7th-Assistant"])

    def test_parse_logs_rerun_by_exit_notify_by_errors(self):
        """重跑依据=未正常退出 或 日常没做完；通知依据=有报错（两者独立、可分离）。

        - ok-ww：正常退出且日常做完、但有报错 → 仅 notify（不 rerun）。
        - BetterGI：未退出且无报错 → 仅 rerun（不 notify）。
        """
        tmp = tempfile.mkdtemp()
        cfg_dir = os.path.join(tmp, "config")
        os.makedirs(cfg_dir, exist_ok=True)
        dump_yaml_file(
            os.path.join(cfg_dir, "config.yml"),
            {
                "script_list": [
                    {
                        "display_name": "A",
                        "script_path": os.path.join(tmp, "ok-ww", "ok-ww.exe"),
                    },
                    {
                        "display_name": "B",
                        "script_path": os.path.join(tmp, "BetterGI", "BetterGI.exe"),
                    },
                ]
            },
        )

        def fake_parse(script_name, script_path=""):
            # 返回 parse_log 的真实契约：完整归一化结构（八键）。
            if script_name == "ok-ww":
                # 正常退出且日常做完：仅剩「有报错」这一条，故只进 notify。
                return {
                    "status": "Failed",
                    "log_path": "x",
                    "exited": True,
                    "errors": ["ERR x"],
                    "stamina": None,
                    "daily_done": True,
                    "extra": None,
                }
            if script_name == "BetterGI":
                return {
                    "status": "Failed",
                    "log_path": "y",
                    "exited": False,
                    "errors": [],
                    "stamina": None,
                    "daily_done": True,
                    "extra": None,
                }
            return {
                "status": "NoLog",
                "log_path": None,
                "exited": None,
                "errors": [],
                "stamina": None,
                "daily_done": False,
                "extra": None,
            }

        orig = collect_log._get_root_dir
        collect_log._get_root_dir = lambda: tmp  # type: ignore[assignment]
        before = {id(h) for h in _logging.getLogger().handlers}
        try:
            config_data = load_yaml(os.path.join(tmp, "config", "config.yml"))
            candidate = {get_script_name(s) for s in config_data.get("script_list", [])}
            with mock.patch.object(collect_log, "parse_log", side_effect=fake_parse):
                result = collect_log.parse_logs(
                    do_log=False, candidate_script_names=candidate
                )
        finally:
            after = {id(h) for h in _logging.getLogger().handlers}
            for h in list(_logging.getLogger().handlers):
                if id(h) in (after - before):
                    _logging.getLogger().removeHandler(h)
                    h.close()
            collect_log._get_root_dir = orig

        self.assertEqual(result["rerun"], ["BetterGI"])
        self.assertEqual(result["notify"], ["ok-ww"])
        # parse_logs 还应返回汇总表格文本（供 notify_mail 整表通知）。
        self.assertIn("report", result)
        self.assertIsInstance(result["report"], str)
        self.assertIn("脚本运行状况汇总报告", result["report"])

    def test_parse_logs_warn_when_success_with_errors(self):
        """正常完成（SUCCESS）但含报错 → 表格显示「成功(有报错)」WARN，
        仅通知不重跑（rerun 看 exited 与 daily_done，notify 看 errors，均不受 WARN 影响）。
        """
        tmp = tempfile.mkdtemp()
        cfg_dir = os.path.join(tmp, "config")
        os.makedirs(cfg_dir, exist_ok=True)
        dump_yaml_file(
            os.path.join(cfg_dir, "config.yml"),
            {
                "script_list": [
                    {
                        "display_name": "A",
                        "script_path": os.path.join(tmp, "BetterGI", "BetterGI.exe"),
                    },
                ]
            },
        )

        def fake_parse(script_name, script_path=""):
            # 正常退出、日常做完、但有报错：应归为 WARN，不进 rerun、进 notify。
            # 返回 parse_log 真实契约：完整归一化结构。
            return {
                "status": "Success",
                "log_path": "x",
                "exited": True,
                "errors": ["ERR x"],
                "stamina": None,
                "daily_done": True,
                "extra": None,
            }

        orig = collect_log._get_root_dir
        collect_log._get_root_dir = lambda: tmp  # type: ignore[assignment]
        before = {id(h) for h in _logging.getLogger().handlers}
        try:
            config_data = load_yaml(os.path.join(tmp, "config", "config.yml"))
            candidate = {get_script_name(s) for s in config_data.get("script_list", [])}
            with mock.patch.object(collect_log, "parse_log", side_effect=fake_parse):
                result = collect_log.parse_logs(
                    do_log=False, candidate_script_names=candidate
                )
        finally:
            after = {id(h) for h in _logging.getLogger().handlers}
            for h in list(_logging.getLogger().handlers):
                if id(h) in (after - before):
                    _logging.getLogger().removeHandler(h)
                    h.close()
            collect_log._get_root_dir = orig

        # WARN 不影响决策：正常退出 → 不重跑；有报错 → 通知。
        self.assertEqual(result["rerun"], [])
        self.assertEqual(result["notify"], ["BetterGI"])
        # 表格状态列呈现「有报错」以抓潜在问题，而非「成功」。
        self.assertIn("有报错", result["report"])

    def test_parse_daily_returns_bool_driven_by_marker(self):
        """parse_daily 仅由 daily_success_marker 决定：命中标记=True，否则=False，绝不返回 None。"""
        for parser_cls in collect_log._PARSERS:
            p = parser_cls()
            # 中性内容（无任一成功标记）→ 一律 False（无标记即失败）。
            self.assertFalse(p.parse_daily("启动但啥也没发生，没有任何每日标记"))
            # 返回类型恒为 bool，绝不 None。
            self.assertIsInstance(p.parse_daily(""), bool)
            # 各成功标记命中应返 True。
            for marker in p.daily_success_marker:
                self.assertTrue(p.parse_daily(marker))

    def test_parse_daily_no_marker_returns_true(self):
        """未配 daily_success_marker 的脚本无法判定，返回 True。

        若返回 False，重跑判据（日常没做完即重跑）会让它每次都进重跑名单。
        """
        p = OkWwLogParser()
        p.daily_success_marker = []
        self.assertTrue(p.parse_daily("没有任何标记的内容"))

    def test_resolve_exited_infers_from_status_when_unknown(self):
        """日志未明确退出信号（None）时按整体状态推断；有明确信号时不覆盖。"""
        # 缺失信号 → 成功=已退出，失败/无日志=未正常退出。
        self.assertTrue(collect_log._resolve_exited(None, ScriptLogStatus.SUCCESS))
        self.assertFalse(collect_log._resolve_exited(None, ScriptLogStatus.FAILED))
        self.assertFalse(collect_log._resolve_exited(None, ScriptLogStatus.NO_LOG))
        # 明确信号不被状态覆盖。
        self.assertFalse(collect_log._resolve_exited(False, ScriptLogStatus.SUCCESS))
        self.assertTrue(collect_log._resolve_exited(True, ScriptLogStatus.FAILED))

    def test_parse_daily_done_driven_by_marker(self):
        """daily_done 直接由 parse_daily 决定：命中每日成功标记=True，否则（含脚本成功但无标记）=False。"""
        p = OkWwLogParser()
        # 脚本整体成功但无每日完成标记 → 未做完每日（无标记即失败）。
        with tempfile.NamedTemporaryFile(
            "w", suffix=".log", delete=False, encoding="utf-8"
        ) as tf:
            tf.write("Successfully Executed Task, Exiting Game and App!")
            path = tf.name
        try:
            p.get_log_path = lambda sp="": Path(path)  # type: ignore[method-assign]
            res = p.parse("")
            self.assertEqual(res["status"], ScriptLogStatus.SUCCESS)
            self.assertFalse(res["daily_done"])
        finally:
            os.unlink(path)
        # 命中「claim daily reward via  coordinate」标记 → 当日做完。
        with tempfile.NamedTemporaryFile(
            "w", suffix=".log", delete=False, encoding="utf-8"
        ) as tf:
            tf.write("DailyTask:claim daily reward via  coordinate")
            path = tf.name
        try:
            p.get_log_path = lambda sp="": Path(path)  # type: ignore[method-assign]
            res = p.parse("")
            self.assertTrue(res["daily_done"])
        finally:
            os.unlink(path)
        # 命中「current daily progress 180」（每日进度满分）兜底标记 → 当日做完。
        with tempfile.NamedTemporaryFile(
            "w", suffix=".log", delete=False, encoding="utf-8"
        ) as tf:
            tf.write("DailyTask:info_set current daily progress 180")
            path = tf.name
        try:
            p.get_log_path = lambda sp="": Path(path)  # type: ignore[method-assign]
            res = p.parse("")
            self.assertTrue(res["daily_done"])
        finally:
            os.unlink(path)

    def test_parse_logs_report_never_shows_unknown_daily(self):
        """聚合方仅消费定稿后的 daily_done，不得自行产出「未知」。"""
        tmp = tempfile.mkdtemp()
        cfg_dir = os.path.join(tmp, "config")
        os.makedirs(cfg_dir, exist_ok=True)
        dump_yaml_file(
            os.path.join(cfg_dir, "config.yml"),
            {
                "script_list": [
                    {
                        "display_name": "A",
                        "script_path": os.path.join(tmp, "BetterGI", "BetterGI.exe"),
                    },
                ]
            },
        )

        def fake_parse(script_name, script_path=""):
            # 已定稿的 daily_done（True）；聚合方只消费，不应再出现「未知」。
            # 返回 parse_log 真实契约：完整归一化结构。
            return {
                "status": "Success",
                "log_path": "x",
                "exited": True,
                "errors": [],
                "daily_done": True,
                "stamina": None,
                "extra": None,
            }

        orig = collect_log._get_root_dir
        collect_log._get_root_dir = lambda: tmp  # type: ignore[assignment]
        before = {id(h) for h in _logging.getLogger().handlers}
        try:
            config_data = load_yaml(os.path.join(tmp, "config", "config.yml"))
            candidate = {get_script_name(s) for s in config_data.get("script_list", [])}
            with mock.patch.object(collect_log, "parse_log", side_effect=fake_parse):
                result = collect_log.parse_logs(
                    do_log=False, candidate_script_names=candidate
                )
        finally:
            after = {id(h) for h in _logging.getLogger().handlers}
            for h in list(_logging.getLogger().handlers):
                if id(h) in (after - before):
                    _logging.getLogger().removeHandler(h)
                    h.close()
            collect_log._get_root_dir = orig

        self.assertNotIn("未知", result["report"])


class TestActionListsAndReport(unittest.TestCase):
    """直接锁定 parse_logs 拆出的两个职责函数：汇总表格 / 需处理脚本列表。"""

    @staticmethod
    def _entry(script_name, display_name, result):
        return {
            "script_name": script_name,
            "display_name": display_name,
            "result": result,
        }

    def test_prepare_action_lists_splits_rerun_and_notify(self):
        # 退出与否、有无报错两轴独立：ok-ww 退出且做完了但有错→仅 notify；
        # BetterGI 未退且无错→仅 rerun。
        entries = [
            self._entry(
                "ok-ww",
                "A",
                {
                    "status": "Failed",
                    "exited": True,
                    "errors": ["e"],
                    "daily_done": True,
                },
            ),
            self._entry(
                "BetterGI",
                "B",
                {
                    "status": "Failed",
                    "exited": False,
                    "errors": [],
                    "daily_done": True,
                },
            ),
        ]
        rerun, notify = collect_log._prepare_action_lists(entries)
        self.assertEqual(rerun, ["BetterGI"])
        self.assertEqual(notify, ["ok-ww"])

    def test_prepare_action_lists_reruns_when_exited_but_daily_not_done(self):
        # 正常退出 ≠ 做完了：脚本可能跑完流程正常收尾、却一项日常都没做成
        # （ok-ef「部分失败」仍会写退出标记），只看退出会漏掉这类。
        entries = [
            self._entry(
                "ok-ef",
                "A",
                {
                    "status": "Failed",
                    "exited": True,
                    "errors": [],
                    "daily_done": False,
                },
            ),
        ]
        rerun, notify = collect_log._prepare_action_lists(entries)
        self.assertEqual(rerun, ["ok-ef"])
        self.assertEqual(notify, [])

    def test_prepare_action_lists_no_rerun_when_exited_and_daily_done(self):
        entries = [
            self._entry(
                "ok-ww",
                "A",
                {
                    "status": "Success",
                    "exited": True,
                    "errors": [],
                    "daily_done": True,
                },
            ),
        ]
        rerun, _ = collect_log._prepare_action_lists(entries)
        self.assertEqual(rerun, [])

    def test_build_summary_report_renders_rows_without_unknown(self):
        entries = [
            self._entry(
                "BetterGI",
                "原神",
                {
                    "status": "Success",
                    "exited": True,
                    "errors": [],
                    "daily_done": True,
                    "stamina": "120",
                    "extra": None,
                },
            ),
        ]
        report = collect_log._build_summary_report(entries, [], [], do_log=False)
        self.assertIn("原神", report)
        self.assertIn("脚本运行状况汇总报告", report)
        self.assertNotIn("未知", report)

    def test_build_summary_report_exited_none_renders_no_unknown(self):
        # 无日志条目 exited=None（调用方直接喂入）也应定稿为「否」，不得出现「未知」。
        entries = [
            self._entry(
                "BetterGI",
                "原神",
                {
                    "status": "NoLog",
                    "exited": None,
                    "errors": [],
                    "daily_done": False,
                    "stamina": None,
                    "extra": None,
                },
            ),
        ]
        report = collect_log._build_summary_report(entries, [], [], do_log=False)
        self.assertIn("原神", report)
        self.assertNotIn("未知", report)
        self.assertIn("否", report)

    def test_build_summary_report_prints_error_lines_then_log_tails(self):
        """各脚本报错信息先打印，全部结束后才打印各脚本日志尾部；两段均不进 report 文本。"""
        entries = [
            self._entry(
                "ok-ww",
                "A",
                {
                    "status": "Failed",
                    "exited": False,
                    "log_path": "D:/log/A.log",
                    "errors": ["ERROR: x", "ERROR: y"],
                    "log_content": "a-line1\na-line2\na-line3",
                    "daily_done": False,
                    "stamina": None,
                    "extra": None,
                },
            ),
            self._entry(
                "BetterGI",
                "B",
                {
                    "status": "Success",
                    "exited": True,
                    "log_path": "D:/log/B.log",
                    "errors": ["WARNING: 未领取"],
                    "log_content": "tail-only-B",
                    "daily_done": True,
                    "stamina": "120",
                    "extra": None,
                },
            ),
            self._entry(
                "ok-nte",
                "C",
                {
                    "status": "Success",
                    "exited": True,
                    "errors": [],
                    "log_path": "D:/log/C.log",
                    "daily_done": True,
                    "stamina": None,
                    "extra": None,
                },
            ),
        ]
        with mock.patch.object(collect_log, "log_info") as mock_log:
            report = collect_log._build_summary_report(entries, [], [], do_log=True)
        # 两段均不进入 report 文本（邮件已由 notify_mail 单独发逐脚本详情）。
        self.assertNotIn("ERROR: x", report)
        self.assertNotIn("tail-only-B", report)
        printed = "\n".join(str(c.args[0]) for c in mock_log.call_args_list)
        # 报错信息与日志尾部两段都在控制台。
        self.assertIn("各脚本报错明细", printed)
        self.assertIn("各脚本日志尾部", printed)
        self.assertIn("ERROR: x", printed)
        self.assertIn("ERROR: y", printed)
        self.assertIn("WARNING: 未领取", printed)
        # 报错信息（含 WARN）打印；但日志尾部仅 FAILED 才打，故 B(Success+报错) 无尾部。
        self.assertNotIn("tail-only-B", printed)
        # A(Failed) 的日志尾部应打印。
        self.assertIn("a-line1", printed)
        # 顺序：报错明细整体在日志尾部之前。
        self.assertLess(
            printed.index("各脚本报错明细"),
            printed.index("各脚本日志尾部"),
        )
        # 无报错脚本（C）不出现于这两段。
        self.assertNotIn("] C [", printed)


class TestFourFieldExtraction(unittest.TestCase):
    """验证各 Parser 的四类补充信息提取（体力 / 每日 / 退出 / 报错）。"""

    def test_oww_stamina_daily_exit_errors(self):
        p = OkWwLogParser()
        content = (
            "info_set current_stamina 240\n"
            "info_set back_up_stamina 79\n"
            "DailyTask:claim daily reward via  coordinate\n"
            "TaskExecutor:Successfully Executed Task, Exiting Game and App!\n"
            "ERROR CombatCheck:target_enemy failed, try recheck\n"  # 噪声：战斗复检
            "ERROR TaskExecutor:Daily Task exception stopped Traceback\n"  # 真实报错
        )
        self.assertEqual(p.parse_stamina(content), "240")
        self.assertTrue(p.parse_daily(content))
        self.assertTrue(p.parse_exit(content))
        # 战斗复检噪声应被过滤，仅保留真实报错。
        self.assertEqual(
            p.collect_error_lines(content),
            ["ERROR TaskExecutor:Daily Task exception stopped Traceback"],
        )

    def test_oww_daily_none_and_false(self):
        p = OkWwLogParser()
        self.assertFalse(p.parse_daily("没有任何每日标记"))
        self.assertFalse(p.parse_daily("ERROR Daily Task exception stopped"))

    def test_oww_stamina_takes_last_occurrence(self):
        p = OkWwLogParser()
        content = "info_set current_stamina 240\ninfo_set current_stamina 102\ninfo_set back_up_stamina 118\n"
        self.assertEqual(p.parse_stamina(content), "102")

    def test_onte_stamina_daily_exit_errors(self):
        p = OkNteLogParser()
        content = (
            "AnomalyHunter:info_set 当前体力 355\n"
            "DailyRoutineTask:开始执行日常任务\n"
            "DailyRoutineTask:info_set failed []\n"
            "DailyRoutineTask:结束执行日常任务\n"
            "TaskExecutor:Successfully Executed Task, Exiting Game and App!\n"
            "ERROR CombatCheck:target_enemy failed, try recheck\n"  # 噪声
            "ERROR DailyRoutineTask:任务运行失败: 喷泉签到 Traceback\n"  # 真实
        )
        self.assertEqual(p.parse_stamina(content), "355")
        self.assertTrue(p.parse_daily(content))
        self.assertTrue(p.parse_exit(content))
        self.assertEqual(
            p.collect_error_lines(content),
            ["ERROR DailyRoutineTask:任务运行失败: 喷泉签到 Traceback"],
        )

    def test_onte_daily_partial_is_false(self):
        p = OkNteLogParser()
        content = (
            "DailyRoutineTask:开始执行日常任务\n"
            "DailyRoutineTask:info_set failed ['喷泉签到']\n"
            "DailyRoutineTask:结束执行日常任务\n"
        )
        self.assertFalse(p.parse_daily(content))
        self.assertFalse(OkNteLogParser().parse_daily("完全没有日常相关标记"))

    def test_oef_report_fields(self):
        p = OkEfLogParser()
        content_done = (
            "日常任务执行情况汇总 - 2026-08-18 05:26:41\n"
            "执行状态: 完成\n"
            "失败任务:\n"
            "  - ⭐刷体力 : 二次寻路失败：没有找到按钮\n"
        )
        self.assertIsNone(p.parse_stamina(content_done))  # 终末地日志无体力数字
        self.assertTrue(p.parse_daily(content_done))
        self.assertTrue(p.parse_exit(content_done))
        # 报错取「- 」缩进明细行（含刷体力失败原因）。
        self.assertEqual(
            p.collect_error_lines(content_done),
            ["- ⭐刷体力 : 二次寻路失败：没有找到按钮"],
        )

        content_partial = (
            "执行状态: 部分失败\n失败任务:\n  - ⭐买信用商店 : 购买失败: 信用不足\n"
        )
        self.assertFalse(p.parse_daily(content_partial))
        # 部分失败 = 进程正常跑完、仅结果部分失败 → 仍算正常退出（与结果成败正交）。
        self.assertTrue(p.parse_exit(content_partial))

        content_abnormal = "执行状态: 异常结束\n当前正在执行的任务:\n  ⭐送礼\n"
        self.assertFalse(p.parse_daily(content_abnormal))
        self.assertFalse(p.parse_exit(content_abnormal))

    def test_m7a_stamina_daily_exit_and_error_truncation(self):
        p = M7ALogParser()
        content = (
            "开拓力: 249/300\n"
            "每日实训已完成\n"
            "2026-08-02 05:24:00,000 | ERROR | 当前界面：未知\n"
            "游戏终止：StarRail\n"
            "2026-08-02 05:31:23,466 | ERROR | 发生错误 [WinError 233]\n"  # 终止后良性
        )
        self.assertEqual(p.parse_stamina(content), "249")
        self.assertTrue(p.parse_daily(content))
        self.assertTrue(p.parse_exit(content))
        # 「游戏终止」之后的收尾报错（WinError 233）属良性，应被截断过滤。
        self.assertEqual(
            p.collect_error_lines(content),
            ["2026-08-02 05:24:00,000 | ERROR | 当前界面：未知"],
        )

    def test_m7a_no_game_terminate_yields_all_errors(self):
        p = M7ALogParser()
        content = "ERROR 当前界面：未知\nERROR 获取当前界面超时\n"
        self.assertEqual(len(p.collect_error_lines(content)), 2)

    def test_zzz_stamina_daily_exit_errors(self):
        # 仅「等待大世界画面 未到达大世界」属重试瞬时噪声应排除；其余单步失败
        # （如「代理人方案培养 找不到」）仍应计入报错，交由状态判定真相。
        p = ZZZLogParser()
        content = (
            "[charge_plan_app.py 141] [INFO]: 剩余电量 119 储蓄电量 888 以太电池 44\n"
            "指令[ 一条龙 ] 执行成功 返回状态 全部结束\n"
            "[operation.py 678] [INFO]: 日常奖励领取成功\n"
            "[operation.py 677] [ERROR]: 指令[ 等待大世界画面 ] 执行失败 返回状态 未到达大世界\n"
            "[operation.py 677] [ERROR]: 指令[ 快捷手册 选择副本类型 代理人方案培养 ] 执行失败 返回状态 找不到 代理人方案培养\n"
        )
        self.assertEqual(p.parse_stamina(content), "119")
        self.assertTrue(p.parse_daily(content))
        self.assertTrue(p.parse_exit(content))
        errs = p.collect_error_lines(content)
        # 仅屏蔽「等待大世界画面」那行；「代理人方案培养」仍被收集。
        self.assertEqual(len(errs), 1)
        self.assertIn("代理人方案培养", errs[0])
        self.assertNotIn("等待大世界画面", errs[0])

    def test_zzz_collects_non_transient_errors(self):
        # 非「等待大世界画面」噪声的 [ERROR] 仍应被收集，不误伤真实错误。
        p = ZZZLogParser()
        content = (
            "指令[ 一条龙 ] 执行成功 返回状态 全部结束\n"
            "[ERROR]: OCR 模型加载失败，识别功能不可用\n"
        )
        errs = p.collect_error_lines(content)
        self.assertEqual(len(errs), 1)
        self.assertIn("OCR 模型加载失败", errs[0])

    def test_zzz_daily_false_on_exec_failure(self):
        p = ZZZLogParser()
        self.assertFalse(p.parse_daily("指令[ 一条龙 ] 执行失败 返回状态 xxx"))
        self.assertFalse(p.parse_daily("启动但啥也没发生"))

    def test_zzz_daily_true_only_on_reward_claimed(self):
        # ZZZ「领取每日」标志为「日常奖励领取成功」，与整轮「一条龙 执行成功」
        # （属 success_markers / 整体成败判定）区分：仅一条龙成功、无领取标记
        # 不算当日做完，避免把未实际领取当成已完成。
        p = ZZZLogParser()
        self.assertTrue(
            p.parse_daily(
                "指令[ 执行应用组 one_dragon ] 执行成功\n[INFO]: 日常奖励领取成功"
            )
        )
        self.assertFalse(p.parse_daily("指令[ 一条龙 ] 执行成功 返回状态 全部结束"))

    def test_bgi_stamina_daily_exit_errors(self):
        p = BGILogParser()
        content = (
            "原粹树脂：22，浓缩树脂：0\n"
            '检查每日奖励结果："今日奖励已领取"\n'
            "一条龙和配置组任务结束\n"
            "[ERR] 任务执行失败\n"
            "异常: 未知错误\n"
            '自动秘境：点击 "地脉异常"\n'  # 游戏内正常术语，不应算报错
        )
        self.assertEqual(p.parse_stamina(content), "22")
        self.assertTrue(p.parse_daily(content))
        self.assertTrue(p.parse_exit(content))
        errs = p.collect_error_lines(content)
        self.assertEqual(len(errs), 2)
        self.assertIn("[ERR] 任务执行失败", errs)
        self.assertIn("异常: 未知错误", errs)
        # 「地脉异常」不带冒号，不应计入报错。
        self.assertFalse(any("地脉异常" in e for e in errs))

    def test_bgi_daily_false_when_unclaimed(self):
        p = BGILogParser()
        self.assertFalse(p.parse_daily('检查每日奖励结果："未领取"，请手动检查！'))

    def test_parse_returns_all_four_fields(self):
        """parse() 应在保留旧键（status/log_path/log_content）的同时并入四类信息。"""
        p = OkWwLogParser()
        with tempfile.NamedTemporaryFile(
            "w", suffix=".log", delete=False, encoding="utf-8"
        ) as tf:
            tf.write(
                "info_set current_stamina 100\n"
                "DailyTask:claim daily reward via  coordinate\n"
                "Successfully Executed Task, Exiting Game and App!"
            )
            path = tf.name
        try:
            p.get_log_path = lambda sp="": Path(path)  # type: ignore[method-assign]
            result = p.parse("")
            self.assertEqual(result["status"], ScriptLogStatus.SUCCESS)
            self.assertEqual(result["stamina"], "100")
            self.assertTrue(result["daily_done"])
            self.assertTrue(result["exited"])
            self.assertEqual(result["errors"], [])
            for key in (
                "status",
                "log_path",
                "log_content",
                "stamina",
                "daily_done",
                "exited",
                "errors",
                "extra",
            ):
                self.assertIn(key, result)
        finally:
            os.unlink(path)

    def test_parse_no_log_has_no_extra_fields(self):
        """无日志时 parse() 仅含 status/log_path，不抛四类字段（调用方用 .get 兜底）。"""
        p = OkWwLogParser()
        p.get_log_path = lambda sp="": None  # type: ignore[method-assign]
        result = p.parse("")
        self.assertEqual(result["status"], ScriptLogStatus.NO_LOG)
        self.assertNotIn("stamina", result)

    def test_parse_log_no_log_resolves_exited_false(self):
        """无日志路径在 parse_log 层定稿 exited 为确定 bool（False），不向显示层漏 None。"""
        # ok-ww 指向不存在的日志 → NO_LOG，聚合方应拿到 exited=False 而非 None。
        tmp = tempfile.mkdtemp()
        cfg_dir = os.path.join(tmp, "config")
        os.makedirs(cfg_dir, exist_ok=True)
        dump_yaml_file(
            os.path.join(cfg_dir, "config.yml"),
            {
                "script_list": [
                    {
                        "display_name": "A",
                        "script_path": os.path.join(tmp, "ok-ww", "ok-ww.exe"),
                    }
                ]
            },
        )
        orig = collect_log._get_root_dir
        collect_log._get_root_dir = lambda: tmp  # type: ignore[assignment]
        before = {id(h) for h in _logging.getLogger().handlers}
        try:
            res = parse_log("ok-ww", os.path.join(tmp, "ok-ww", "ok-ww.exe"))
        finally:
            after = {id(h) for h in _logging.getLogger().handlers}
            for h in list(_logging.getLogger().handlers):
                if id(h) in (after - before):
                    _logging.getLogger().removeHandler(h)
                    h.close()
            collect_log._get_root_dir = orig
        self.assertEqual(res["status"], ScriptLogStatus.NO_LOG)
        self.assertFalse(res["exited"])
        self.assertIsInstance(res["exited"], bool)


class TestScriptNameIdentifier(unittest.TestCase):
    """验证各 Parser 以脚本唯一标识 script_name 定位（exe=进程名 / python=display_name）。

    这同时修复此前的 bug：config.yml 的崩铁名为「崩坏：星穹铁道」、script_path 指向
    March7th Assistant.exe，其脚本标识为进程名 March7th-Assistant，必须能命中 M7ALogParser。
    """

    def test_parse_log_dispatches_by_script_name(self):
        """parse_log 按 script_name 分派到对应 Parser（已合入原 _find_parser 的查找）。"""
        # 受支持标识分派命中对应 Parser，返回真实状态（非不支持哨兵）。
        for name in (
            "March7th-Assistant",
            "ok-ww",
            "BetterGI",
            "OneDragon-Launcher",
            "ok-ef",
            "ok-nte",
        ):
            res = parse_log(name)
            self.assertIn(
                res["status"],
                (
                    ScriptLogStatus.SUCCESS,
                    ScriptLogStatus.FAILED,
                    ScriptLogStatus.NO_LOG,
                    ScriptLogStatus.WARN,
                ),
                name,
            )

    def test_supported_set_from_script_name(self):
        supported = {cls.script_name for cls in collect_log._PARSERS if cls.script_name}
        self.assertIn("March7th-Assistant", supported)
        self.assertIn("ok-ww", supported)


class TestExtraAndReportTable(unittest.TestCase):
    """验证额外信息（原神浓缩树脂）与汇总表格对齐辅助函数。"""

    def test_bgi_extra_records_condensed_when_nonzero(self):
        p = BGILogParser()
        self.assertEqual(p.parse_extra("原粹树脂：22，浓缩树脂：3\n"), "浓缩树脂: 3")

    def test_bgi_extra_none_when_condensed_zero(self):
        p = BGILogParser()
        self.assertIsNone(p.parse_extra("原粹树脂：22，浓缩树脂：0\n"))

    def test_bgi_extra_none_when_no_marker(self):
        p = BGILogParser()
        self.assertIsNone(p.parse_extra("没有任何树脂标记"))

    def test_base_extra_default_none(self):
        self.assertIsNone(OkWwLogParser().parse_extra("whatever"))

    def test_cell_width_counts_cjk_as_two(self):
        self.assertEqual(collect_log._cell_width("中"), 2)
        self.assertEqual(collect_log._cell_width("ab"), 2)
        self.assertEqual(collect_log._cell_width("a中"), 3)

    def test_pad_row_reaches_total_width(self):
        row = collect_log._pad_row(["原神", "成功", "22"], [14, 8, 10])
        self.assertEqual(collect_log._cell_width(row), 14 + 8 + 10)


class TestIsValidLog(unittest.TestCase):
    """_is_valid_log 是每日/体力/报错/额外解析共用的前置日期闸门，运行日从
    04:00 切分（定时运行在 04:10）：现在 >= 4 点只认「今天 04:00 之后」，现在
    < 4 点（凌晨）只认「昨天运行日」（昨天 04:00 之后）。两个分支都以 4 点为界，
    避免把更早的日志误判成当前运行日。"""

    def _make_log(self, mtime: float) -> Path:
        d = Path(tempfile.mkdtemp())
        log = d / "log.txt"
        log.write_text("x", encoding="utf-8")
        os.utime(log, (mtime, mtime))
        return log

    def _dt(self, y, mo, d, h=9, mi=0):
        return _dt_real(y, mo, d, h, mi)

    def _patch_now(self, fake_now):
        real_dt = collect_log.datetime
        fake = mock.MagicMock(wraps=real_dt)
        fake.now = mock.Mock(return_value=fake_now)
        return mock.patch.object(collect_log, "datetime", fake)

    # ---- 现在 >= 4 点：只认「今天 04:00 之后」----
    def test_hour_ge_4_today_after_4am_valid(self):
        with self._patch_now(self._dt(2026, 8, 24, 9)):
            log = self._make_log(self._dt(2026, 8, 24, 4, 10).timestamp())
            self.assertTrue(ZZZLogParser()._is_valid_log(log))

    def test_hour_ge_4_today_before_4am_invalid(self):
        # 今天 03:00 产生的日志：4 点前属昨天运行日，>=4 点时不应认
        with self._patch_now(self._dt(2026, 8, 24, 9)):
            log = self._make_log(self._dt(2026, 8, 24, 3, 0).timestamp())
            self.assertFalse(ZZZLogParser()._is_valid_log(log))

    def test_hour_ge_4_yesterday_invalid(self):
        with self._patch_now(self._dt(2026, 8, 24, 9)):
            log = self._make_log(self._dt(2026, 8, 23, 13, 12).timestamp())
            self.assertFalse(ZZZLogParser()._is_valid_log(log))

    def test_hour_ge_4_day_before_yesterday_invalid(self):
        with self._patch_now(self._dt(2026, 8, 24, 9)):
            log = self._make_log(self._dt(2026, 8, 22, 13, 12).timestamp())
            self.assertFalse(ZZZLogParser()._is_valid_log(log))

    # ---- 现在 < 4 点（凌晨）：只认「昨天运行日」即昨天 04:00 之后 ----
    def test_hour_lt_4_yesterday_after_4am_valid(self):
        # 昨天 13:12 属昨天运行日，凌晨 parse 应认（这是预期的昨天那一轮）
        with self._patch_now(self._dt(2026, 8, 24, 2)):
            log = self._make_log(self._dt(2026, 8, 23, 13, 12).timestamp())
            self.assertTrue(ZZZLogParser()._is_valid_log(log))

    def test_hour_lt_4_yesterday_before_4am_invalid(self):
        # 昨天 03:00 早于昨天运行日起点，不应认
        with self._patch_now(self._dt(2026, 8, 24, 2)):
            log = self._make_log(self._dt(2026, 8, 23, 3, 0).timestamp())
            self.assertFalse(ZZZLogParser()._is_valid_log(log))

    def test_hour_lt_4_today_after_midnight_valid(self):
        # 今天 00:05 属今天 0-4 点，按运行日边界归入「昨天运行日」，凌晨 parse 应认
        with self._patch_now(self._dt(2026, 8, 24, 2)):
            log = self._make_log(self._dt(2026, 8, 24, 0, 5).timestamp())
            self.assertTrue(ZZZLogParser()._is_valid_log(log))

    def test_hour_lt_4_day_before_yesterday_invalid(self):
        with self._patch_now(self._dt(2026, 8, 24, 2)):
            log = self._make_log(self._dt(2026, 8, 22, 13, 12).timestamp())
            self.assertFalse(ZZZLogParser()._is_valid_log(log))

    def test_applies_to_all_parsers(self):
        # 同一个日期闸门对所有脚本类型一致生效
        with self._patch_now(self._dt(2026, 8, 24, 9)):
            log = self._make_log(self._dt(2026, 8, 23, 13, 12).timestamp())
            for parser in (
                OkEfLogParser(),
                M7ALogParser(),
                OkWwLogParser(),
                BGILogParser(),
                ZZZLogParser(),
            ):
                self.assertFalse(parser._is_valid_log(log), parser.__class__.__name__)


class TestLogAnalysisConfigDriven(unittest.TestCase):
    """日志分析关键词应来自 config/log_analysis.yml，而非 hardcode 在 Parser 子类。

    回归护栏：确保重构后关键词确由配置注入，且配置与代码中的脚本标识保持一致。
    """

    def test_config_covers_all_parsers(self):
        """_PARSERS 中每个脚本标识都应在 log_analysis.yml 有对应条目，反之亦然。"""
        cfg = collect_log._load_log_analysis_config()
        parsers = cfg.get("parsers", {})
        configured = set(parsers.keys())
        declared = {cls.script_name for cls in collect_log._PARSERS if cls.script_name}
        self.assertEqual(configured, declared)

    def test_keywords_loaded_from_config(self):
        """Parser 实例的判定关键词应由配置注入，而非依赖类属性 hardcode。"""
        oww = OkWwLogParser()
        self.assertEqual(oww.log_pattern, "ok-script.log")
        self.assertEqual(oww.error_markers, ("ERROR",))
        # 双空格领奖标记必须原样保留。
        self.assertEqual(
            oww.daily_success_marker,
            ("claim daily reward via  coordinate", "current daily progress 180"),
        )
        self.assertEqual(
            oww.success_markers, ("Successfully Executed Task", "Task completed")
        )

        bgi = BGILogParser()
        self.assertEqual(bgi.error_markers, ("[ERR]", "异常:", "异常："))
        self.assertEqual(bgi.success_markers, ("一条龙和配置组任务结束",))
        self.assertEqual(bgi.fail_markers, ("未领取",))

    def test_ok_ef_has_no_error_markers(self):
        """终末地靠「- 」缩进明细收集报错，配置不含 error_markers → 应为空元组。"""
        oef = OkEfLogParser()
        self.assertEqual(oef.error_markers, ())
        self.assertEqual(oef.daily_success_marker, ("执行状态: 完成",))


if __name__ == "__main__":
    unittest.main()
