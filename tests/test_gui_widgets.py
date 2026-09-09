"""测试 src/gui/icons.py：get_script_icon / get_icon_source 的图标源选择。"""

import base64
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# 在导入 PySide6 之前设置 offscreen 平台插件（CI 无显示器环境）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QIcon, QImage, QPixmap
from PySide6.QtWidgets import QApplication

from src.gui.icons import get_exe_icon_url, get_icon_source, get_script_icon

# 全局 QApplication 实例（测试共享）
_app = QApplication.instance() or QApplication([])


class TestExeIconUrl(unittest.TestCase):
    def setUp(self):
        self.native = MagicMock()
        self.native.ExtractIconExW.return_value = 1
        for mock in (
            patch("src.gui.icons.sys.platform", "win32"),
            patch("src.gui.icons.ctypes.WinDLL", return_value=self.native, create=True),
            patch("src.gui.icons.os.path.isfile", return_value=True),
        ):
            mock.start()
            self.addCleanup(mock.stop)

    def test_png_url_contains_extracted_icon(self):
        pixmap = QPixmap(64, 64)
        pixmap.fill(QColor("#348FCA"))
        with patch("src.gui.icons._exe_icon", return_value=QIcon(pixmap)) as extract:
            url = get_exe_icon_url("C:/游戏/Game.exe")
        extract.assert_called_once_with("C:/游戏/Game.exe")
        self.native.ExtractIconExW.assert_called_once_with(
            "C:/游戏/Game.exe", -1, None, None, 0
        )
        self.assertTrue(url.startswith("data:image/png;base64,"))
        image = QImage.fromData(base64.b64decode(url.split(",", 1)[1]), "PNG")
        self.assertEqual(image.pixelColor(32, 32), QColor("#348FCA"))

    def test_missing_file_does_not_extract_icon(self):
        with patch("src.gui.icons.os.path.isfile", return_value=False):
            self.assertEqual(get_exe_icon_url("C:/missing.exe"), "")
        self.native.ExtractIconExW.assert_not_called()

    def test_no_embedded_icon_or_native_failure_returns_empty(self):
        for count in (0, 0xFFFFFFFF):
            with self.subTest(count=count), patch("src.gui.icons._exe_icon") as extract:
                self.native.ExtractIconExW.return_value = count
                self.assertEqual(get_exe_icon_url("C:/game.exe"), "")
                extract.assert_not_called()

    def test_missing_or_null_qt_icon_returns_empty(self):
        for icon in (None, QIcon()):
            with (
                self.subTest(icon=icon),
                patch("src.gui.icons._exe_icon", return_value=icon),
            ):
                self.assertEqual(get_exe_icon_url("C:/game.exe"), "")

    def test_encoding_failure_returns_empty_and_logs(self):
        icon = MagicMock()
        icon.pixmap.return_value.isNull.return_value = False
        icon.pixmap.return_value.save.return_value = False
        with (
            patch("src.gui.icons._exe_icon", return_value=icon),
            self.assertLogs("src.gui.icons", level="WARNING"),
        ):
            self.assertEqual(get_exe_icon_url("C:/game.exe"), "")


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
