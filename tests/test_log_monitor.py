"""测试日志解析器"""

import logging as _logging
import os
import sys
import tempfile
import unittest

# python_script/ 位于项目根（非 src/ 下），追加根目录到 sys.path 以便导入。
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from python_script import collect_log
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


if __name__ == "__main__":
    unittest.main()
