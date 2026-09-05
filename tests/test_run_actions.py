"""测试 src/service/run_actions.py：各 post_run/pre_run step 动作。

send_summary_mail 为最佳努力通知：send_mail 抛异常时须记明确日志且不向上抛，
以免邮件失败阻断后续 post_run 步骤（如关机）。
"""

import unittest
from unittest import mock

from src.service import run_actions


class TestSendSummaryMail(unittest.TestCase):
    """send_summary_mail：最佳努力通知，失败须记日志且不中断后续步骤。"""

    def test_logs_and_does_not_propagate_on_failure(self):
        """send_mail 抛异常：记 [mail] 错误日志、不向上抛（后续关机 step 不受影响）。"""
        result = {"entries": []}
        smtp_config = {"enabled": True, "email": "a@qq.com", "password": "pw"}
        with (
            mock.patch(
                "src.service.run_actions.send_mail",
                side_effect=RuntimeError("smtp down"),
            ),
            self.assertLogs(logger=run_actions.logger, level="ERROR") as cm,
        ):
            run_actions.send_summary_mail(result, smtp_config)
        self.assertTrue(
            any("[mail] 运行汇总邮件发送失败" in line for line in cm.output),
            msg=f"未记录邮件失败日志: {cm.output}",
        )


if __name__ == "__main__":
    unittest.main()
