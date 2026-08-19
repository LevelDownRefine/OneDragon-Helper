"""视频背景层：QQuickWidget 承载 QML VideoOutput（Qt Quick 场景图合成）。

根因（调研结论）：QVideoWidget 在 Windows 走 WinId 渲染路径，视频帧直接提交
系统合成器的覆盖层（Dedicated Video Plane），完全绕开 Qt 的 paintEvent 与窗口
合成管线——因此任何 z-order / 布局 / 父子窗口调整都拦不住它盖住 UI（官网也
明说"只要视频窗口拥有独立句柄，raise() 也无济于事"）。

成熟方案（Qt 官方 qmlvideo 示例同思路）：把视频放进 Qt 自己的合成管线。
QQuickWidget 是"真正的 QWidget"（官方文档：行为像普通控件，不受原生窗口叠放
限制），内部用 QQuickRenderControl 离屏渲染 QML 场景到纹理、再按普通 widget
绘制——VideoOutput 作为场景图节点与半透明 UI 同一管线 GPU 合成，不创建系统
Overlay，因此不盖 UI、不卡。

VideoBackdrop 只承载视频模式；图片/渐变仍由主窗口 paintEvent 绘制（零回归）。
"""

import os
import warnings

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QColor
from PySide6.QtQuickWidgets import QQuickWidget

from src.config.subscript import resolve_script_path
from src.gui.theme import C_WINDOW_BG

# QML 场景文件（相对项目根；VideoOutput 全画布 cover + 循环 + 错误上报）
QML_PATH = "assets/bg_video.qml"

# 走 QML VideoOutput 的扩展名（其余一律按图片处理）
VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".mov"}


def is_video(path: str) -> bool:
    """扩展名识别是否走视频背景。"""
    return os.path.splitext(path)[1].lower() in VIDEO_EXTS


class VideoBackdrop(QQuickWidget):
    """视频背景层（QML VideoOutput，场景图 GPU 合成）。

    懒创建：只在需要视频背景时实例化；stop 后隐藏。
    QML 场景加载失败 / 媒体解码错误 → 告警一次（去重）并发 fallback_requested，
    由主窗口回退渐变。
    """

    fallback_requested = Signal(str)  # 视频不可用（reason）→ 主窗口回退渐变

    def __init__(self, parent=None):
        super().__init__(parent)
        self._root = None  # QML 根对象（Ready 后可用）
        self._failed = False  # 回退去重：一次失败只告警一次
        self._pending_source = ""  # Ready 前暂存的视频 URL
        qml_path = resolve_script_path(QML_PATH)
        assert qml_path and os.path.isfile(qml_path), (
            f"[video_backdrop] QML 场景缺失: {QML_PATH}"
        )
        self.setResizeMode(QQuickWidget.SizeRootObjectToView)
        self.setClearColor(QColor(C_WINDOW_BG))
        self.statusChanged.connect(self._on_status)
        self.setSource(QUrl.fromLocalFile(qml_path))
        self.setVisible(False)

    # ── 外部接口 ─────────────────────────────────────────────────────────
    def play(self, abs_path: str):
        """进入视频模式并循环播放。调用方须保证 abs_path 存在。"""
        self._failed = False
        self.setVisible(True)
        self._pending_source = QUrl.fromLocalFile(abs_path).toString()
        self._apply_source()

    def stop(self):
        """停止播放并隐藏（切图片/渐变或窗口关闭时调用）。"""
        self._pending_source = ""
        self._apply_source()
        self.setVisible(False)

    # ── 内部 ─────────────────────────────────────────────────────────────
    def _apply_source(self):
        if self._root is not None:
            self._root.setProperty("sourceUrl", self._pending_source)

    def _on_status(self, status):
        if status == QQuickWidget.Error:
            errors = self.errors()
            detail = errors[0].description() if errors else "QML 场景加载失败"
            self._fallback(detail)
            return
        if status == QQuickWidget.Ready:
            self._root = self.rootObject()
            assert self._root is not None, (
                "[video_backdrop] QML Ready 但 rootObject 为空"
            )
            self._root.mediaError.connect(self._on_media_error)
            self._apply_source()

    def _on_media_error(self, reason):
        self._fallback(str(reason) or "媒体解码错误")

    def _fallback(self, reason: str):
        """视频不可用：告警一次（去重）并回退渐变。"""
        if self._failed:
            return
        self._failed = True
        warnings.warn(
            f"[bg] 视频背景不可用，回退：{reason}",
            RuntimeWarning,
            stacklevel=2,
        )
        self.stop()
        self.fallback_requested.emit(reason)
