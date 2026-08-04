"""GUI 工具与 UI 状态持久化。

- UI 状态持久化（config/gui_state.json）与星期计算；
- 统一的消息框 / 打开文件辅助函数（强制浅色样式，避免深色主题下全黑不可读）。
"""

import contextlib
import ctypes
import json
import logging
import os
import sys
from ctypes import wintypes
from datetime import datetime, timedelta
from functools import lru_cache

from PySide6.QtCore import QFileInfo, Qt
from PySide6.QtGui import QIcon, QImage
from PySide6.QtWidgets import QFileIconProvider, QMessageBox

from src.utils import get_root_dir, safe_path_join

logger = logging.getLogger(__name__)

# 复用的文件图标提供器：避免每个 exe 都 new 一个 QFileIconProvider 的开销
_ICON_PROVIDER = QFileIconProvider()

# 后台线程提取 exe 图标：用纯 Win32 ExtractIconExW（避开 QFileIconProvider 依赖的
# COM 化 Shell 扩展，后者在后台线程（MTA 单元）调用会失败/崩溃）。worker 取到 HICON 后
# 用纯 GDI 把它转成 QImage（不依赖 PySide6.QtWin，跨线程安全），再由主线程转 QPixmap 显示。
try:
    _shell32 = ctypes.windll.shell32
    _user32 = ctypes.windll.user32
    _gdi32 = ctypes.windll.gdi32
    _shell32.ExtractIconExW.restype = ctypes.c_int
    _shell32.ExtractIconExW.argtypes = [
        wintypes.LPCWSTR,
        ctypes.c_int,
        ctypes.POINTER(wintypes.HICON),
        ctypes.POINTER(wintypes.HICON),
        wintypes.UINT,
    ]
    _user32.GetIconInfo.argtypes = [wintypes.HICON, ctypes.c_void_p]
    _user32.GetIconInfo.restype = ctypes.c_int
    _user32.DestroyIcon.argtypes = [wintypes.HICON]
    _user32.DestroyIcon.restype = ctypes.c_int
    _gdi32.GetObjectW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p]
    _gdi32.GetObjectW.restype = ctypes.c_int
    _gdi32.GetDIBits.argtypes = [
        wintypes.HANDLE,
        wintypes.HANDLE,
        ctypes.c_uint,
        ctypes.c_uint,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint,
    ]
    _gdi32.GetDIBits.restype = ctypes.c_int
    _gdi32.CreateCompatibleDC.argtypes = [wintypes.HANDLE]
    _gdi32.CreateCompatibleDC.restype = wintypes.HANDLE
    _gdi32.DeleteDC.argtypes = [wintypes.HANDLE]
    _gdi32.DeleteDC.restype = ctypes.c_int
    _gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
    _gdi32.DeleteObject.restype = ctypes.c_int
    _ICON_EXTRACTION_AVAILABLE = True
except Exception:  # noqa: BLE001 - 非 Windows（如 CI/Linux）环境不可用
    _ICON_EXTRACTION_AVAILABLE = False


# 仅用于 GDI 图标解码的 ctypes 结构体（非 Windows 下不会被实例化）
class _ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", wintypes.BOOL),
        ("xHotspot", wintypes.DWORD),
        ("yHotspot", wintypes.DWORD),
        ("hbmMask", wintypes.HANDLE),
        ("hbmColor", wintypes.HANDLE),
    ]


class _BITMAP(ctypes.Structure):
    _fields_ = [
        ("bmType", ctypes.c_long),
        ("bmWidth", ctypes.c_long),
        ("bmHeight", ctypes.c_long),
        ("bmWidthBytes", ctypes.c_long),
        ("bmPlanes", ctypes.c_short),
        ("bmBitsPixel", ctypes.c_short),
        ("bmBits", ctypes.c_void_p),
    ]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", ctypes.c_short),
        ("biBitCount", ctypes.c_short),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


# 默认图标：没有自带图标的脚本（如 python 脚本，或 external 但取不到 exe 图标的）使用。
# 优先用当前 Python 解释器（sys.executable）的 OS 文件图标，即 Python 官方图标；
# 极个别取不到时（如冻结后 sys.executable 指向自身 exe）回退到 assets/Chtholly.ico。
_DEFAULT_ICON_PATH = safe_path_join(get_root_dir(), "assets", "Chtholly.ico")
_DEFAULT_ICON: QIcon | None = None

_STATE_FILE = safe_path_join(get_root_dir(), "config", "gui_state.json")


