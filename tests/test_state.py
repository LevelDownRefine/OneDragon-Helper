"""测试 src/service/chain_gen.py：_resolve_daily_run 的覆盖规则（自 weekly_timeouts.py 迁入）。"""

import unittest
from unittest.mock import patch

from src.config.subscript import DEFAULT_RUN_TIMEOUT
from src.service.chain_gen import _resolve_daily_run, _resolve_weekly_start


def _script(display_name="测试"):
    # 脚本文件（.py）：脚本唯一标识 = display_name
    return {"display_name": display_name, "script_path": "scripts/test.py"}


class TestApplyWeeklyTimeout(unittest.TestCase):
    """_resolve_daily_run：统一从 weekly_timeouts 取当天值，<10 秒视为当天不运行。"""

    @patch("src.service.chain_gen.get_week_num", return_value=0)
    def test_positive_overrides(self, _mock):
        """有完整 7 格且当天 >= 10 → 取当天值并返回 True（应运行）。"""
        script = _script()
        result = _resolve_daily_run(
            script, {"测试": [1800, 600, 600, 600, 600, 600, 600]}
        )
        self.assertTrue(result)
        self.assertEqual(script["run_timeout_seconds"], 1800)

    @patch("src.service.chain_gen.get_week_num", return_value=2)
    def test_zero_skips_script(self, _mock):
        """当天值为 0 → 返回 False（不运行），且不设置超时字段。"""
        script = _script()
        result = _resolve_daily_run(
            script, {"测试": [1800, 600, 0, 600, 600, 600, 600]}
        )
        self.assertFalse(result)
        self.assertNotIn("run_timeout_seconds", script)

    @patch("src.service.chain_gen.get_week_num", return_value=0)
    def test_all_zero_skips_script(self, _mock):
        """整周全 0 → 每天都不运行。"""
        script = _script()
        result = _resolve_daily_run(script, {"测试": [0, 0, 0, 0, 0, 0, 0]})
        self.assertFalse(result)

    @patch("src.service.chain_gen.get_week_num", return_value=0)
    def test_missing_entry_uses_default(self, _mock):
        """weekly_timeouts 中无该脚本 → fallback 到 DEFAULT_RUN_TIMEOUT。"""
        script = _script()
        result = _resolve_daily_run(script, {})
        self.assertTrue(result)
        self.assertEqual(script["run_timeout_seconds"], DEFAULT_RUN_TIMEOUT)

    @patch("src.service.chain_gen.get_week_num", return_value=0)
    def test_incomplete_list_uses_default(self, _mock):
        """周超时不足 7 个值 → fallback 到 DEFAULT_RUN_TIMEOUT。"""
        script = _script()
        result = _resolve_daily_run(script, {"测试": [1800, 600]})
        self.assertTrue(result)
        self.assertEqual(script["run_timeout_seconds"], DEFAULT_RUN_TIMEOUT)

    @patch("src.service.chain_gen.get_week_num", return_value=1)
    def test_low_value_skips_script(self, _mock):
        """当天值低于 10（如 5）→ 返回 False（不运行）。"""
        script = _script()
        result = _resolve_daily_run(
            script, {"测试": [1800, 5, 600, 600, 600, 600, 600]}
        )
        self.assertFalse(result)

    @patch("src.service.chain_gen.get_week_num", return_value=0)
    def test_ten_seconds_still_runs(self, _mock):
        """边界：当天正好 10 秒 → 正常运行。"""
        script = _script()
        result = _resolve_daily_run(
            script, {"测试": [10, 600, 600, 600, 600, 600, 600]}
        )
        self.assertTrue(result)
        self.assertEqual(script["run_timeout_seconds"], 10)


class TestResolveWeeklyStart(unittest.TestCase):
    """_resolve_weekly_start：从 weekly_start_map（weekly_start.yml 全量映射）取周常起始日（1=周一~7=周日），不判断今天。"""

    def test_missing_weekly_start_returns_none(self):
        """未设置 weekly_start → None（不处理周常，保持脚本配置原样）"""
        self.assertIsNone(_resolve_weekly_start({}, "ok-ww"))
        self.assertIsNone(_resolve_weekly_start({"other": 4}, "ok-ww"))

    def test_returns_weekly_start_value(self):
        """已设置 weekly_start → 返回原值（启用/停用由 set_config 自行判断）"""
        result = _resolve_weekly_start({"ok-ww": 4}, "ok-ww")
        self.assertEqual(result, 4)

    def test_invalid_weekly_start_raises(self):
        """weekly_start 越界（0 / 8）→ assert"""
        for bad in (0, 8):
            with self.subTest(bad=bad), self.assertRaises(AssertionError):
                _resolve_weekly_start({"ok-ww": bad}, "ok-ww")


if __name__ == "__main__":
    unittest.main()
