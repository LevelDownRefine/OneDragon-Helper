"""测试 src/gui/icons.py：get_script_icon / get_icon_source 的图标源选择。"""

import os
import sys
import unittest

# 在导入 PySide6 之前设置 offscreen 平台插件（CI 无显示器环境）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.gui.icons import get_icon_source, get_script_icon

# 全局 QApplication 实例（测试共享）
_app = QApplication.instance() or QApplication([])


class TestGetScriptIcon(unittest.TestCase):
    """测试 get_script_icon：external 用 exe 自带图标，其余用默认图标。"""

    def test_scripts_uses_default_icon(self):
        """python 脚本无自带图标 → 返回非空的默认图标"""
        icon = get_script_icon(
            {"display_name": "静音", "script_type": "python", "script_path": "x.py"}
        )
        self.assertFalse(icon.isNull())

    def test_external_missing_exe_falls_back_to_default(self):
        """external 但 exe 不存在 → 回退到非空的默认图标（不崩溃）"""
        icon = get_script_icon(
            {
                "display_name": "x",
                "script_type": "external",
                "script_path": "C:/nope/run.exe",
            }
        )
        self.assertFalse(icon.isNull())

    def test_external_existing_exe_uses_own_icon(self):
        """external 且 exe 存在 → 返回该 exe 自带图标（非空）。"""
        icon = get_script_icon(
            {
                "display_name": "x",
                "script_type": "external",
                "script_path": sys.executable,
            }
        )
        self.assertFalse(icon.isNull())

    def test_external_uses_own_exe_as_icon_source(self):
        """external 脚本：图标源即其解析后的自身 exe 路径（崩铁 canonical 已是 Launcher）。"""
        data = {
            "display_name": "崩铁",
            "script_type": "external",
            "script_path": "D:/game_helper/March7thAssistant/March7th Launcher.exe",
        }
        self.assertEqual(
            get_icon_source(data),
            "D:/game_helper/March7thAssistant/March7th Launcher.exe",
        )


if __name__ == "__main__":
    unittest.main()