def load_ui_state() -> dict:
    """读取上次保存的 UI 状态"""
    if os.path.exists(_STATE_FILE):
        with open(_STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_ui_state(state: dict):
    """保存 UI 状态"""
    with open(_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def get_week_num() -> int:
    """返回星期数字：0周一 ~ 6周日。

    以凌晨 4 点为界：4 点前归前一天，例如周一 03:00 仍按上周日(6)计。
    """
    return (datetime.now() - timedelta(hours=4)).weekday()


DEFAULT_RUN_TIMEOUT = 3600
"""脚本运行默认超时秒数。当 weekly_timeouts.yml 无条目或不足 7 格时作为 fallback。"""


def apply_weekly_timeout(script: dict, weekly_timeouts: dict) -> None:
    """根据 weekly_timeouts.yml 就地设置 script['run_timeout_seconds']。

    - 有完整 7 格 → 取当天值，且不低于 10（避免 0 秒杀脚本）。
    - 无条目 / 不足 7 格 → fallback 到 DEFAULT_RUN_TIMEOUT。
    """
    assert "display_name" in script, "[state] script_list 条目缺少 display_name 字段"
    timeouts = weekly_timeouts.get(script["display_name"])
    if timeouts and len(timeouts) == 7:
        script["run_timeout_seconds"] = max(timeouts[get_week_num()], 10)
    else:
        script["run_timeout_seconds"] = DEFAULT_RUN_TIMEOUT


# ---------------------------------------------------------------------------
# 统一消息框 / 打开文件辅助（强制浅色样式，避免深色主题下全黑不可读）
# ---------------------------------------------------------------------------

_MSG_STYLE = """
QMessageBox { background-color: #ffffff; color: #1f2937; }
QMessageBox QLabel { color: #1f2937; background-color: transparent; }
QMessageBox QPushButton {
    background-color: #f1f5f9; color: #1f2937;
    border: 1px solid #cbd5e1; border-radius: 6px; padding: 6px 16px;
}
QMessageBox QPushButton:hover { background-color: #e2e8f0; }
"""


def _styled_msg_box(parent, icon, title, text):
    """构造一个样式固定的消息框（白底深字，带图标），直接 .exec() 即可。"""
    box = QMessageBox(parent)
    box.setIcon(icon)
    box.setWindowTitle(title)
    box.setText(text)
    box.setTextFormat(Qt.PlainText)
    box.setStyleSheet(_MSG_STYLE)
    return box


def _safe_startfile(parent, path, fail_text):
    """用系统默认程序打开 path；任何异常都转成清晰可读的提示，不让 GUI 崩溃。"""
    try:
        os.startfile(path)
    except OSError as e:
        _styled_msg_box(
            parent, QMessageBox.Warning, "提示", f"{fail_text}：\n{e}"
        ).exec()


# ---------------------------------------------------------------------------
# 脚本图标解析
# ---------------------------------------------------------------------------


def _default_icon() -> QIcon:
    """懒加载默认图标（缺自带图标时回退用）：优先 Python 解释器图标，否则 Chtholly。"""
    global _DEFAULT_ICON
    if _DEFAULT_ICON is None:
        python_icon = _exe_icon(sys.executable)
        _DEFAULT_ICON = (
            python_icon if python_icon is not None else QIcon(_DEFAULT_ICON_PATH)
        )
    return _DEFAULT_ICON


@lru_cache(maxsize=256)
def _exe_icon(path: str) -> QIcon | None:
    """返回 exe 自带图标（OS 文件图标，即程序内嵌图标）。

    文件缺失 / 取不到时返回 None；异常也一并吞掉，不让列表渲染崩溃。
    """
    if not path or not os.path.isfile(path):
        return None
    try:
        icon = _ICON_PROVIDER.icon(QFileInfo(path))
    except Exception:  # noqa: BLE001  # 取图标失败不应影响整个列表
        logger.warning("取 %s 的图标失败", path, exc_info=True)
        return None
    return icon if (icon is not None and not icon.isNull()) else None


def _extract_hicon(path: str) -> int:
    """在任意线程（含后台线程）提取 exe/dll 内嵌图标的 HICON 句柄（整数）。

    使用纯 Win32 ``ExtractIconExW``（不走 COM 化的 Shell 扩展），可在后台线程安全调用。
    提取到的句柄需由调用方在**主线程**用 :func:`_hicon_to_pixmap` 转成 QPixmap 后销毁。
    非 Windows / 文件缺失 / 失败均返回 0。
    """
    if not _ICON_EXTRACTION_AVAILABLE or not path or not os.path.isfile(path):
        return 0
    hicon = wintypes.HICON(0)
    try:
        # 取索引 0 的大图标；phiconSmall 传 NULL
        count = _shell32.ExtractIconExW(path, 0, ctypes.byref(hicon), None, 1)
    except Exception:  # noqa: BLE001
        logger.warning("ExtractIconExW 提取 %s 图标失败", path, exc_info=True)
        return 0
    if count <= 0:
        return 0
    return int(hicon.value)


def _hicon_to_qimage(handle: int) -> "QImage | None":
    """把 HICON 转成 QImage（BGRA→RGBA）。可在后台线程调用（纯 GDI，不依赖 PySide6.QtWin）。

    仅处理常见 32bpp 彩色图标（hbmColor 存在）；旧式单色图标返回 None（回退默认图标）。
    返回的 QImage 拥有独立内存，可安全跨线程传递到主线程。
    """
    if not handle or not _ICON_EXTRACTION_AVAILABLE or _user32 is None:
        return None
    ii = _ICONINFO()
    if _user32.GetIconInfo(handle, ctypes.byref(ii)) == 0:
        return None
    color_bmp = ii.hbmColor
    mask_bmp = ii.hbmMask
    try:
        if not color_bmp:
            return None  # 单色图标暂不处理，回退默认图标
        bmp = _BITMAP()
        if _gdi32.GetObjectW(color_bmp, ctypes.sizeof(bmp), ctypes.byref(bmp)) == 0:
            return None
        w, h = bmp.bmWidth, bmp.bmHeight
        if w <= 0 or h <= 0:
            return None
        bmi = _BITMAPINFO()
        hdr = bmi.bmiHeader
        hdr.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        hdr.biWidth = w
        hdr.biHeight = -h  # top-down
        hdr.biPlanes = 1
        hdr.biBitCount = 32
        hdr.biCompression = 0  # BI_RGB
        buf = ctypes.create_string_buffer(w * h * 4)
        hdc = _gdi32.CreateCompatibleDC(0)
        if not hdc:
            return None
        try:
            if _gdi32.GetDIBits(hdc, color_bmp, 0, h, buf, ctypes.byref(bmi), 0) == 0:
                return None
        finally:
            _gdi32.DeleteDC(hdc)
        # BGRA → RGBA（QImage.Format_RGBA8888 期望 R,G,B,A 顺序）
        data = bytearray(buf)
        for i in range(0, len(data), 4):
            data[i], data[i + 2] = data[i + 2], data[i]
        qimg = QImage(bytes(data), w, h, w * 4, QImage.Format_RGBA8888)
        return qimg.copy()  # 脱离 ctypes buffer，独立拥有内存
    finally:
        if color_bmp:
            _gdi32.DeleteObject(color_bmp)
        if mask_bmp:
            _gdi32.DeleteObject(mask_bmp)


def _destroy_hicon(handle: int) -> None:
    """释放后台线程提取的 HICON 句柄（可在主线程调用）。"""
    if handle and _ICON_EXTRACTION_AVAILABLE and _user32 is not None:
        with contextlib.suppress(Exception):
            _user32.DestroyIcon(wintypes.HICON(handle))


def get_icon_source(script_data: dict) -> str | None:
    """返回本脚本将用于显示图标的 exe 路径。

    崩铁（星铁）的 exe 图标不好看，其 exe 同目录下有 ``March7th Launcher.exe``
    图标更好看，故优先用它；其它 external 脚本用自身 exe；非 exe 图标源返回 None。
    """
    if script_data.get("script_type") != "external":
        return None
    script_path = script_data.get("script_path", "")
    launcher = os.path.join(os.path.dirname(script_path), "March7th Launcher.exe")
    if script_path and os.path.isfile(launcher):
        return launcher
    return script_path


def get_script_icon(script_data: dict) -> QIcon:
    """返回脚本在列表中显示的图标。

    - external 脚本（指向 exe）：优先使用 exe 内嵌的自带图标；
      取不到（文件缺失 / 无图标）时回退默认图标。
    - python 脚本及其他：使用默认图标。

    调用方（ScriptItem）可缓存结果，本函数仅做轻量解析与缓存。
    """
    source = get_icon_source(script_data)
    if source:
        icon = _exe_icon(source)
        if icon is not None:
            return icon
    return _default_icon()
