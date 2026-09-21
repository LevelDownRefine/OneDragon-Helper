"""测试 src/service/chain_gen.py：_resolve_daily_run 的覆盖规则（自 weekly_timeouts.py 迁入）。"""

import os
import tempfile
import unittest
from unittest.mock import patch

from src.service.chain_gen import (
    _resolve_daily_run,
    generate_chain_config,
    resolve_weekly_starts,
)
from src.utils.utils_sub_config import DEFAULT_RUN_TIMEOUT
from src.utils.utils_yaml import load_yaml


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


class TestResolveWeeklyStarts(unittest.TestCase):
    """resolve_weekly_starts：从 weekly_start_map 取该脚本各周常的起始日（条目级），不判断今天。"""

    def test_missing_weekly_start_returns_empty(self):
        """未设置 weekly_start → 空 dict（不处理周常，保持脚本配置原样）"""
        self.assertEqual(resolve_weekly_starts({}, "ok-ww"), {})
        self.assertEqual(resolve_weekly_starts({"other": {"周常": 4}}, "ok-ww"), {})

    def test_returns_weekly_start_values(self):
        """已设置 → 返回该脚本各周常的起始日（启用/停用由 weekly 模块自行判断）"""
        result = resolve_weekly_starts(
            {"March7th-Launcher": {"货币战争": 4, "历战余响": 5}}, "March7th-Launcher"
        )
        self.assertEqual(result, {"货币战争": 4, "历战余响": 5})

    def test_invalid_weekly_start_raises(self):
        """weekly_start 越界（0 / 8）→ assert"""
        for bad in (0, 8):
            with self.subTest(bad=bad), self.assertRaises(AssertionError):
                resolve_weekly_starts({"ok-ww": {"幻梦游园": bad}}, "ok-ww")

    def test_non_dict_entry_raises(self):
        """条目不是 {周常: 起始日} 结构 → assert（旧格式不留兼容）"""
        with self.assertRaises(AssertionError):
            resolve_weekly_starts({"ok-ww": 4}, "ok-ww")


class TestGenerateChainConfig(unittest.TestCase):
    """generate_chain_config：名单是唯一判据，链内条目统一显式写 enabled=True。"""

    @staticmethod
    def _write(config: dict, names: set[str]) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            out = generate_chain_config(
                config, names, out_path=os.path.join(tmp, "today.yml")
            )
            return load_yaml(out)

    def test_only_named_scripts_included_with_enabled_true(self):
        config = {
            "script_list": [
                {"script_path": "scripts/a.py", "display_name": "甲"},
                {"script_path": "scripts/b.py", "display_name": "乙"},
            ]
        }
        data = self._write(config, {"甲"})
        self.assertEqual([s["display_name"] for s in data["script_list"]], ["甲"])
        self.assertIs(data["script_list"][0]["enabled"], True)

    def test_residual_enabled_field_does_not_exclude_script(self):
        """config.yml 的历史残留 enabled=False 不再参与判定（勾选已改内存态）。"""
        config = {
            "script_list": [
                {"script_path": "scripts/b.py", "display_name": "乙", "enabled": False},
            ]
        }
        data = self._write(config, {"乙"})
        self.assertEqual([s["display_name"] for s in data["script_list"]], ["乙"])
        self.assertIs(data["script_list"][0]["enabled"], True)


if __name__ == "__main__":
    unittest.main()
