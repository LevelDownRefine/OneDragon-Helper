"""测试日志解析器"""

import unittest

from src.log.log_monitor import (
    ScriptLogStatus,
    parse_log,
    OkEfLogParser,
    OkWwLogParser,
    M7ALogParser,
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
        log_content = "2026-07-19 14:15:01,481 INFO TaskExecutor DailyTask:Task completed"
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

    def test_parse_log_not_supported(self):
        result = parse_log("MAA")
        self.assertEqual(result["status"], "不支持的脚本")


if __name__ == "__main__":
    unittest.main()
