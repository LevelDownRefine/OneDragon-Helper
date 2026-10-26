"""测试 src/gui/controllers/background.py：壁纸视图驱动的背景与缓存。

数据源为 AppService.wallpaper_view（与 Rust 前端同一视图）：用视图替身驱动，
验证模式分发（视频/图片/渐变）、缓存策略（小图跳过、大图压缩写回 token 通道）、
视频首帧预览与错误回退；缓存内容经回写参数（base64 JPEG）解码验证。
"""

import base64
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# 在导入 PySide6 之前设置 offscreen 平台插件（CI 无显示器环境）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QUrl
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

import gui.controllers.background as bgmod
from gui.controllers.background import BackgroundController
from src.service.app_service import AppService
from src.utils.utils_wallpaper import InvalidWallpaper


def _make_image(path: str, w: int, h: int, color: str = "red") -> str:
    """写一张 w×h 的 PNG 到 path，返回 path。"""
    img = QImage(w, h, QImage.Format_RGB888)
    img.fill(QColor(color))
    assert img.save(path, "PNG")
    return path


def _view(script_name="s", mode="image", source="", token=None, cache=None):
    return {
        "script_name": script_name,
        "display_name": "D",
        "mode": mode,
        "source": source,
        "custom_path": None,
        "token": token,
        "cache": cache,
    }


def _make_ctrl(view=None):
    """构造控制器，service 的壁纸三接口接 mock（视图按用例注入）。"""
    ctrl = BackgroundController(
        game_list=MagicMock(),
        app_service=MagicMock(),
        toast=MagicMock(),
    )
    if view is not None:
        ctrl._app_service.wallpaper_view.return_value = view
    return ctrl


class TestApplyModes(unittest.TestCase):
    """apply_current：按视图模式分发（视频/图片/渐变）。"""

    def setUp(self):
        self._app = QApplication.instance() or QApplication([])
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.game = {"script_name": "s", "color": "#123456", "char": "游"}

    def test_gradient_view_uses_gradient(self):
        ctrl = _make_ctrl(_view(mode="gradient"))
        ctrl.apply_current(self.game)
        self.assertEqual(ctrl.background_mode, "gradient")
        self.assertEqual(ctrl.background_url, "")
        self.assertEqual(ctrl.gradient_color, "#123456")

    def test_missing_script_shrinks_to_gradient(self):
        ctrl = _make_ctrl()
        ctrl._app_service.wallpaper_view.side_effect = InvalidWallpaper("脚本不存在")
        ctrl.apply_current(self.game)
        self.assertEqual(ctrl.background_mode, "gradient")

    def test_video_view_sets_source_and_existing_preview(self):
        preview = _make_image(os.path.join(self.tmp, "v.jpg"), 320, 180)
        ctrl = _make_ctrl(
            _view(mode="video", source="C:/clip.mp4", token="t", cache=preview)
        )
        ctrl.apply_current(self.game)
        self.assertEqual(ctrl.background_mode, "video")
        self.assertTrue(ctrl.background_url.endswith("clip.mp4"))
        self.assertEqual(
            ctrl.background_preview_url, QUrl.fromLocalFile(preview).toString()
        )

    def test_video_view_without_cache_keeps_placeholder(self):
        ctrl = _make_ctrl(_view(mode="video", source="C:/clip.mp4", token="t"))
        ctrl.apply_current(self.game)
        self.assertEqual(ctrl.background_mode, "video")
        self.assertEqual(ctrl.background_preview_url, "")

    def test_image_view_prefers_ready_cache(self):
        """视图 cache 已就绪（后端仅在文件存在时给出）→ 直接使用，不重编码。"""
        cache = _make_image(os.path.join(self.tmp, "c.jpg"), 100, 100)
        ctrl = _make_ctrl(
            _view(
                source=_make_image(os.path.join(self.tmp, "s.png"), 3000, 2000),
                token="t",
                cache=cache,
            )
        )
        ctrl.apply_current(self.game)
        self.assertEqual(ctrl.background_mode, "image")
        self.assertEqual(ctrl.background_url, QUrl.fromLocalFile(cache).toString())
        ctrl._app_service.save_wallpaper_cache.assert_not_called()

    def test_image_view_small_source_skips_cache(self):
        small = _make_image(os.path.join(self.tmp, "small.png"), 800, 600)
        ctrl = _make_ctrl(_view(source=small, token="t"))
        ctrl.apply_current(self.game)
        self.assertEqual(ctrl.background_mode, "image")
        self.assertEqual(ctrl.background_url, QUrl.fromLocalFile(small).toString())
        ctrl._app_service.save_wallpaper_cache.assert_not_called()

    def test_missing_source_falls_back_to_gradient(self):
        ctrl = _make_ctrl(
            _view(mode="gradient", source=os.path.join(self.tmp, "gone.png"))
        )
        ctrl.apply_current(self.game)
        self.assertEqual(ctrl.background_mode, "gradient")

    def test_version_increments_on_apply(self):
        """换壁纸 / 切脚本都走 apply_current：版本号自增，使 QML source 身份变化触发重载。"""
        ctrl = _make_ctrl(_view(mode="gradient"))
        v0 = ctrl.background_version
        ctrl.apply_current(self.game)
        v1 = ctrl.background_version
        ctrl.apply_current(self.game)
        v2 = ctrl.background_version
        self.assertEqual((v1, v2), (v0 + 1, v0 + 2))


