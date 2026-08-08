"""脚本图标相关逻辑（与 UI 状态/消息框、控件职责分离）。

集中管理图标从「源」到「显示」的全部环节：

- 图标源解析：``get_icon_source`` / ``get_script_icon`` / ``_default_icon``，决定一个
  脚本该用哪个 exe 的图标（external 用 exe 内嵌图标，其余用 Python 默认图标）。
- 图标提取（Windows）：用纯 Win32 + GDI 在后台线程取 exe 内嵌 HICON 并转成
  ``QImage``，避开 ``QFileIconProvider`` 在后台线程（MTA 单元）调用 Shell 易失败/崩溃的坑，
  也不依赖 PySide6.QtWin（本机 PySide6 6.8 已无该模块）。
- 后台异步加载：``_IconLoadWorker`` + ``QThreadPool`` 把最慢的「加载 exe / 读图标资源」
  挪出主线程；结果经信号回主线程，由 ``on_script_icon_loaded`` 转成 ``QPixmap`` 显示并缓存。

非 Windows（CI/Linux）``_ICON_EXTRACTION_AVAILABLE`` 为 False，提取与后台加载自动降级为
默认占位图标。
"""

import contextlib
import ctypes
import logging
import os
import sys
from ctypes import wintypes
from functools import lru_cache

from PySide6.QtCore import (
    QFileInfo,
    QObject,
    QRunnable,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
)
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import QFileIconProvider

from src.config.subscript import resolve_script_path
from src.utils import get_root_dir, safe_path_join

logger = logging.getLogger(__name__)

# 复用的文件图标提供器：避免每个 exe 都 new 一个 QFileIconProvider 的开销
_ICON_PROVIDER = QFileIconProvider()

# 后台线程提取 exe 图标：用纯 Win32 SHDefExtractIconW + 纯 GDI 转 QImage（跨线程安全），
# 主线程只做轻量的 QImage → QPixmap 转换。worker 取到 HICON 后由纯 GDI 把它转成 QImage
# （不依赖 PySide6.QtWin），再由主线程转 QPixmap 显示。
# 注：以下 ctypes 句柄先初始化为 None。非 Windows（CI/Linux）下 ctypes.windll 不存在，
_shell32 = _user32 = _gdi32 = _ole32 = None
_ICON_EXTRACTION_AVAILABLE = False
if sys.platform == "win32":
    _shell32 = ctypes.windll.shell32
    _user32 = ctypes.windll.user32
    _gdi32 = ctypes.windll.gdi32
    _shell32.SHDefExtractIconW.restype = ctypes.c_long
    _shell32.SHDefExtractIconW.argtypes = [
        wintypes.LPCWSTR,
        ctypes.c_int,
        wintypes.UINT,
        ctypes.POINTER(wintypes.HICON),
        ctypes.POINTER(wintypes.HICON),
        wintypes.UINT,
    ]
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
    _user32.LoadImageW.restype = wintypes.HANDLE
    _user32.LoadImageW.argtypes = [
        wintypes.HANDLE,  # hInst（从文件加载时为 NULL）
        wintypes.LPCWSTR,  # name
        wintypes.UINT,  # type
        ctypes.c_int,  # cxDesired
        ctypes.c_int,  # cyDesired
        wintypes.UINT,  # fuLoad
    ]
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
    # Shell 高质量图标提取（取高清源），以及后台线程所需的 COM 初始化
    _ole32 = ctypes.windll.ole32
    _ole32.CoInitializeEx.restype = ctypes.c_long
    _ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    _ole32.CoUninitialize.argtypes = []
    _ole32.CoUninitialize.restype = None
    _ICON_EXTRACTION_AVAILABLE = True

# 后台提取时向系统请求的目标像素尺寸：尽量取高清源（系统会选 exe 内最接近的图标资源
# 并缩放），再由界面按实际显示尺寸 + DPR 精确缩放，避免模糊。纯 GDI 常量。
_IMAGE_ICON = 1  # IMAGE_ICON
_LR_LOADFROMFILE = 0x10  # LR_LOADFROMFILE
_ICON_DESIRED_SIZE = 64
# SHDefExtractIconW 的 nIconSize 是目标像素尺寸：64px 源对 28px×DPR(≈56px) 的显示足够清晰，
# 且提取比 256px 高清源快数倍（如崩铁 107ms→20-30ms）。COM 初始化用 STA 单元
_COINIT_APARTMENTTHREADED = 0x2  # COINIT_APARTMENTTHREADED


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

# 已转换的 exe 图标（仅主线程读写，key=exe 路径，避免重复后台提取）
_EXE_ICON_PIXMAP_CACHE: dict[str, QPixmap] = {}


def _default_icon() -> QIcon:
    """懒加载默认图标（缺自带图标时回退用）：优先 Python 解释器图标，否则 Chtholly。"""
    global _DEFAULT_ICON
    if _DEFAULT_ICON is None:
        python_icon = _exe_icon(sys.executable)
        _DEFAULT_ICON = (
            python_icon if python_icon is not None else QIcon(_DEFAULT_ICON_PATH)
        )
    return _DEFAULT_ICON


@lru_cache
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


