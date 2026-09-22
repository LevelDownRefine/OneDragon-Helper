"""视频首帧缓存与实际 QML 占位切换。"""

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QUrl  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtMultimedia import QtVideo, QVideoFrame, QVideoSink  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.gui.controllers.background import BackgroundController  # noqa: E402
from src.service.app_service import AppService  # noqa: E402


class TestVideoWallpaper(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.video = Path(self.tmp.name) / "clip.mp4"
        self.video.write_bytes(b"video")
        patcher = patch(
            "src.utils.utils_wallpaper.get_wallpaper_json_path_under_root",
            return_value=str(Path(self.tmp.name) / "wallpaper.json"),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.service = AppService()
        self.ctrl = BackgroundController(MagicMock(), self.service, MagicMock())
        self.sink = QVideoSink()
        self.game = {"script_name": "game", "color": "#123456", "char": "游"}
        self.apply()

    def apply(self, path=None):
        with patch.object(
            self.ctrl, "resolve_bg", return_value=str(path or self.video)
        ):
            self.ctrl.apply_current(self.game)

    def frame(self, color="red", width=320, height=180):
        img = QImage(width, height, QImage.Format_RGB32)
        img.fill(color)
        self.sink.setVideoFrame(QVideoFrame(img))

    def ready(self, version=None):
        return self.ctrl.video_frame_ready(
            self.sink, self.ctrl.background_version if version is None else version
        )

    def test_invalid_then_valid_frame_creates_reusable_preview(self):
        self.assertEqual(self.ctrl.background_preview_url, "")
        self.assertFalse(self.ready())
        self.frame()
        self.assertTrue(self.ready())
        preview = self.ctrl.background_preview_url
        img = QImage(QUrl(preview).toLocalFile())
        self.assertEqual((img.width(), img.height()), (320, 180))
        self.assertGreater(img.pixelColor(10, 10).red(), 240)
        self.apply()
        self.assertEqual(self.ctrl.background_preview_url, preview)
        self.frame("blue")
        with patch.object(self.service, "save_video_preview") as save:
            self.assertTrue(self.ready())
        save.assert_not_called()

    def test_large_portrait_frame_preserves_display_orientation(self):
        self.frame(width=3000, height=1500)
        frame = self.sink.videoFrame()
        frame.setRotation(QtVideo.Rotation.Clockwise90)
        frame.setMirrored(True)
        self.sink.setVideoFrame(frame)
        self.assertTrue(self.ready())
        img = QImage(QUrl(self.ctrl.background_preview_url).toLocalFile())
        self.assertEqual((img.width(), img.height()), (960, 1920))

    def test_old_frames_rejected_after_switch_including_same_path(self):
        self.frame()
        previous = self.ctrl.background_version
        self.apply()
        self.assertFalse(self.ready(previous))
        self.assertEqual(self.ctrl.background_preview_url, "")
        self.assertTrue(self.ready())
        image = QUrl(self.ctrl.background_preview_url).toLocalFile()
        self.apply(image)
        self.assertEqual(self.ctrl.background_mode, "image")
        self.assertEqual(self.ctrl.background_preview_url, "")
        self.assertFalse(self.ready())

    def test_corrupt_preview_regenerates_and_errors_keep_valid_preview(self):
        cache = Path(self.service.video_preview_path(str(self.video)))
        cache.parent.mkdir()
        cache.write_bytes(b"broken jpeg")
        with self.assertLogs("src.gui.controllers.background", level="WARNING"):
            self.apply()
        self.assertEqual(self.ctrl.background_preview_url, "")
        self.frame()
        self.assertTrue(self.ready())
        preview = self.ctrl.background_preview_url
        with self.assertLogs("src.gui.controllers.background", level="WARNING"):
            self.ctrl.videoError("decode failed")
        self.assertEqual(self.ctrl.background_mode, "image")
        self.assertEqual(self.ctrl.background_url, preview)

    def test_write_failure_still_unblocks_playback_and_is_not_retried_each_frame(self):
        self.frame()
        with patch.object(
            self.service, "save_video_preview", return_value=False
        ) as save:
            self.assertTrue(self.ready())
            self.frame("blue")
            self.assertTrue(self.ready())
        save.assert_called_once()
        self.assertEqual(self.ctrl.background_preview_url, "")


class TestVideoWallpaperQml(unittest.TestCase):
    def test_cold_start_decodes_without_preimporting_multimedia(self):
        code = textwrap.dedent(
            """
            import sys
            import tempfile
            from pathlib import Path
            from unittest.mock import patch
            from PySide6.QtCore import QUrl
            from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterSingletonInstance
            from PySide6.QtTest import QTest

            # 测试不能提前注册 QtMultimedia 的 Python 包装，否则会掩盖启动问题。
            assert "PySide6.QtMultimedia" not in sys.modules
            from src.gui.main_window import QmlBridge
            from src.gui.icons import UiIconProvider
            from src.utils.utils_sub_config import resolve_script_path
            from tests.gui.helpers import make_bridge

            with tempfile.TemporaryDirectory() as directory, patch(
                "src.utils.utils_wallpaper.get_wallpaper_json_path_under_root",
                return_value=str(Path(directory) / "wallpaper.json"),
            ):
                with (
                    patch("src.service.app_service.get_daily_map", return_value={}),
                    patch("src.service.app_service.get_weekly_map", return_value=[]),
                    patch("src.gui.controllers.task_card.get_daily_readback", return_value=[]),
                    patch("src.gui.controllers.background.BackgroundController.resolve_bg", return_value=None),
                ):
                    bridge = make_bridge()
                video = resolve_script_path("tests/fixtures/wallpaper.mp4")
                with patch.object(bridge.background, "resolve_bg", return_value=video):
                    bridge.background.apply_current(bridge.game_list.current_game)
                qmlRegisterSingletonInstance(QmlBridge, "OneDragonHelper", 1, 0, "Bridge", bridge)
                engine = QQmlApplicationEngine()
                engine.addImageProvider("uiicon", UiIconProvider())
                engine.addImageProvider("scripticon", bridge.game_list.icon_provider)
                engine.load(QUrl.fromLocalFile(resolve_script_path("src/gui/qml/main.qml")))
                assert len(engine.rootObjects()) == 1
                window = engine.rootObjects()[0]
                for _ in range(100):
                    if window.property("videoFrameReady"):
                        break
                    QTest.qWait(50)
                assert window.property("videoFrameReady"), "First frame never reached the bridge"
                assert bridge.backgroundPreviewUrl
                assert Path(QUrl(bridge.backgroundPreviewUrl).toLocalFile()).is_file()
                window.close()
                engine.deleteLater()
                QTest.qWait(20)
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for error in ("AssertionError", "TypeError", "Traceback", "Binding loop"):
            self.assertNotIn(error, result.stderr)

    def test_preview_waits_for_frame_and_resets_on_switch(self):
        code = textwrap.dedent(
            """
            import tempfile
            from pathlib import Path
            from unittest.mock import patch
            from PySide6.QtCore import QObject, QUrl
            from PySide6.QtGui import QImage
            from PySide6.QtMultimedia import QVideoFrame
            from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterSingletonInstance
            from PySide6.QtQuick import QQuickItem
            from PySide6.QtTest import QTest
            from src.gui.icons import UiIconProvider
            from src.gui.main_window import QmlBridge
            from src.utils.utils_sub_config import resolve_script_path
            # 离屏平台不执行 layer.effect（整窗内容不绘制），且 GraphicsInfo.api 在
            # 该平台报的值不可信，所以本用例只验证视频层的帧/可见性/缓存逻辑，不做
            # grabWindow 像素断言；真实后端下的整窗圆角由
            # tests/exe/test_gui_rendering_exe.py 覆盖。
            from tests.gui.helpers import make_bridge

            with tempfile.TemporaryDirectory() as directory, patch(
                "src.utils.utils_wallpaper.get_wallpaper_json_path_under_root",
                return_value=str(Path(directory) / "wallpaper.json"),
            ):
                with (
                    patch("src.service.app_service.get_daily_map", return_value={}),
                    patch("src.service.app_service.get_weekly_map", return_value=[]),
                    patch("src.gui.controllers.task_card.get_daily_readback", return_value=[]),
                    patch("src.gui.controllers.background.BackgroundController.resolve_bg", return_value=None),
                ):
                    bridge = make_bridge()
                video = Path(resolve_script_path("tests/fixtures/wallpaper.mp4"))
                preview = Path(bridge.app_service.video_preview_path(str(video)))
                preview.parent.mkdir()
                img = QImage(320, 180, QImage.Format_RGB32)
                img.fill("red")
                assert img.save(str(preview), "JPG")
                game = bridge.game_list.current_game
                def apply():
                    with patch.object(bridge.background, "resolve_bg", return_value=str(video)):
                        bridge.background.apply_current(game)
                apply()
                qmlRegisterSingletonInstance(QmlBridge, "OneDragonHelper", 1, 0, "Bridge", bridge)
                engine = QQmlApplicationEngine()
                engine.addImageProvider("uiicon", UiIconProvider())
                engine.addImageProvider("scripticon", bridge.game_list.icon_provider)
                engine.load(QUrl.fromLocalFile(resolve_script_path("src/gui/qml/main.qml")))
                assert len(engine.rootObjects()) == 1
                window = engine.rootObjects()[0]
                loader = window.findChild(QQuickItem, "videoBackgroundLoader")
                image = window.findChild(QQuickItem, "wallpaperImage")
                gradient = window.findChild(QQuickItem, "wallpaperGradient")
                def current_video():
                    item = loader.property("item")
                    assert item is not None, "Video component did not load"
                    item.findChild(QObject, "wallpaperStartTimer").setProperty("running", False)
                    output = item.findChild(QQuickItem, "wallpaperVideoOutput")
                    return item, output.property("videoSink")
                item, sink = current_video()
                QTest.qWait(50)
                assert not window.property("videoFrameReady")
                assert image.isVisible() and not loader.isVisible()
                assert not gradient.isVisible()
                assert Path(image.property("source").toLocalFile()) == preview
                sink.videoFrameChanged.emit(QVideoFrame())
                assert not item.property("frameReady")
                sink.setVideoFrame(QVideoFrame(img))
                assert item.property("frameReady")
                assert loader.isVisible() and image.isVisible()
                # 同一个视频重选也创建新播放器，不能保留上一轮 frameReady。
                apply()
                item, sink = current_video()
                assert not item.property("frameReady")
                assert image.isVisible() and not loader.isVisible()
                # 缓存缺失时渐变占位；首帧生成缓存不会重建正在播放的组件。
                preview.unlink()
                apply()
                item, sink = current_video()
                assert gradient.isVisible()
                sink.setVideoFrame(QVideoFrame(img))
                assert preview.is_file()
                assert loader.property("item") == item
                assert loader.isVisible() and not gradient.isVisible()
                bridge.videoError("test failure")
                assert bridge.backgroundMode == "image"
                assert image.isVisible() and not loader.isVisible()
                # 实际解码同一测试视频，验证播放器信号也能完成首帧缓存。
                preview.unlink()
                apply()
                for _ in range(100):
                    if window.property("videoFrameReady"):
                        break
                    QTest.qWait(50)
                assert window.property("videoFrameReady"), "Decoder produced no frame"
                assert preview.is_file()
                QTest.qWait(50)
                # 解码首帧后预览缓存仍指向同一文件（下面由真实渲染测试覆盖像素）。
                assert Path(image.property("source").toLocalFile()) == preview
                window.close()
                engine.deleteLater()
                QTest.qWait(20)
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for error in ("ReferenceError", "TypeError", "Binding loop", "Traceback"):
            self.assertNotIn(error, result.stderr)