class TestImageCache(unittest.TestCase):
    """_build_image_cache：大图压缩 / 小图跳过 / 损坏回退 / token 写回。"""

    def setUp(self):
        self._app = QApplication.instance() or QApplication([])
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.ctrl = _make_ctrl()
        # 写盘通道按 token 校验后成功：缓存内容经回写参数验证。
        self.ctrl._app_service.save_wallpaper_cache.return_value = True
        self.ctrl._app_service.wallpaper_view.return_value = _view(
            token="tok", cache="C:/cache/expected.jpg"
        )

    def _view(self, path, cache=None):
        return _view(source=path, token="tok", cache=cache)

    def test_downscales_large_image_and_writes_via_token(self):
        big = _make_image(os.path.join(self.tmp, "big.png"), 3000, 2000)
        got = self.ctrl._build_image_cache(self._view(big))
        self.assertEqual(got, "C:/cache/expected.jpg")
        args = self.ctrl._app_service.save_wallpaper_cache.call_args
        self.assertEqual(args.args[:2], ("s", "tok"))
        jpeg = base64.b64decode(args.args[2])
        self.assertTrue(jpeg.startswith(b"\xff\xd8"))
        out = QImage.fromData(jpeg)
        self.assertFalse(out.isNull())
        # 比例保持：3000x2000 -> 1920x1280
        self.assertEqual((out.width(), out.height()), (1920, 1280))

    def test_skips_small_image_without_write(self):
        small = _make_image(os.path.join(self.tmp, "small.png"), 640, 360)
        self.assertIsNone(self.ctrl._build_image_cache(self._view(small)))
        self.ctrl._app_service.save_wallpaper_cache.assert_not_called()

    def test_small_image_skips_pixel_decode(self):
        """小图仅凭头部尺寸判定即跳过缓存，不触发整图 QImage 解码（省内存）。"""
        small = _make_image(os.path.join(self.tmp, "small2.png"), 640, 360)
        with patch.object(bgmod, "QImage") as mock_img:
            result = self.ctrl._build_image_cache(self._view(small))
        self.assertIsNone(result)
        mock_img.assert_not_called()

    def test_corrupt_image_warns_and_returns_none(self):
        corrupt = os.path.join(self.tmp, "bad.png")
        with open(corrupt, "wb") as f:
            f.write(b"not an image")
        with self.assertLogs(bgmod.__name__, level="WARNING"):
            self.assertIsNone(self.ctrl._build_image_cache(self._view(corrupt)))

    def test_rejected_write_returns_none(self):
        """后端拒收（源已变化 token 失配）→ 不使用缓存落点，回退原图。"""
        big = _make_image(os.path.join(self.tmp, "big.png"), 3000, 2000)
        self.ctrl._app_service.save_wallpaper_cache.return_value = False
        with self.assertLogs(bgmod.__name__, level="WARNING"):
            self.assertIsNone(self.ctrl._build_image_cache(self._view(big)))


