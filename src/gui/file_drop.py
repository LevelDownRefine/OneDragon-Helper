"""Windows 文件拖放兼容：管理员窗口接收资源管理器的 WM_DROPFILES。"""

import ctypes
import logging
import sys
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QTimer, QUrl
from PySide6.QtGui import QGuiApplication

logger = logging.getLogger(__name__)

_WM_DROPFILES = 0x0233
_WM_COPYGLOBALDATA = 0x0049


class WindowsFileDrop(QAbstractNativeEventFilter):
    """主窗口全区域接收文件路径，持久化仍交给原添加入口。"""

    def __init__(self, window, on_drop):
        super().__init__()
        self._window = window
        self._on_drop = on_drop
        self._hwnd = int(window.winId())
        self._shell = ctypes.WinDLL("shell32", use_last_error=True)
        self._user = ctypes.WinDLL("user32", use_last_error=True)
        self._ole = ctypes.WinDLL("ole32", use_last_error=True)
        self._ole.RevokeDragDrop.argtypes = [wintypes.HWND]
        self._ole.RevokeDragDrop.restype = ctypes.c_long
        self._shell.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
        self._shell.DragAcceptFiles.restype = None
        self._shell.DragQueryFileW.argtypes = [
            wintypes.HANDLE,
            wintypes.UINT,
            wintypes.LPWSTR,
            wintypes.UINT,
        ]
        self._shell.DragQueryFileW.restype = wintypes.UINT
        self._shell.DragFinish.argtypes = [wintypes.HANDLE]
        self._shell.DragFinish.restype = None
        self._user.ChangeWindowMessageFilterEx.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.DWORD,
            ctypes.c_void_p,
        ]
        self._user.ChangeWindowMessageFilterEx.restype = wintypes.BOOL

    def install(self, app):
        # Qt 的 OLE 注册优先于 WM_DROPFILES，跨权限时会先拒绝拖放。
        # Windows 统一使用整窗文件拖放，必须先撤销这份 OLE 注册。
        result = self._ole.RevokeDragDrop(self._hwnd)
        if result not in (0, -2147221248):  # S_OK / DRAGDROP_E_NOTREGISTERED
            logger.warning("撤销 Qt 文件拖放注册失败：HRESULT %#x", result & 0xFFFFFFFF)
        # 按窗口放行文件拖放所需的两条消息，不改应用权限或进程级过滤器。
        for message in (_WM_DROPFILES, _WM_COPYGLOBALDATA):
            if not self._user.ChangeWindowMessageFilterEx(self._hwnd, message, 1, None):
                logger.warning(
                    "启用文件拖放消息 %#x 失败：WinError %d",
                    message,
                    ctypes.get_last_error(),
                )
        self._shell.DragAcceptFiles(self._hwnd, True)
        app.installNativeEventFilter(self)
        logger.info("[file_drop] 已启用整窗文件拖入（WM_DROPFILES）")

    def nativeEventFilter(self, event_type, message):
        if event_type != b"windows_generic_MSG":
            return False, 0
        msg = wintypes.MSG.from_address(int(message))
        if msg.hWnd != self._hwnd or msg.message != _WM_DROPFILES:
            return False, 0
        urls = []
        try:
            if QGuiApplication.modalWindow() is not None:
                logger.info("[file_drop] 对话框打开期间忽略文件拖入")
                return True, 0
            # 消息已命中主窗口，整窗接收不再按客户区标记过滤。
            count = self._shell.DragQueryFileW(msg.wParam, 0xFFFFFFFF, None, 0)
            logger.info("[file_drop] 收到 %d 个拖入文件", count)
            for index in range(count):
                length = self._shell.DragQueryFileW(msg.wParam, index, None, 0)
                buffer = ctypes.create_unicode_buffer(length + 1)
                if not length or not self._shell.DragQueryFileW(
                    msg.wParam, index, buffer, length + 1
                ):
                    logger.warning("读取拖入的第 %d 个文件路径失败", index + 1)
                    continue
                urls.append(QUrl.fromLocalFile(buffer.value))
        finally:
            self._shell.DragFinish(msg.wParam)
        # 退出系统消息回调后再刷新模型与配置，空路径也交给添加入口提示失败。
        QTimer.singleShot(0, lambda: self._on_drop(urls))
        return True, 0


def install_file_drop(app, window, on_drop):
    """返回需保持存活的原生过滤器；其他平台使用 QML DropArea。"""
    if sys.platform != "win32":
        return None
    handler = WindowsFileDrop(window, on_drop)
    handler.install(app)
    return handler
