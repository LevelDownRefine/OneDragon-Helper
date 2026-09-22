"""脚本图标：来源选择、默认回退、提取缓存和 PNG 编码。"""

import base64
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# 在导入 PySide6 之前设置 offscreen 平台插件（CI 无显示器环境）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QIcon, QImage, QPixmap
from PySide6.QtWidgets import QApplication

from src.gui import icons
from src.gui.icons import (
    _EXE_ICON_CACHE,
    _exe_icon,
    get_exe_icon_url,
    get_icon_source,
    get_script_icon,
)

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
        with (
            patch.object(icons, "_exe_icon") as extract,
            patch.object(icons, "_default_icon") as default,
        ):
            icon = get_script_icon(
                {"display_name": "静音", "script_type": "python", "script_path": "x.py"}
            )
        self.assertIs(icon, default.return_value)
        default.assert_called_once_with()
        extract.assert_not_called()

    def test_external_missing_exe_falls_back_to_default(self):
        with (
            patch.object(icons, "_exe_icon", return_value=None) as extract,
            patch.object(icons, "_default_icon") as default,
        ):
            icon = get_script_icon(
                {
                    "display_name": "x",
                    "script_type": "external",
                    "script_path": "C:/nope/run.exe",
                }
            )
        self.assertIs(icon, default.return_value)
        extract.assert_called_once_with("C:/nope/run.exe")
        default.assert_called_once_with()

    def test_external_existing_exe_uses_own_icon(self):
        with (
            patch.object(icons, "_exe_icon") as extract,
            patch.object(icons, "_default_icon") as default,
        ):
            icon = get_script_icon(
                {
                    "display_name": "x",
                    "script_type": "external",
                    "script_path": "C:/game/run.exe",
                }
            )
        self.assertIs(icon, extract.return_value)
        extract.assert_called_once_with("C:/game/run.exe")
        default.assert_not_called()

    def test_default_icon_fallback_is_nonempty(self):
        with (
            patch.object(icons, "_DEFAULT_ICON", None),
            patch.object(icons, "_exe_icon", return_value=None) as extract,
        ):
            first = icons._default_icon()
            self.assertFalse(first.isNull())
            self.assertIs(icons._default_icon(), first)
        extract.assert_called_once_with(icons.sys.executable)

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


class _StubIcon:
    """替代真实 QIcon，仅满足 _exe_icon 的非空判定，避免无头环境依赖平台图标提供器。"""

    def isNull(self) -> bool:  # noqa: N802  # 对齐 QIcon.isNull 命名
        return False


class TestExeIconCache(unittest.TestCase):
    """_exe_icon 仅缓存成功结果，缺失/失败不缓存，以容忍 exe 后续就位。

    旧实现用 @lru_cache 会把 ``path → None`` 永久缓存：脚本创建时 exe 尚未
    就位、首次取不到，之后 exe 出现仍取不到，需重启进程才刷新。
    """

    def setUp(self):
        self.enterContext(patch.dict(_EXE_ICON_CACHE, clear=True))

    def test_missing_returns_none_and_not_cached(self):
        """文件缺失时返回 None，且不写入缓存（否则会永久记住失败态）。"""
        missing = os.path.join(
            self.enterContext(tempfile.TemporaryDirectory()), "nope.exe"
        )
        self.assertIsNone(_exe_icon(missing))
        self.assertNotIn(missing, _EXE_ICON_CACHE)

    def test_existing_file_returns_icon_and_cached(self):
        path = str(Path(self.enterContext(tempfile.TemporaryDirectory())) / "game.exe")
        Path(path).touch()
        with patch.object(icons, "_ICON_PROVIDER") as provider:
            expected = provider.icon.return_value = _StubIcon()
            self.assertIs(_exe_icon(path), expected)
            self.assertIs(_exe_icon(path), expected)
        self.assertIs(_EXE_ICON_CACHE[path], expected)
        provider.icon.assert_called_once()

    def test_missing_then_file_appears_is_refetched(self):
        """缺失后 exe 才就位：再次请求应能取到（不因首次缺失而缓存失败）。"""
        path = os.path.join(
            self.enterContext(tempfile.TemporaryDirectory()), "later.exe"
        )
        self.assertIsNone(_exe_icon(path))
        self.assertNotIn(path, _EXE_ICON_CACHE)
        Path(path).touch()
        with patch.object(icons, "_ICON_PROVIDER") as provider:
            expected = provider.icon.return_value = _StubIcon()
            self.assertIs(_exe_icon(path), expected)
        provider.icon.assert_called_once()

    def test_null_icon_is_not_cached_and_can_be_retried(self):
        path = str(Path(self.enterContext(tempfile.TemporaryDirectory())) / "game.exe")
        Path(path).touch()
        expected = _StubIcon()
        for missing in (None, QIcon()):
            with (
                self.subTest(icon=missing),
                patch.dict(_EXE_ICON_CACHE, clear=True),
                patch.object(icons, "_ICON_PROVIDER") as provider,
            ):
                provider.icon.side_effect = [missing, expected]
                self.assertIsNone(_exe_icon(path))
                self.assertNotIn(path, _EXE_ICON_CACHE)
                self.assertIs(_exe_icon(path), expected)
                self.assertEqual(provider.icon.call_count, 2)

    def test_extraction_error_is_logged_and_can_be_retried(self):
        path = str(Path(self.enterContext(tempfile.TemporaryDirectory())) / "game.exe")
        Path(path).touch()
        expected = _StubIcon()
        with patch.object(icons, "_ICON_PROVIDER") as provider:
            provider.icon.side_effect = [OSError("extract failed"), expected]
            with self.assertLogs(icons.__name__, level="WARNING") as logs:
                self.assertIsNone(_exe_icon(path))
            self.assertIn("OSError: extract failed", logs.output[0])
            self.assertNotIn(path, _EXE_ICON_CACHE)
            self.assertIs(_exe_icon(path), expected)
        self.assertEqual(provider.icon.call_count, 2)


if __name__ == "__main__":
    unittest.main()
