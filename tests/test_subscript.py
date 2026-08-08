"""测试 src/config/subscript.py：相对路径解析、脚本路径读取、默认条目构造"""

import unittest
from unittest import mock

from src.config.subscript import (
    default_script_entry,
    get_script_path,
    resolve_script_path,
)
from src.utils import get_root_dir, safe_path_join


class TestResolveScriptPath(unittest.TestCase):
    """测试 resolve_script_path：相对→项目根绝对，绝对原样保留"""

    def test_relative_resolved_to_root(self):
        self.assertEqual(
            resolve_script_path("scripts/shutdown.bat"),
            safe_path_join(get_root_dir(), "scripts/shutdown.bat"),
        )

    def test_absolute_preserved(self):
        self.assertEqual(resolve_script_path("D:\\games\\x.exe"), "D:\\games\\x.exe")


class TestGetScriptPath(unittest.TestCase):
    """测试 get_script_path：相对 script_path 解析为基于项目根的绝对路径，绝对路径原样保留"""

    def test_relative_script_path_resolved_to_root(self):
        fake = {
            "script_list": [
                {"display_name": "自动关机", "script_path": "scripts/shutdown.bat"},
            ]
        }
        with (
            mock.patch("src.config.subscript._load_config_yml", return_value=fake),
            mock.patch("src.config.subscript.os.path.exists", return_value=True),
        ):
            got = get_script_path("自动关机")
        expected = safe_path_join(get_root_dir(), "scripts/shutdown.bat").replace(
            "\\", "/"
        )
        self.assertEqual(got, expected)

    def test_absolute_script_path_preserved(self):
        fake = {
            "script_list": [
                {"display_name": "原神", "script_path": "D:\\games\\BetterGI.exe"},
            ]
        }
        with (
            mock.patch("src.config.subscript._load_config_yml", return_value=fake),
            mock.patch("src.config.subscript.os.path.exists", return_value=True),
        ):
            got = get_script_path("原神")
        self.assertEqual(got, "D:/games/BetterGI.exe")


class TestDefaultScriptEntry(unittest.TestCase):
    """测试 default_script_entry 字段补全"""

    def test_default_script_entry_has_all_fields(self):
        """default_script_entry 覆盖 config.yml 全部字段，核心字段用参数值"""
        entry = default_script_entry("崩坏3", "python", "C:/a/b.py")
        self.assertEqual(entry["display_name"], "崩坏3")
        self.assertEqual(entry["script_type"], "python")
        self.assertEqual(entry["script_path"], "C:/a/b.py")
        # 关键默认字段
        self.assertEqual(entry["script_process_name"], [])
        self.assertEqual(entry["kill_script_after_done"], True)
        self.assertEqual(entry["no_log_max_retries"], 3)
        # 与真实条目字段集合一致（无 run_timeout_seconds）
        expected_keys = {
            "display_name",
            "game_label",
            "script_type",
            "script_path",
            "script_process_name",
            "game_process_name",
            "launcher_mode",
            "check_done",
            "kill_script_after_done",
            "kill_game_after_done",
            "script_arguments",
            "notify_start",
            "notify_done",
            "notify_log_interval",
            "attach_direction",
            "no_log_timeout_seconds",
            "no_log_max_retries",
            "block",
        }
        self.assertEqual(set(entry.keys()), expected_keys)


if __name__ == "__main__":
    unittest.main()
