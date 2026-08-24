"""测试 src/service/scheduled_run.py：定时等待期应有即时状态日志。

核心回归：定时计划设置后、等待到点前，必须立即输出日志说明「正在等待至 XX:XX」，
避免等待期间静默无日志（用户无法判断进程是否在运行）。
"""

import unittest
from unittest import mock

from src.service.scheduled_run import build_pre_run_pipeline


class TestPreRunWaitLogs(unittest.TestCase):
    """build_pre_run_pipeline：定时模式的等待 step 立即打日志、不静默。"""

    def test_wait_step_emits_log_before_sleeping(self):
        # 让目标时刻恒为「未来」，进入等待分支打印「将等待至」；time.sleep 被 mock
        # 掉避免真实长睡，随后仍打印「已到达」。验证等待期不再静默。
        future = __import__("datetime").datetime(2099, 1, 1, 0, 0)
        with (
            mock.patch(
                "src.service.scheduled_run.next_target_datetime", return_value=future
            ),
            mock.patch("src.service.scheduled_run.time.sleep") as mock_sleep,
            self.assertLogs("src.service.scheduled_run", level="INFO") as cm,
        ):
            steps = build_pre_run_pipeline(target_time="00:00")
            # 定时模式应含一个等待 step（此处 mute=False，仅 _wait）。
            self.assertTrue(steps, "定时模式应产出至少一个等待 step")
            for step in steps:
                step()

        # 未真正沉睡（sleep 被 mock 替换）。
        mock_sleep.assert_called_once()
        # 关键断言：等待前/到点均有状态日志，而非静默。
        joined = "\n".join(cm.output)
        self.assertIn("定时运行已设置", joined)
        self.assertIn("已到达目标时刻", joined)

    def test_now_mode_has_no_wait_step(self):
        # 即时运行（target=now）：不应有等待 step，也就不会打等待日志。
        steps = build_pre_run_pipeline(target_time="now")
        self.assertEqual(steps, [])


if __name__ == "__main__":
    unittest.main()
