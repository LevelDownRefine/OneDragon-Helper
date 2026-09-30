"""快捷方式读取：保留完整启动信息，COM 错误可恢复且不写回。"""

import unittest
from unittest.mock import MagicMock, patch

from src.utils.utils_shortcut import read_shortcut


class ComError(Exception):
    pass


class TestReadShortcut(unittest.TestCase):
    def setUp(self):
        self.com = MagicMock()
        self.com.com_error = ComError
        self.ole = MagicMock()
        self.shell = MagicMock()
        self.shortcut = self.com.CoCreateInstance.return_value
        self.shortcut.GetPath.return_value = ("C:/scripts/run.exe", None)
        self.shortcut.GetArguments.return_value = '--profile "中文 参数" --daily'
        self.shortcut.GetWorkingDirectory.return_value = "C:/scripts"
        modules = {
            "pythoncom": self.com,
            "win32com": MagicMock(),
            "win32com.shell": MagicMock(shell=self.shell),
        }
        for patcher in (
            patch.dict("sys.modules", modules),
            patch("src.utils.utils_shortcut.sys.platform", "win32"),
            patch(
                "src.utils.utils_shortcut.ctypes.OleDLL",
                return_value=self.ole,
                create=True,
            ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_reads_arguments_without_saving_shortcut(self):
        self.assertEqual(
            read_shortcut("C:/桌面/run.lnk"),
            ("C:/scripts/run.exe", '--profile "中文 参数" --daily', "C:/scripts"),
        )
        self.shortcut.QueryInterface.return_value.Load.assert_called_once_with(
            "C:/桌面/run.lnk"
        )
        self.shortcut.QueryInterface.return_value.Save.assert_not_called()
        self.ole.CoInitializeEx.assert_called_once_with(None, 2)
        self.ole.CoUninitialize.assert_called_once()

    def test_read_error_is_recoverable_and_releases_com(self):
        self.shortcut.QueryInterface.return_value.Load.side_effect = ComError(
            "bad link"
        )
        with self.assertRaisesRegex(OSError, "bad link"):
            read_shortcut("C:/桌面/bad.lnk")
        self.ole.CoUninitialize.assert_called_once()

    def test_com_initialization_failure_does_not_uninitialize(self):
        self.ole.CoInitializeEx.side_effect = OSError("not available")
        with self.assertRaisesRegex(OSError, "not available"):
            read_shortcut("C:/桌面/run.lnk")
        self.com.CoCreateInstance.assert_not_called()
        self.ole.CoUninitialize.assert_not_called()

    def test_unsupported_platform_reports_reason(self):
        with (
            patch("src.utils.utils_shortcut.sys.platform", "linux"),
            self.assertRaisesRegex(ValueError, "当前系统不支持"),
        ):
            read_shortcut("run.lnk")
        self.ole.CoInitializeEx.assert_not_called()

    def test_long_arguments_are_not_silently_truncated(self):
        arguments = "x" * 1200
        self.shortcut.GetArguments.side_effect = lambda capacity: arguments[
            : capacity - 1
        ]
        self.assertEqual(read_shortcut("run.lnk")[1], arguments)

    def test_arguments_at_buffer_limit_are_rejected(self):
        self.shortcut.GetArguments.return_value = "x" * 32767
        with self.assertRaisesRegex(ValueError, "参数过长"):
            read_shortcut("run.lnk")
        self.ole.CoUninitialize.assert_called_once()
