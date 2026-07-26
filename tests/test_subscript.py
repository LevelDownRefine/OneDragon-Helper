"""测试 src/config/subscript.py：config 读写基础设施与相对路径解析"""
import os
import unittest

from src.config.subscript import _resolve_relative_script_paths
from src.utils import get_root_dir


class TestResolveRelativeScriptPaths(unittest.TestCase):
    """测试 _resolve_relative_script_paths：相对路径解析为绝对，绝对/空路径原样保留"""

    def test_resolves_relative_and_keeps_others(self):
        data = {
            "script_list": [
                {"display_name": "静音", "script_path": "src/python_script/mute.py"},
                {"display_name": "原神", "script_path": "D:\\games\\BetterGI.exe"},
                {"display_name": "无路径", "script_path": ""},
            ]
        }
        _resolve_relative_script_paths(data)
        root = get_root_dir()
        # 相对路径解析为基于项目根目录的绝对路径（分隔符随系统归一）
        self.assertEqual(
            os.path.abspath(data["script_list"][0]["script_path"]),
            os.path.abspath(os.path.join(root, "src/python_script", "mute.py")),
        )
        # 绝对路径原样保留
        self.assertEqual(data["script_list"][1]["script_path"], "D:\\games\\BetterGI.exe")
        # 空路径原样保留
        self.assertEqual(data["script_list"][2]["script_path"], "")


if __name__ == '__main__':
    unittest.main()
