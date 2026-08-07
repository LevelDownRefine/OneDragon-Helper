"""测试 src/service/chain_gen.py：_apply_weekly_timeout 的覆盖规则（自 weekly_timeouts.py 迁入）。"""

import unittest
from unittest.mock import patch

from src.config.subscript import DEFAULT_RUN_TIMEOUT
from src.service.chain_gen import _apply_weekly_timeout


def _script(display_name="测试"):
    return {"display_name": display_name}


class TestApplyWeeklyTimeout(unittest.TestCase):
    """_apply_weekly_timeout：统一从 weekly_timeouts 取当天值，无条目 fallback 到 DEFAULT_RUN_TIMEOUT。"""

    @patch("src.service.chain_gen._get_week_num", return_value=0)
    def test_positive_overrides(self, _mock):
        """有完整 7 格且当天为正数 → 取当天值。"""
        script = _script()
        _apply_weekly_timeout(script, {"测试": [1800, 600, 600, 600, 600, 600, 600]})
        self.assertEqual(script["run_timeout_seconds"], 1800)

    @patch("src.service.chain_gen._get_week_num", return_value=2)
    def test_zero_clamped_to_10(self, _mock):
        """当天值为 0 → 被 clamp 到 10，不再保留旧 config 值。"""
        script = _script()
        _apply_weekly_timeout(script, {"测试": [1800, 600, 0, 600, 600, 600, 600]})
        self.assertEqual(script["run_timeout_seconds"], 10)

    @patch("src.service.chain_gen._get_week_num", return_value=0)
    def test_all_zero_clamped_to_10(self, _mock):
        """整周全 0 → 每天都被 clamp 到 10。"""
        script = _script()
        _apply_weekly_timeout(script, {"测试": [0, 0, 0, 0, 0, 0, 0]})
        self.assertEqual(script["run_timeout_seconds"], 10)

    @patch("src.service.chain_gen._get_week_num", return_value=0)
    def test_missing_entry_uses_default(self, _mock):
        """weekly_timeouts 中无该脚本 → fallback 到 DEFAULT_RUN_TIMEOUT。"""
        script = _script()
        _apply_weekly_timeout(script, {})
        self.assertEqual(script["run_timeout_seconds"], DEFAULT_RUN_TIMEOUT)

    @patch("src.service.chain_gen._get_week_num", return_value=0)
    def test_incomplete_list_uses_default(self, _mock):
        """周超时不足 7 个值 → fallback 到 DEFAULT_RUN_TIMEOUT。"""
        script = _script()
        _apply_weekly_timeout(script, {"测试": [1800, 600]})
        self.assertEqual(script["run_timeout_seconds"], DEFAULT_RUN_TIMEOUT)

    @patch("src.service.chain_gen._get_week_num", return_value=1)
    def test_low_value_clamped_to_10(self, _mock):
        """当天值低于 10（如 5）→ 被 clamp 到 10。"""
        script = _script()
        _apply_weekly_timeout(script, {"测试": [1800, 5, 600, 600, 600, 600, 600]})
        self.assertEqual(script["run_timeout_seconds"], 10)


if __name__ == "__main__":
    unittest.main()
