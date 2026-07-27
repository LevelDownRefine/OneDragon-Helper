"""测试 src/gui/state.py：apply_weekly_timeout 的覆盖规则（含 0 不覆盖）。"""
import unittest
from unittest.mock import patch

from src.gui.state import apply_weekly_timeout


def _script(display_name="测试", run_timeout=60):
    return {"display_name": display_name, "run_timeout_seconds": run_timeout}


class TestApplyWeeklyTimeout(unittest.TestCase):
    """apply_weekly_timeout：周超时要覆盖 run_timeout_seconds，但 0 视为不覆盖。"""

    @patch("src.gui.state.get_week_num", return_value=0)
    def test_positive_overrides(self, _mock):
        """当日周超时为正数时覆盖 config.yml 原值。"""
        script = _script(run_timeout=60)
        apply_weekly_timeout(script, {"测试": [1800, 600, 600, 600, 600, 600, 600]})
        self.assertEqual(script["run_timeout_seconds"], 1800)

    @patch("src.gui.state.get_week_num", return_value=2)
    def test_zero_keeps_config_value(self, _mock):
        """当日周超时为 0 时保留 config.yml 原值（避免 ScriptChainer 把 0 当作立即杀掉）。"""
        script = _script(run_timeout=60)
        apply_weekly_timeout(script, {"测试": [1800, 600, 0, 600, 600, 600, 600]})
        self.assertEqual(script["run_timeout_seconds"], 60)

    @patch("src.gui.state.get_week_num", return_value=0)
    def test_all_zero_keeps_config_value(self, _mock):
        """整周全 0 时保留 config.yml 原值。"""
        script = _script(run_timeout=120)
        apply_weekly_timeout(script, {"测试": [0, 0, 0, 0, 0, 0, 0]})
        self.assertEqual(script["run_timeout_seconds"], 120)

    @patch("src.gui.state.get_week_num", return_value=0)
    def test_missing_entry_keeps_config_value(self, _mock):
        """weekly_timeouts 中无该脚本时保留 config.yml 原值。"""
        script = _script(run_timeout=60)
        apply_weekly_timeout(script, {})
        self.assertEqual(script["run_timeout_seconds"], 60)

    @patch("src.gui.state.get_week_num", return_value=0)
    def test_incomplete_list_keeps_config_value(self, _mock):
        """周超时不足 7 个值时保留 config.yml 原值。"""
        script = _script(run_timeout=60)
        apply_weekly_timeout(script, {"测试": [1800, 600]})
        self.assertEqual(script["run_timeout_seconds"], 60)


if __name__ == "__main__":
    unittest.main()
