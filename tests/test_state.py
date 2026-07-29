"""测试 src/gui/utils.py：apply_weekly_timeout 的覆盖规则。"""
import unittest
from unittest.mock import patch

from src.gui.utils import DEFAULT_RUN_TIMEOUT, apply_weekly_timeout


def _script(display_name="测试"):
    return {"display_name": display_name}


class TestApplyWeeklyTimeout(unittest.TestCase):
    """apply_weekly_timeout：统一从 weekly_timeouts 取当天值，无条目 fallback 到 DEFAULT_RUN_TIMEOUT。"""

    @patch("src.gui.utils.get_week_num", return_value=0)
    def test_positive_overrides(self, _mock):
        """有完整 7 格且当天为正数 → 取当天值。"""
        script = _script()
        apply_weekly_timeout(script, {"测试": [1800, 600, 600, 600, 600, 600, 600]})
        self.assertEqual(script["run_timeout_seconds"], 1800)

    @patch("src.gui.utils.get_week_num", return_value=2)
    def test_zero_clamped_to_10(self, _mock):
        """当天值为 0 → 被 clamp 到 10，不再保留旧 config 值。"""
        script = _script()
        apply_weekly_timeout(script, {"测试": [1800, 600, 0, 600, 600, 600, 600]})
        self.assertEqual(script["run_timeout_seconds"], 10)

    @patch("src.gui.utils.get_week_num", return_value=0)
    def test_all_zero_clamped_to_10(self, _mock):
        """整周全 0 → 每天都被 clamp 到 10。"""
        script = _script()
        apply_weekly_timeout(script, {"测试": [0, 0, 0, 0, 0, 0, 0]})
        self.assertEqual(script["run_timeout_seconds"], 10)

    @patch("src.gui.utils.get_week_num", return_value=0)
    def test_missing_entry_uses_default(self, _mock):
        """weekly_timeouts 中无该脚本 → fallback 到 DEFAULT_RUN_TIMEOUT。"""
        script = _script()
        apply_weekly_timeout(script, {})
        self.assertEqual(script["run_timeout_seconds"], DEFAULT_RUN_TIMEOUT)

    @patch("src.gui.utils.get_week_num", return_value=0)
    def test_incomplete_list_uses_default(self, _mock):
        """周超时不足 7 个值 → fallback 到 DEFAULT_RUN_TIMEOUT。"""
        script = _script()
        apply_weekly_timeout(script, {"测试": [1800, 600]})
        self.assertEqual(script["run_timeout_seconds"], DEFAULT_RUN_TIMEOUT)

    @patch("src.gui.utils.get_week_num", return_value=1)
    def test_low_value_clamped_to_10(self, _mock):
        """当天值低于 10（如 5）→ 被 clamp 到 10。"""
        script = _script()
        apply_weekly_timeout(script, {"测试": [1800, 5, 600, 600, 600, 600, 600]})
        self.assertEqual(script["run_timeout_seconds"], 10)


if __name__ == "__main__":
    unittest.main()
