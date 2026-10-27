"""RPC 背景视图、Qt 图像编码与测试端真实壁纸缓存。"""

import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QUrl
from PySide6.QtGui import QColor, QImage

import gui.controllers.cli_background as bgmod
from gui.cli_client import CliSession
from gui.controllers.cli_background import CliBackgroundController
from tests.gui.helpers import FakeCliClient, drain_events, get_app
from tests.gui.wallpaper_backend import WallpaperBackend


def _make_image(path, width, height, color="red"):
    image = QImage(width, height, QImage.Format_RGB888)
    image.fill(QColor(color))
    assert image.save(str(path), "PNG")
    return str(path)


def _view(script_name="s", mode="image", source="", token="tok", cache=None):
    return {
        "script_name": script_name,
        "display_name": "D",
        "mode": mode,
        "source": source,
        "custom_path": None,
        "token": None if mode == "gradient" else token,
        "cache": cache,
    }


def _make_ctrl(view=None, responses=None):
    client = FakeCliClient(
        responses={
            "wallpaper.current": view or _view(mode="gradient"),
            **(responses or {}),
        }
    )
    games = MagicMock()
    toast = MagicMock()
    controller = CliBackgroundController(games, CliSession(client, None), toast)
    controller.test_client = client
    return controller


def _apply(controller, game=None):
    controller.apply_current(
        game or {"script_name": "s", "color": "#123456", "char": "游"}
    )
    drain_events()


def _requests(controller, method):
    return [
        params for name, params in controller.test_client.requests if name == method
    ]


class TestApplyModes(unittest.TestCase):
    def setUp(self):
        self.app = get_app()
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_gradient_view_uses_gradient(self):
        controller = _make_ctrl(_view(mode="gradient"))
        _apply(controller)
        self.assertEqual(controller.background_mode, "gradient")
        self.assertEqual(controller.background_url, "")
        self.assertEqual(controller.gradient_color, "#123456")

    def test_missing_script_shrinks_to_gradient(self):
        def missing(_params):
            raise ValueError("脚本不存在")

        controller = _make_ctrl(responses={"wallpaper.current": missing})
        _apply(controller)
        self.assertEqual(controller.background_mode, "gradient")
        self.assertEqual(controller.background_url, "")
        controller._toast.assert_called_once_with("脚本不存在")

    def test_video_view_sets_source_and_existing_preview(self):
        preview = _make_image(self.root / "preview.jpg", 320, 180)
        controller = _make_ctrl(
            _view(mode="video", source="C:/clip.mp4", cache=preview)
        )
        _apply(controller)
        self.assertEqual(controller.background_mode, "video")
        self.assertTrue(controller.background_url.endswith("clip.mp4"))
        self.assertEqual(
            controller.background_preview_url, QUrl.fromLocalFile(preview).toString()
        )

    def test_video_view_without_cache_keeps_placeholder(self):
        controller = _make_ctrl(_view(mode="video", source="C:/clip.mp4"))
        _apply(controller)
        self.assertEqual(controller.background_mode, "video")
        self.assertEqual(controller.background_preview_url, "")

    def test_image_view_prefers_ready_cache(self):
        preview = _make_image(self.root / "cache.jpg", 100, 100)
        controller = _make_ctrl(
            _view(
                source=_make_image(self.root / "source.png", 3000, 2000), cache=preview
            )
        )
        _apply(controller)
        self.assertEqual(controller.background_mode, "image")
        self.assertEqual(
            controller.background_url, QUrl.fromLocalFile(preview).toString()
        )
        self.assertEqual(_requests(controller, "wallpaper.cache"), [])

    def test_image_view_small_source_skips_cache(self):
        source = _make_image(self.root / "small.png", 800, 600)
        controller = _make_ctrl(_view(source=source))
        _apply(controller)
        self.assertEqual(controller.background_mode, "image")
        self.assertEqual(
            controller.background_url, QUrl.fromLocalFile(source).toString()
        )
        self.assertEqual(_requests(controller, "wallpaper.cache"), [])

    def test_missing_source_falls_back_to_gradient(self):
        controller = _make_ctrl(
            _view(mode="gradient", source=str(self.root / "gone.png"))
        )
        _apply(controller)
        self.assertEqual(controller.background_mode, "gradient")

    def test_version_increments_on_apply(self):
        controller = _make_ctrl(_view(mode="gradient"))
        version = controller.background_version
        _apply(controller)
        self.assertEqual(controller.background_version, version + 1)
        _apply(controller)
        self.assertEqual(controller.background_version, version + 2)

    def test_empty_selection_keeps_gradient_without_rpc(self):
        controller = _make_ctrl()
        _apply(controller, {"script_name": "", "color": "#123456", "char": ""})
        self.assertEqual(controller.background_mode, "gradient")
        self.assertEqual(controller.test_client.requests, [])