def _init_com_for_thread() -> None:
    """在后台 worker 线程初始化 COM（STA 单元），供 SHDefExtractIconW 正常工作。

    调用方须在线程结束/异常时配对的调用 :func:`_uninit_com_for_thread`。非 Windows
    环境或 ole32 不可用时静默跳过（图标提取会走 GDI 回退路径）。
    """
    if not _ICON_EXTRACTION_AVAILABLE or _ole32 is None:
        return
    with contextlib.suppress(Exception):
        _ole32.CoInitializeEx(0, _COINIT_APARTMENTTHREADED)


def _uninit_com_for_thread() -> None:
    """与 :func:`_init_com_for_thread` 配对，释放本线程的 COM 单元。"""
    if _ICON_EXTRACTION_AVAILABLE and _ole32 is not None:
        with contextlib.suppress(Exception):
            _ole32.CoUninitialize()


def _extract_hicon(path: str) -> int:
    """在任意线程（含后台线程）提取 exe/dll 内嵌图标的 HICON 句柄（整数）。

    优先用 Shell 的 ``SHDefExtractIconW`` 取高清源（真正的高清，避开 32px 固定尺寸），
    再由界面按显示尺寸 + DPR 精确缩放；失败再回退 ``LoadImageW`` / ``ExtractIconExW``
    （系统默认尺寸）。非 Windows / 文件缺失 / 失败均返回 0。
    """
    if not _ICON_EXTRACTION_AVAILABLE or not path or not os.path.isfile(path):
        return 0
    # 优先：Shell 取高清图标（需要 COM/STA，由 worker 线程初始化）
    if _ole32 is not None:
        try:
            phicon = wintypes.HICON(0)
            hr = _shell32.SHDefExtractIconW(
                path, 0, 0, ctypes.byref(phicon), None, _ICON_DESIRED_SIZE
            )
            if hr >= 0 and phicon.value:
                return int(phicon.value)
        except Exception:  # noqa: BLE001
            logger.warning(
                "SHDefExtractIconW 提取 %s 图标失败，回退 GDI", path, exc_info=True
            )
    # 回退 1：大尺寸 LoadImage（纯 GDI，无 COM 单元限制）
    try:
        hicon = _user32.LoadImageW(
            0,
            path,
            _IMAGE_ICON,
            _ICON_DESIRED_SIZE,
            _ICON_DESIRED_SIZE,
            _LR_LOADFROMFILE,
        )
        if hicon:
            return int(hicon)
    except Exception:  # noqa: BLE001
        logger.warning(
            "LoadImageW 提取 %s 图标失败，回退 ExtractIconExW", path, exc_info=True
        )
    # 回退 2：系统默认尺寸
    hicon = wintypes.HICON(0)
    try:
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
    """返回脚本图标所用的 exe 路径（崩铁优先同目录 March7th Launcher.exe）。"""
    if script_data.get("script_type") != "external":
        return None
    raw = script_data.get("script_path", "")
    if not raw:
        return None
    script_path = resolve_script_path(raw)
    launcher = os.path.join(os.path.dirname(script_path), "March7th Launcher.exe")
    if os.path.isfile(launcher):
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


class _IconLoadSignals(QObject):
    """后台提取完成信号：(exe 路径, 转换好的 QImage 或 None)。"""

    finished = Signal(str, object)


class _IconLoadWorker(QRunnable):
    """在后台线程提取单个 exe 图标（HICON→QImage，纯 GDI），结果回传主线程。"""

    def __init__(self, source: str):
        super().__init__()
        self.source = source
        self.signals = _IconLoadSignals()

    def run(self):
        _init_com_for_thread()
        try:
            handle = _extract_hicon(self.source)
            qimg = _hicon_to_qimage(handle)
            _destroy_hicon(handle)
            self.signals.finished.emit(self.source, qimg)
        finally:
            _uninit_com_for_thread()


def _schedule_icon_load(item, script_data: dict) -> None:
    """external 图标：先查缓存；未命中则延迟到事件循环空闲后提交后台线程提取。

    非 Windows 环境（CI/Linux）无 Win32 图标提取能力，直接保持默认占位图标即可。
    """
    if not _ICON_EXTRACTION_AVAILABLE:
        return
    source = get_icon_source(script_data)
    if not source:
        return
    cached = _EXE_ICON_PIXMAP_CACHE.get(source)
    if cached is not None:
        item.icon_label.setPixmap(cached)
        return
    worker = _IconLoadWorker(source)
    worker.signals.finished.connect(item._on_icon_loaded)
    # 延迟提交：singleShot(0) 在事件循环空闲（window.show() 首帧渲染完成）后才触发，
    # 避免构造期立即启动 14 个提取线程与首帧渲染抢 CPU，拖慢启动（见 2026-08-08 启动分析）。
    QTimer.singleShot(0, lambda: QThreadPool.globalInstance().start(worker))


def on_script_icon_loaded(label, source: str, qimg) -> None:
    """主线程把后台提取的 QImage 转成 QPixmap 并设置到 label，同时写入缓存。

    提取逻辑在图标模块内完成，本函数只负责「显示 + 缓存」，控件侧轻量调用即可。
    高 DPI 屏下按 ``devicePixelRatio`` 缩放并设回 DPR，不模糊。
    """
    if qimg is not None and not qimg.isNull():
        size = label.width()
        dpr = label.devicePixelRatioF()
        target = int(round(size * dpr))
        pix = QPixmap.fromImage(qimg).scaled(
            target, target, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        pix.setDevicePixelRatio(dpr)
        label.setPixmap(pix)
        _EXE_ICON_PIXMAP_CACHE[source] = pix
