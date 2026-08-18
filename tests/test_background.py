"""测试 src.gui.video_backdrop：QQuickWidget 视频背景层的播放/停止与回退。

VideoBackdrop 是背景视频的成熟方案：QML VideoOutput 走 Qt 场景图合成，
不创建系统 Overlay（不像 QVideoWidget 那样盖 UI）。测试用真实 QQuickWidget
基类（offscreen 下可实例化），拦截 setSource 避免真实加载，状态变化直接调
_on_status 模拟（PySide6 Signal 是 shiboken 属性，无法被 mock patch）。
"""
import os
import unittest
import warnings
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QUrl
from PySide6.QtQuickWidgets import QQuickWidget as _RealQuickWidget
from PySide6.QtWidgets import QApplication

from src.gui.video_backdrop import VideoBackdrop, is_video

# 全局 QApplication 实例（offscreen 平台，CI 无显示器）
_app = QApplication.instance() or QApplication([])


def _patch_backdrop(root=None):
    """start 构造 VideoBackdrop 所需的补丁，返回 (patchers, root)。

    真实 QQuickWidget 基类（枚举可用），拦截 setSource 避免真实 QML 加载。
    调用方需在 finally 中 stop 全部 patchers。
    """
    root = root if root is not None else MagicMock()
    patchers = [
        patch("src.gui.video_backdrop.QQuickWidget", _RealQuickWidget),
        patch.object(VideoBackdrop, "setSource"),
    ]
    for p in patchers:
        p.start()
    return patchers, root


def _make_ready_backdrop():
    """构造 VideoBackdrop 并模拟 QML Ready，返回 (backdrop, root)。"""
    patchers, root = _patch_backdrop()
    try:
        b = VideoBackdrop()
        with patch.object(b, "rootObject", return_value=root):
            b._on_status(_RealQuickWidget.Ready)
    finally:
        for p in patchers:
            p.stop()
    return b, root


class TestIsVideo(unittest.TestCase):
    """is_video：按扩展名识别视频背景。"""
    def test_video_exts(self):
        for ext in (".mp4", ".webm", ".mkv", ".mov"):
            self.assertTrue(is_video(f"clip{ext}"))

    def test_non_video_exts(self):
        for ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"):
            self.assertFalse(is_video(f"img{ext}"))

    def test_case_insensitive(self):
        self.assertTrue(is_video("CLIP.MP4"))


class TestPlayStop(unittest.TestCase):
    """play / stop：设置视频源与显隐。"""

    def test_play_sets_source_and_shows(self):
        b, root = _make_ready_backdrop()
        b.play("C:/fake/clip.mp4")
        url = QUrl.fromLocalFile("C:/fake/clip.mp4").toString()
        self.assertEqual(b._pending_source, url)
        root.setProperty.assert_called_with("sourceUrl", url)
        self.assertTrue(b.isVisible())

    def test_stop_clears_source_and_hides(self):
        b, root = _make_ready_backdrop()
        b.play("C:/fake/clip.mp4")
        b.stop()
        self.assertEqual(b._pending_source, "")
        root.setProperty.assert_called_with("sourceUrl", "")
        self.assertFalse(b.isVisible())

    def test_play_before_ready_applies_on_ready(self):
        root = MagicMock()
        patchers, _ = _patch_backdrop(root=root)
        try:
            b = VideoBackdrop()
            b.play("C:/fake/clip.mp4")  # Ready 前：只缓存 pending source
            with patch.object(b, "rootObject", return_value=root):
                b._on_status(_RealQuickWidget.Ready)  # Ready 后应用
        finally:
            for p in patchers:
                p.stop()
        self.assertEqual(
            root.setProperty.call_args[0],
            ("sourceUrl", QUrl.fromLocalFile("C:/fake/clip.mp4").toString()),
        )
        root.mediaError.connect.assert_called_once()


class TestFallback(unittest.TestCase):
    """QML 加载失败 / 媒体错误：告警一次（去重）并回退渐变。"""

    def test_media_error_falls_back_and_warns(self):
        b, root = _make_ready_backdrop()
        spy = MagicMock()
        b.fallback_requested.connect(spy)
        with self.assertWarns(RuntimeWarning):
            root.mediaError.connect.call_args[0][0]("boom")
        self.assertEqual(b._pending_source, "")  # stop 已清空
        self.assertFalse(b.isVisible())
        spy.assert_called_once_with("boom")

    def test_qml_load_error_falls_back_and_warns(self):
        patchers, _ = _patch_backdrop()
        try:
            b = VideoBackdrop()
            with self.assertWarns(RuntimeWarning):
                b._on_status(_RealQuickWidget.Error)
        finally:
            for p in patchers:
                p.stop()
        # 回退：stop 清空 source 并隐藏
        self.assertEqual(b._pending_source, "")
        self.assertFalse(b.isVisible())

    def test_double_failure_warns_once(self):
        b, root = _make_ready_backdrop()
        cb = root.mediaError.connect.call_args[0][0]
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            cb("boom1")
            count_after_first = root.setProperty.call_count
            cb("boom2")  # 第二次不应再告警、不再 stop
        self.assertEqual(len(caught), 1)
        self.assertIn("视频背景不可用", str(caught[0].message))
        self.assertEqual(root.setProperty.call_count, count_after_first)


if __name__ == "__main__":
    unittest.main()
