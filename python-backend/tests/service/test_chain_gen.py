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
    """周超时按当天取值；不足 10 秒不运行，缺省使用默认超时。"""

    def test_daily_timeout_or_default(self):
        for name, day, values, expected in (
            ("positive", 0, [1800, 600, 600, 600, 600, 600, 600], 1800),
            ("boundary", 0, [10, 600, 600, 600, 600, 600, 600], 10),
            ("zero_today", 2, [1800, 600, 0, 600, 600, 600, 600], None),
            ("all_zero", 0, [0] * 7, None),
            ("below_boundary", 1, [1800, 5, 600, 600, 600, 600, 600], None),
            ("missing", 0, None, DEFAULT_RUN_TIMEOUT),
            ("incomplete", 0, [1800, 600], DEFAULT_RUN_TIMEOUT),
        ):
            with (
                self.subTest(name=name),
                patch("src.service.chain_gen.get_week_num", return_value=day),
            ):
                script = _script()
                weekly = {} if values is None else {"测试": values}
                self.assertEqual(
                    _resolve_daily_run(script, weekly), expected is not None
                )
                if expected is None:
                    self.assertNotIn("run_timeout_seconds", script)
                else:
                    self.assertEqual(script["run_timeout_seconds"], expected)


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

    def test_disabled_start_day_is_valid(self):
        """0（不启用，DISABLED_START_DAY）合法通过，下游经 is_weekly_start_reached 折算为停用"""
        result = resolve_weekly_starts({"ok-ww": {"幻梦游园": 0}}, "ok-ww")
        self.assertEqual(result, {"幻梦游园": 0})

    def test_out_of_range_weekly_start_raises(self):
        """weekly_start 越界（8）→ assert；0 与不启用语义由上面用例覆盖"""
        for bad in (8, -1):
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
        """config.yml 残留的 enabled=False 不影响入链。"""
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
