"""Windows 拖放桥：撤销 OLE、整窗接收与句柄释放，无桌面依赖。"""

import ctypes
import unittest
from ctypes import wintypes
from unittest.mock import MagicMock, call, patch

from PySide6.QtCore import QUrl

from src.gui.file_drop import WindowsFileDrop, install_file_drop


class TestWindowsFileDrop(unittest.TestCase):
    def setUp(self):
        self.shell = MagicMock()
        self.user = MagicMock()
        self.ole = MagicMock()
        self.ole.RevokeDragDrop.return_value = 0
        self.window = MagicMock()
        self.window.winId.return_value = 1234
        self.on_drop = MagicMock()
        self.files = ["C:/中文 path/100% #1.py", "D:/run.exe"]
        self.point = (100, 300)
        self.shell.DragQueryPoint.side_effect = self.query_point
        self.shell.DragQueryFileW.side_effect = self.query_file
        for mock in (
            patch(
                "src.gui.file_drop.ctypes.WinDLL",
                side_effect=[self.shell, self.user, self.ole],
                create=True,
            ),
            patch("src.gui.file_drop.QGuiApplication.modalWindow", return_value=None),
            patch(
                "src.gui.file_drop.QTimer.singleShot",
                side_effect=lambda _, callback: callback(),
            ),
        ):
            mock.start()
            self.addCleanup(mock.stop)
        self.handler = WindowsFileDrop(self.window, self.on_drop)

    def query_point(self, handle, point):
        point._obj.x, point._obj.y = self.point
        return True

    def query_file(self, handle, index, buffer, length):
        if index == 0xFFFFFFFF:
            return len(self.files)
        if buffer is not None:
            buffer.value = self.files[index]
        return len(self.files[index])

    def message(self, message=0x0233, hwnd=1234):
        native = wintypes.MSG(hWnd=hwnd, message=message, wParam=5678)
        return self.handler.nativeEventFilter(
            b"windows_generic_MSG", ctypes.addressof(native)
        )

    def test_install_allows_only_file_messages_for_this_window(self):
        app = MagicMock()
        self.handler.install(app)
        self.ole.RevokeDragDrop.assert_called_once_with(1234)
        self.assertEqual(
            self.user.ChangeWindowMessageFilterEx.call_args_list,
            [call(1234, 0x0233, 1, None), call(1234, 0x0049, 1, None)],
        )
        self.shell.DragAcceptFiles.assert_called_once_with(1234, True)
        app.installNativeEventFilter.assert_called_once_with(self.handler)

    def test_native_drop_passes_full_paths(self):
        self.assertEqual(self.message(), (True, 0))
        self.on_drop.assert_called_once()
        # Linux 的 toLocalFile 会保留盘符前的 /；回调契约是跨平台一致的 URL。
        self.assertEqual(
            self.on_drop.call_args.args[0],
            [
                QUrl("file:///C:/中文%20path/100%25%20%231.py"),
                QUrl("file:///D:/run.exe"),
            ],
        )
        self.shell.DragFinish.assert_called_once_with(5678)

    def test_anywhere_inside_window_accepts_files(self):
        for point in ((40, 300), (600, 300), (1270, 710)):
            with self.subTest(point=point):
                self.point = point
                self.assertEqual(self.message(), (True, 0))
        self.assertEqual(self.on_drop.call_count, 3)
        self.assertEqual(self.shell.DragFinish.call_count, 3)

    def test_other_windows_and_messages_are_not_consumed(self):
        self.assertEqual(self.message(hwnd=9876), (False, 0))
        self.assertEqual(self.message(message=0x49), (False, 0))
        self.assertEqual(
            self.handler.nativeEventFilter(b"xcb_generic_event_t", 0), (False, 0)
        )
        self.shell.DragFinish.assert_not_called()

    def test_modal_window_prevents_adding(self):
        with patch(
            "src.gui.file_drop.QGuiApplication.modalWindow", return_value=object()
        ):
            self.message()
        self.on_drop.assert_not_called()
        self.shell.DragFinish.assert_called_once()

    def test_non_client_flag_does_not_discard_files(self):
        self.shell.DragQueryPoint.side_effect = None
        self.shell.DragQueryPoint.return_value = False
        self.message()
        self.on_drop.assert_called_once()
        self.shell.DragQueryPoint.assert_not_called()
        self.shell.DragFinish.assert_called_once()

    def test_failed_path_read_logs_and_releases_handle(self):
        self.shell.DragQueryFileW.side_effect = [1, 0]
        with self.assertLogs("src.gui.file_drop", level="WARNING"):
            self.message()
        self.on_drop.assert_called_once_with([])
        self.shell.DragFinish.assert_called_once_with(5678)

    def test_failed_filter_registration_is_logged(self):
        self.user.ChangeWindowMessageFilterEx.return_value = False
        with (
            patch(
                "src.gui.file_drop.ctypes.get_last_error", return_value=5, create=True
            ),
            self.assertLogs("src.gui.file_drop", level="WARNING"),
        ):
            self.handler.install(MagicMock())

    def test_other_platform_uses_qml_drop_area(self):
        with patch("src.gui.file_drop.sys.platform", "linux"):
            self.assertIsNone(install_file_drop(MagicMock(), self.window, self.on_drop))

    def test_missing_ole_registration_is_normal(self):
        self.ole.RevokeDragDrop.return_value = -2147221248
        with self.assertNoLogs("src.gui.file_drop", level="WARNING"):
            self.handler.install(MagicMock())

    def test_failed_ole_revoke_is_reported(self):
        self.ole.RevokeDragDrop.return_value = -2147024891
        with self.assertLogs("src.gui.file_drop", level="WARNING"):
            self.handler.install(MagicMock())