class TestImageCache(unittest.TestCase):
    def setUp(self):
        self.app = get_app()
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.source = ""
        self.saved = False
        self.accept = True

        def current(_params):
            return _view(
                source=self.source,
                cache="C:/cache/expected.jpg" if self.saved else None,
            )

        def cache(_params):
            self.saved = self.accept
            return self.accept

        self.ctrl = _make_ctrl(
            responses={"wallpaper.current": current, "wallpaper.cache": cache}
        )

    def test_downscales_large_image_and_writes_via_token(self):
        self.source = _make_image(self.root / "large.png", 3000, 2000)
        _apply(self.ctrl)
        self.assertEqual(
            self.ctrl.background_url,
            QUrl.fromLocalFile("C:/cache/expected.jpg").toString(),
        )
        (payload,) = _requests(self.ctrl, "wallpaper.cache")
        self.assertEqual(payload["script_name"], "s")
        self.assertEqual(payload["token"], "tok")
        jpeg = base64.b64decode(payload["jpeg_base64"])
        self.assertTrue(jpeg.startswith(b"\xff\xd8"))
        image = QImage.fromData(jpeg)
        self.assertFalse(image.isNull())
        self.assertEqual((image.width(), image.height()), (1920, 1280))

    def test_skips_small_image_without_write(self):
        self.source = _make_image(self.root / "small.png", 640, 360)
        _apply(self.ctrl)
        self.assertEqual(_requests(self.ctrl, "wallpaper.cache"), [])
        self.assertEqual(
            self.ctrl.background_url, QUrl.fromLocalFile(self.source).toString()
        )

    def test_small_image_skips_pixel_decode(self):
        self.source = _make_image(self.root / "small.png", 640, 360)
        with patch.object(bgmod, "QImage") as image:
            _apply(self.ctrl)
        image.assert_not_called()
        self.assertEqual(_requests(self.ctrl, "wallpaper.cache"), [])

    def test_corrupt_image_warns_and_returns_none(self):
        self.source = str(self.root / "corrupt.png")
        Path(self.source).write_bytes(b"not an image")
        with self.assertLogs(bgmod.__name__, level="WARNING"):
            _apply(self.ctrl)
        self.assertEqual(_requests(self.ctrl, "wallpaper.cache"), [])
        self.assertEqual(
            self.ctrl.background_url, QUrl.fromLocalFile(self.source).toString()
        )

    def test_rejected_write_returns_none(self):
        self.source = _make_image(self.root / "large.png", 3000, 2000)
        self.accept = False
        with self.assertLogs(bgmod.__name__, level="WARNING"):
            _apply(self.ctrl)
        self.assertEqual(
            self.ctrl.background_url, QUrl.fromLocalFile(self.source).toString()
        )
        self.assertEqual(len(_requests(self.ctrl, "wallpaper.cache")), 1)


