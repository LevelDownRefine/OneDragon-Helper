"""测试 src/config/subscript.py：相对路径解析与脚本路径读取"""

import unittest
from unittest import mock

from src.config.subscript import get_script_path, resolve_script_path
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
        with mock.patch("src.config.subscript._load_config_yml", return_value=fake):
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


if __name__ == "__main__":
    unittest.main()
