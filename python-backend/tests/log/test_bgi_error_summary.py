"""BetterGI 错误摘要保留日志正文与记录边界。"""

import unittest

from src.log.monitor import BGILogParser


class TestBgiErrorSummary(unittest.TestCase):
    def test_two_line_and_single_line_records(self):
        parser = BGILogParser()
        content = (
            "[06:35:11.058] [ERR] [Primary:S1:P23720:T1795126929493] BetterGenshinImpact.Core.Script.Dependence.Log\n"
            '脚本执行出错: "退出关卡返回大厅超时"\n\n'
            "[06:35:12.000] [INF] BetterGenshinImpact.Service.ScriptService\n正常记录\n"
            "[ERR] 单行错误\n"
            "[06:35:13.000] [ERR] BetterGenshinImpact.Service.ScriptService\n"
            "[06:35:14.000] [INF] BetterGenshinImpact.Service.ScriptService\n不可并入\n"
            "[06:35:15.000] [ERR] BetterGenshinImpact.Service.ScriptService\n\n空行后不并入\n"
        )
        errors = parser.collect_error_lines(content)
        self.assertEqual(len(errors), 4)
        self.assertIn('脚本执行出错: "退出关卡返回大厅超时"', errors[0])
        self.assertEqual(errors[1], "[ERR] 单行错误")
        self.assertTrue(errors[2].endswith("BetterGenshinImpact.Service.ScriptService"))
        self.assertTrue(errors[3].endswith("BetterGenshinImpact.Service.ScriptService"))
        self.assertEqual(parser.collect_error_lines(content, limit=1), errors[:1])
        self.assertEqual(parser.collect_error_lines(content, limit=0), [])

    def test_inline_message_and_noise(self):
        parser = BGILogParser()
        parser.error_noise = ("忽略此异常",)
        content = (
            "[06:35:11.058] [ERR] BetterGenshinImpact.Service.ScriptService 同行错误\n"
            "不属于上一行\n"
            "[06:35:12.000] [ERR] BetterGenshinImpact.Service.ScriptService\n"
            "忽略此异常\n"
        )
        self.assertEqual(
            parser.collect_error_lines(content),
            ["[06:35:11.058] [ERR] BetterGenshinImpact.Service.ScriptService 同行错误"],
        )