class TestWallpaperServiceIntegration(unittest.TestCase):
    """真实后端仅作为 RPC 测试服务器，控制器不持有或调用服务。"""

    def setUp(self):
        self.app = get_app()
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.backend = self.enterContext(WallpaperBackend(self.root))
        self.ctrl = _make_ctrl(responses=self.backend.responses())
        self.game = {"script_name": "s", "color": "#123456", "char": "游"}
        self.source = _make_image(self.root / "large.png", 3000, 2000)
        self.backend.set("s", self.source)

    def test_first_large_image_creates_and_reuses_cache(self):
        self.assertIsNone(self.backend.view("s")["cache"])
        _apply(self.ctrl)
        cache = self.backend.view("s")["cache"]
        self.assertEqual(self.ctrl.background_url, QUrl.fromLocalFile(cache).toString())
        image = QImage(cache)
        self.assertEqual((image.width(), image.height()), (1920, 1280))
        self.ctrl.test_client.requests.clear()
        _apply(self.ctrl)
        self.assertEqual(_requests(self.ctrl, "wallpaper.cache"), [])

    def test_source_replaced_after_cache_save_does_not_show_stale_cache(self):
        save = self.backend.service.save_wallpaper_cache

        def save_then_replace(*args, **kwargs):
            result = save(*args, **kwargs)
            _make_image(self.source, 640, 360, "blue")
            return result

        with patch.object(
            self.backend.service, "save_wallpaper_cache", side_effect=save_then_replace
        ):
            _apply(self.ctrl)
        self.assertIsNone(self.backend.view("s")["cache"])
        self.assertEqual(
            self.ctrl.background_url, QUrl.fromLocalFile(self.source).toString()
        )

    def test_rejected_first_cache_write_falls_back_to_source(self):
        with (
            patch.object(
                self.backend.service, "save_wallpaper_cache", return_value=False
            ),
            self.assertLogs(bgmod.__name__, level="WARNING"),
        ):
            _apply(self.ctrl)
        self.assertEqual(
            self.ctrl.background_url, QUrl.fromLocalFile(self.source).toString()
        )

    def test_corrupt_cache_is_rebuilt(self):
        _apply(self.ctrl)
        cache = self.backend.view("s")["cache"]
        Path(cache).write_bytes(b"broken jpeg")
        with self.assertLogs(bgmod.__name__, level="WARNING"):
            _apply(self.ctrl)
        self.assertFalse(QImage(cache).isNull())

    def test_missing_source_uses_service_gradient(self):
        Path(self.source).unlink()
        _apply(self.ctrl)
        self.assertEqual(self.ctrl.background_mode, "gradient")
        self.assertEqual(self.ctrl.background_url, "")


class TestOpenWallpaper(unittest.TestCase):
    def setUp(self):
        self.app = get_app()

    def test_pick_writes_through_service_and_refreshes(self):
        controller = _make_ctrl(
            _view(script_name="ok-ww", mode="gradient"), {"wallpaper.set": None}
        )
        controller._game_list.current_game = {
            "script_name": "ok-ww",
            "display_name": "鸣潮",
            "color": "#111",
            "char": "鸣",
        }
        with patch("gui.dialogs.pick_file", return_value="D:/pic.png"):
            controller.open_wallpaper()
            drain_events()
        self.assertEqual(
            _requests(controller, "wallpaper.set"),
            [{"script_name": "ok-ww", "file_path": "D:/pic.png"}],
        )
        self.assertEqual(
            _requests(controller, "wallpaper.current"), [{"script_name": "ok-ww"}]
        )
        controller._toast.assert_called_once_with("已更换 鸣潮 壁纸")

    def test_cancelled_pick_does_not_write(self):
        controller = _make_ctrl()
        controller._game_list.current_game = {
            "script_name": "ok-ww",
            "display_name": "鸣潮",
        }
        with patch("gui.dialogs.pick_file", return_value=""):
            controller.open_wallpaper()
            drain_events()
        self.assertEqual(_requests(controller, "wallpaper.set"), [])

    def test_empty_game_list_toasts_and_skips(self):
        controller = _make_ctrl()
        controller._game_list.current_game = None
        with patch("gui.dialogs.pick_file") as picker:
            controller.open_wallpaper()
        picker.assert_not_called()
        self.assertEqual(_requests(controller, "wallpaper.set"), [])
        controller._toast.assert_called_once_with("尚无脚本")


class TestVideoFallback(unittest.TestCase):
    def setUp(self):
        self.app = get_app()

    def test_error_without_preview_falls_back_gradient(self):
        controller = _make_ctrl(_view(mode="gradient"))
        _apply(controller)
        with self.assertLogs("gui.controllers.background", level="WARNING"):
            controller.videoError("boom")
        self.assertEqual(controller.background_mode, "gradient")
        self.assertEqual(controller.background_url, "")

    def test_error_with_preview_keeps_image(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        preview = _make_image(root / "preview.jpg", 320, 180)
        controller = _make_ctrl(
            _view(mode="video", source="C:/clip.mp4", cache=preview)
        )
        _apply(controller)
        with self.assertLogs("gui.controllers.background", level="WARNING"):
            controller.videoError("boom")
        self.assertEqual(controller.background_mode, "image")
        self.assertEqual(
            controller.background_url, QUrl.fromLocalFile(preview).toString()
        )