class TestWallpaperServiceIntegration(unittest.TestCase):
    """真实 service 视图只返回已存在缓存，首次生成须重新取数。"""

    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(
            patch(
                "src.utils.utils_wallpaper.get_wallpaper_json_path_under_root",
                return_value=str(self.root / "wallpaper.json"),
            )
        )
        self.enterContext(
            patch(
                "src.utils.utils_wallpaper.get_script",
                return_value={"display_name": "测试"},
            )
        )
        self.service = AppService()
        self.ctrl = BackgroundController(MagicMock(), self.service, MagicMock())
        self.game = {"script_name": "s", "color": "#123456", "char": "游"}
        self.source = _make_image(str(self.root / "large.png"), 3000, 2000)
        self.service.set_wallpaper("s", self.source)

    def test_first_large_image_creates_and_reuses_cache(self):
        self.assertIsNone(self.service.wallpaper_view("s")["cache"])
        self.ctrl.apply_current(self.game)
        cache = self.service.wallpaper_view("s")["cache"]
        self.assertEqual(self.ctrl.background_url, QUrl.fromLocalFile(cache).toString())
        image = QImage(cache)
        self.assertEqual((image.width(), image.height()), (1920, 1280))
        with patch.object(self.service, "save_wallpaper_cache") as save:
            self.ctrl.apply_current(self.game)
        save.assert_not_called()

    def test_source_replaced_after_cache_save_does_not_show_stale_cache(self):
        save = self.service.save_wallpaper_cache

        def save_then_replace(*args):
            result = save(*args)
            _make_image(self.source, 640, 360, "blue")
            return result

        with patch.object(
            self.service, "save_wallpaper_cache", side_effect=save_then_replace
        ):
            self.ctrl.apply_current(self.game)
        self.assertIsNone(self.service.wallpaper_view("s")["cache"])
        self.assertEqual(
            self.ctrl.background_url, QUrl.fromLocalFile(self.source).toString()
        )

    def test_rejected_first_cache_write_falls_back_to_source(self):
        with (
            patch.object(self.service, "save_wallpaper_cache", return_value=False),
            self.assertLogs(bgmod.__name__, level="WARNING"),
        ):
            self.ctrl.apply_current(self.game)
        self.assertEqual(
            self.ctrl.background_url, QUrl.fromLocalFile(self.source).toString()
        )

    def test_corrupt_cache_is_rebuilt(self):
        self.ctrl.apply_current(self.game)
        cache = self.service.wallpaper_view("s")["cache"]
        Path(cache).write_bytes(b"broken jpeg")
        self.ctrl.apply_current(self.game)
        self.assertFalse(QImage(cache).isNull())

    def test_missing_source_uses_service_gradient(self):
        Path(self.source).unlink()
        self.ctrl.apply_current(self.game)
        self.assertEqual(self.ctrl.background_mode, "gradient")
        self.assertEqual(self.ctrl.background_url, "")


class TestOpenWallpaper(unittest.TestCase):
    """open_wallpaper：选图后经 service.set_wallpaper 落壁纸表并刷新。"""

    def setUp(self):
        self._app = QApplication.instance() or QApplication([])

    def test_pick_writes_through_service_and_refreshes(self):
        img = "D:/pic.png"
        ctrl = _make_ctrl(_view(mode="gradient"))
        ctrl._game_list.current_game = {
            "script_name": "ok-ww",
            "display_name": "鸣潮",
            "color": "#111",
            "char": "鸣",
        }
        with (
            patch("gui.dialogs.QFileDialog.getOpenFileName", return_value=(img, "")),
            patch.object(ctrl, "apply_current") as apply,
        ):
            ctrl.open_wallpaper()
        ctrl._app_service.set_wallpaper.assert_called_once_with("ok-ww", img)
        apply.assert_called_once()

    def test_cancelled_pick_does_not_write(self):
        ctrl = _make_ctrl()
        ctrl._game_list.current_game = {"script_name": "ok-ww", "display_name": "鸣潮"}
        with patch("gui.dialogs.QFileDialog.getOpenFileName", return_value=("", "")):
            ctrl.open_wallpaper()
        ctrl._app_service.set_wallpaper.assert_not_called()

    def test_empty_game_list_toasts_and_skips(self):
        """config 删空（current_game None）：只 toast，不弹选框、不写壁纸表。"""
        ctrl = _make_ctrl()
        ctrl._game_list.current_game = None
        with patch("gui.dialogs.QFileDialog.getOpenFileName") as mock_dialog:
            ctrl.open_wallpaper()
        mock_dialog.assert_not_called()
        ctrl._app_service.set_wallpaper.assert_not_called()
        ctrl._toast.assert_called_once_with("尚无脚本")


class TestVideoFallback(unittest.TestCase):
    """videoError：解码失败保留预览图，无缓存回退渐变。"""

    def setUp(self):
        self._app = QApplication.instance() or QApplication([])

    def test_error_without_preview_falls_back_gradient(self):
        ctrl = _make_ctrl(_view(mode="gradient"))
        ctrl.apply_current({"script_name": "s", "color": "#1", "char": "x"})
        with self.assertLogs(bgmod.__name__, level="WARNING"):
            ctrl.videoError("boom")
        self.assertEqual(ctrl.background_mode, "gradient")
        self.assertEqual(ctrl.background_url, "")

    def test_error_with_preview_keeps_image(self):
        preview = os.path.join(
            self.enterContext(tempfile.TemporaryDirectory()), "p.jpg"
        )
        _make_image(preview, 320, 180)
        ctrl = _make_ctrl(
            _view(mode="video", source="C:/clip.mp4", token="t", cache=preview)
        )
        ctrl.apply_current({"script_name": "s", "color": "#1", "char": "x"})
        with self.assertLogs(bgmod.__name__, level="WARNING"):
            ctrl.videoError("boom")
        self.assertEqual(ctrl.background_mode, "image")
        self.assertEqual(ctrl.background_url, QUrl.fromLocalFile(preview).toString())


if __name__ == "__main__":
    unittest.main()
