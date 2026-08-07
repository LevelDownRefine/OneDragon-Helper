"""测试 src/config/runner_utils.py：脚本配置合法性校验（与 runner ScriptConfig.invalid_message 对齐）。"""

import os
import tempfile
import unittest

from src.config.runner_utils import (
    collect_invalid_script_messages,
    script_invalid_message,
)


def _external_entry(**overrides):
    entry = {
        "display_name": "测试脚本",
        "script_type": "external",
        "script_path": "",
        "script_process_name": [],
        "game_process_name": "",
        "launcher_mode": False,
        "run_timeout_seconds": 3600,
        "check_done": "script_closed",
        "kill_script_after_done": True,
        "kill_game_after_done": False,
    }
    entry.update(overrides)
    return entry


class TestScriptInvalidMessage(unittest.TestCase):
    """script_invalid_message：各分支与 runner invalid_message 对齐"""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.existing = os.path.join(self.tmp_dir.name, "run.bat")
        with open(self.existing, "w", encoding="utf-8") as f:
            f.write("@echo off\n")
        self.missing = os.path.join(self.tmp_dir.name, "missing.bat")

    def test_external_valid(self):
        entry = _external_entry(script_path=self.existing)
        self.assertIsNone(script_invalid_message(entry))

    def test_external_path_empty(self):
        self.assertEqual(
            script_invalid_message(_external_entry(script_path="")), "脚本路径为空"
        )

    def test_external_path_missing(self):
        entry = _external_entry(script_path=self.missing)
        self.assertEqual(
            script_invalid_message(entry), f"脚本路径不存在 {self.missing}"
        )

    def test_python_path_empty(self):
        entry = _external_entry(script_type="python", script_path="")
        self.assertEqual(
            script_invalid_message(entry), "Python 脚本路径为空"
        )

    def test_python_path_missing(self):
        entry = _external_entry(script_type="python", script_path=self.missing)
        self.assertEqual(
            script_invalid_message(entry), f"Python 脚本不存在 {self.missing}"
        )

    def test_check_done_invalid(self):
        entry = _external_entry(script_path=self.existing, check_done="bogus")
        self.assertEqual(
            script_invalid_message(entry), "检查完成方式非法 bogus"
        )

    def test_game_process_name_empty_when_kill_game(self):
        """kill_game_after_done=True 但 game_process_name 为空 → 游戏进程名称为空"""
        entry = _external_entry(
            script_path=self.existing,
            check_done="script_closed",
            kill_game_after_done=True,
            game_process_name="",
        )
        self.assertEqual(script_invalid_message(entry), "游戏进程名称为空")

    def test_game_process_name_required_by_check_done(self):
        """check_done=game_closed 但 game_process_name 为空 → 游戏进程名称为空"""
        entry = _external_entry(
            script_path=self.existing,
            check_done="game_closed",
            kill_game_after_done=False,
            game_process_name="",
        )
        self.assertEqual(script_invalid_message(entry), "游戏进程名称为空")

    def test_game_process_name_filled_ok(self):
        entry = _external_entry(
            script_path=self.existing,
            check_done="game_closed",
            kill_game_after_done=False,
            game_process_name="Game.exe",
        )
        self.assertIsNone(script_invalid_message(entry))

    def test_launcher_mode_script_process_empty(self):
        entry = _external_entry(
            script_path=self.existing,
            launcher_mode=True,
            script_process_name=[],
            check_done="script_closed",
            kill_script_after_done=True,
        )
        self.assertEqual(script_invalid_message(entry), "启动后实际运行的程序为空")

    def test_launcher_mode_script_process_contains_launcher(self):
        launcher = os.path.join(self.tmp_dir.name, "launcher.exe")
        with open(launcher, "w", encoding="utf-8") as f:
            f.write("MZ")
        entry = _external_entry(
            script_path=launcher,
            launcher_mode=True,
            script_process_name=["launcher.exe"],
            check_done="script_closed",
        )
        self.assertEqual(
            script_invalid_message(entry),
            "启动后实际运行的程序不能包含启动程序本体 launcher.exe",
        )

    def test_run_timeout_seconds_le_zero(self):
        entry = _external_entry(script_path=self.existing, run_timeout_seconds=0)
        self.assertEqual(script_invalid_message(entry), "运行超时时间必须大于0")

    def test_run_timeout_missing_uses_default(self):
        """缺 run_timeout_seconds 时按 runner 默认 3600 处理，不误报。"""
        entry = _external_entry(script_path=self.existing)
        entry.pop("run_timeout_seconds", None)
        self.assertIsNone(script_invalid_message(entry))


class TestCollectInvalidScriptMessages(unittest.TestCase):
    """collect_invalid_script_messages：仅返回不合法项"""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.existing = os.path.join(self.tmp_dir.name, "run.bat")
        with open(self.existing, "w", encoding="utf-8") as f:
            f.write("@echo off\n")

    def test_mixed_list_returns_only_invalid(self):
        good = _external_entry(display_name="好脚本", script_path=self.existing)
        bad = _external_entry(
            display_name="坏脚本",
            script_path="",
            kill_game_after_done=True,
        )
        result = collect_invalid_script_messages([good, bad])
        self.assertEqual(result, [("坏脚本", "脚本路径为空")])

    def test_all_valid_returns_empty(self):
        good = _external_entry(script_path=self.existing)
        self.assertEqual(collect_invalid_script_messages([good]), [])


if __name__ == "__main__":
    unittest.main()
