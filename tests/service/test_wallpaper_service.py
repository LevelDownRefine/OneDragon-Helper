"""壁纸路径、映射和缓存写入均使用临时目录。"""

import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.service import wallpaper_service as wallpaper
from src.utils.utils_wallpaper import (
    load_wallpapers,
    save_wallpapers,
    video_preview_path,
)


class WallpaperTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch("src.utils.get_root_dir", return_value=str(self.root)))
        self.enterContext(
            patch(
                "src.utils.utils_sub_config.get_root_dir", return_value=str(self.root)
            )
        )
        self.lookup = self.enterContext(
            patch.object(wallpaper, "get_script", return_value={"display_name": "测试"})
        )
        self.relative = self.enterContext(
            patch.object(wallpaper, "get_background_rel_path", return_value="")
        )
        self.enterContext(
            patch.object(wallpaper, "get_script_root_dir", return_value=str(self.root))
        )
        (self.root / "config").mkdir()
        (self.root / "assets").mkdir()
        self.default = self.root / "assets/ds.jpg"
        self.default.write_bytes(b"default")

    def test_priority_and_missing_custom_do_not_fall_back_to_another_image(self):
        self.assertEqual(
            wallpaper.wallpaper_view("script")["source"], str(self.default)
        )
        native = self.root / "native.png"
        native.write_bytes(b"native")
        self.relative.return_value = "native.png"
        self.assertEqual(wallpaper.wallpaper_view("script")["source"], str(native))
        custom = self.root / "自定义.webp"
        custom.write_bytes(b"custom")
        wallpaper.set_wallpaper("script", str(custom))
        self.assertEqual(wallpaper.wallpaper_view("script")["source"], str(custom))
        custom.unlink()
        self.assertEqual(wallpaper.wallpaper_view("script")["mode"], "gradient")
        wallpaper.set_wallpaper("script", None)
        self.assertEqual(wallpaper.wallpaper_view("script")["source"], str(native))

    def test_save_reset_preserve_other_script_and_source_files(self):
        save_wallpapers({"other": "unchanged.png"})
        wallpaper.set_wallpaper("script", str(self.default))
        self.assertEqual(
            load_wallpapers(), {"other": "unchanged.png", "script": str(self.default)}
        )
        wallpaper.set_wallpaper("script", None)
        self.assertEqual(load_wallpapers(), {"other": "unchanged.png"})
        self.assertEqual(self.default.read_bytes(), b"default")
        before = (self.root / "config/wallpaper.json").read_bytes()
        for path in ("", "missing.png", str(self.root), "bad.exe"):
            with self.subTest(path=path), self.assertRaises(wallpaper.InvalidWallpaper):
                wallpaper.set_wallpaper("script", path)
        self.assertEqual((self.root / "config/wallpaper.json").read_bytes(), before)

    def test_cache_uses_current_source_identity_and_rejects_stale_data(self):
        state = wallpaper.wallpaper_view("script")
        jpeg = base64.b64encode(b"\xff\xd8test\xff\xd9").decode()
        self.assertTrue(wallpaper.save_wallpaper_cache("script", state["token"], jpeg))
        cache = Path(wallpaper.wallpaper_view("script")["cache"])
        self.assertEqual(cache.parent, self.root / "config/wallpaper_cache")
        self.assertEqual(cache.read_bytes(), b"\xff\xd8test\xff\xd9")
        self.default.write_bytes(b"changed source")
        self.assertIsNone(wallpaper.wallpaper_view("script")["cache"])
        self.assertFalse(wallpaper.save_wallpaper_cache("script", state["token"], jpeg))
        for invalid in ("not base64", base64.b64encode(b"not jpeg").decode()):
            with (
                self.subTest(invalid=invalid),
                self.assertRaises(wallpaper.InvalidWallpaper),
            ):
                wallpaper.save_wallpaper_cache("script", state["token"], invalid)
        with (
            patch.object(wallpaper, "MAX_CACHE_BYTES", 2),
            self.assertRaises(wallpaper.InvalidWallpaper),
        ):
            wallpaper.save_wallpaper_cache("script", state["token"], jpeg)
        self.assertEqual(len(list(cache.parent.iterdir())), 1)

    def test_video_keeps_existing_qt_preview_identity(self):
        video = self.root / "sample.mp4"
        video.write_bytes(b"video fixture")
        wallpaper.set_wallpaper("script", str(video))
        state = wallpaper.wallpaper_view("script")
        jpeg = base64.b64encode(b"\xff\xd8test\xff\xd9").decode()
        self.assertTrue(wallpaper.save_wallpaper_cache("script", state["token"], jpeg))
        self.assertEqual(
            wallpaper.wallpaper_view("script")["cache"], video_preview_path(str(video))
        )
        self.assertEqual(state["mode"], "video")
