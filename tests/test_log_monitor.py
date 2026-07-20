"""测试日志解析器"""

import unittest

from src.log.log_monitor import (
    ScriptLogStatus,
    parse_log,
    OkEfLogParser,
    OkWwLogParser,
    OkNteLogParser,
    M7ALogParser,
    BGILogParser,
    ZZZLogParser,
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

    def test_parse_ok_nte_success(self):
        parser = OkNteLogParser()
        log_content = "2026-07-19 14:15:01,484 INFO TaskExecutor TaskExecutor:Successfully Executed Task"
        self.assertEqual(parser.parse_content(log_content), ScriptLogStatus.SUCCESS)

    def test_parse_ok_nte_task_completed(self):
        parser = OkNteLogParser()
        log_content = "2026-07-19 14:15:01,481 INFO TaskExecutor DailyTask:Task completed"
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
        log_content = "[13:56:11.603] [WRN] BetterGenshinImpact.GameTask.Common.TaskControl\n检查每日奖励结果：\"未领取\"，请手动检查！\n[13:56:13.291] [INF] BetterGenshinImpact.ViewModel.Pages.OneDragonFlowViewModel\n一条龙和配置组任务结束"
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
        log_content = "[20:08:32.067] [one_dragon_context.py 471] [INFO]: 开始加载实例配置 1"
        self.assertEqual(parser.parse_content(log_content), ScriptLogStatus.FAILED)


if __name__ == "__main__":
    unittest.main()
