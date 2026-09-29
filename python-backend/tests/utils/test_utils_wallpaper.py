"""壁纸来源、映射读写与预览缓存；文件操作使用临时目录。"""

import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.utils import utils_wallpaper as wallpaper
from src.utils.utils_wallpaper import (
    load_wallpapers,
    save_video_preview,
    save_wallpapers,
    video_preview_path,
)


class UtilsWallpaperTestBase(unittest.TestCase):
    """用临时 wallpaper.json 隔离真实文件。"""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.json_path = os.path.join(self.tmp_dir.name, "wallpaper.json")
        patcher = patch(
            "src.utils.utils_wallpaper.get_wallpaper_json_path_under_root",
            return_value=self.json_path,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _write_raw(self, text: str) -> None:
        with open(self.json_path, "w", encoding="utf-8") as f:
            f.write(text)


class TestLoadWallpapers(UtilsWallpaperTestBase):
    def test_missing_file_returns_empty(self):
        self.assertEqual(load_wallpapers(), {})

    def test_loads_mapping(self):
        self._write_raw('{"wu": "C:/w.png"}')
        self.assertEqual(load_wallpapers(), {"wu": "C:/w.png"})

    def test_corrupt_json_returns_empty_with_warning(self):
        """损坏 JSON 属可恢复外部输入：按未设置处理，不让 GUI 启动崩在坏文件上。"""
        self._write_raw('{"wu": "C:/w.pn')  # 截断的 JSON
        self.assertEqual(load_wallpapers(), {})

    def test_non_dict_asserts(self):
        self._write_raw('["wu"]')
        with self.assertRaises(AssertionError):
            load_wallpapers()


class TestSaveWallpapers(UtilsWallpaperTestBase):
    def test_save_roundtrip_replaces_content_without_leaving_temporary_file(self):
        for mapping in ({"wu": "C:/a.png"}, {"wu": "C:/b.png", "ef": "C:/c.mp4"}):
            with self.subTest(mapping=mapping):
                save_wallpapers(mapping)
                with open(self.json_path, encoding="utf-8") as stream:
                    self.assertEqual(json.load(stream), mapping)
                self.assertEqual(load_wallpapers(), mapping)
                self.assertFalse(os.path.exists(self.json_path + ".tmp"))

    def test_non_dict_asserts(self):
        with self.assertRaises(AssertionError):
            save_wallpapers(["wu"])  # type: ignore[arg-type]


class TestCorruptThenSaveRecovers(UtilsWallpaperTestBase):
    def test_save_over_corrupt_file_recovers(self):
        """损坏文件不影响保存：写入即覆盖重建（原子替换）。"""
        self._write_raw("{{{ not json")
        self.assertEqual(load_wallpapers(), {})
        save_wallpapers({"wu": "C:/w.png"})
        self.assertEqual(load_wallpapers(), {"wu": "C:/w.png"})


class TestModuleUsesRealPathConvention(unittest.TestCase):
    def test_default_path_is_config_dir(self):
        """路径 helper 指向项目根 config/wallpaper.json（贴真实部署）。"""
        from src.utils import get_wallpaper_json_path_under_root

        self.assertTrue(
            str(get_wallpaper_json_path_under_root())
            .replace("\\", "/")
            .endswith("config/wallpaper.json")
        )


class TestVideoPreview(UtilsWallpaperTestBase):
    def setUp(self):
        super().setUp()
        self.video = Path(self.tmp_dir.name) / "clip.mp4"
        self.video.write_bytes(b"video")
        self.cache = video_preview_path(str(self.video))

    def test_same_video_reuses_atomic_cache(self):
        self.assertTrue(save_video_preview(str(self.video), self.cache, b"jpeg"))
        self.assertEqual(video_preview_path(str(self.video)), self.cache)
        self.assertEqual(Path(self.cache).read_bytes(), b"jpeg")
        self.assertFalse(Path(self.cache + ".tmp").exists())

    def test_source_path_size_and_mtime_each_invalidate_cache(self):
        other = self.video.with_name("other.mp4")
        other.write_bytes(self.video.read_bytes())
        stat = self.video.stat()
        os.utime(other, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.assertNotEqual(video_preview_path(str(other)), self.cache)
        os.utime(self.video, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000))
        self.assertNotEqual(video_preview_path(str(self.video)), self.cache)
        self.video.write_bytes(b"longer video")
        os.utime(self.video, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.assertNotEqual(video_preview_path(str(self.video)), self.cache)

    def test_replaced_source_rejects_pending_frame(self):
        self.video.write_bytes(b"replacement")
        with self.assertLogs("src.utils.utils_wallpaper", level="WARNING"):
            self.assertFalse(save_video_preview(str(self.video), self.cache, b"old"))
        self.assertFalse(Path(self.cache).exists())

    def test_missing_source_skips_cache(self):
        self.video.unlink()
        with self.assertLogs("src.utils.utils_wallpaper", level="WARNING"):
            self.assertIsNone(video_preview_path(str(self.video)))

    def test_write_failure_preserves_previous_image(self):
        save_video_preview(str(self.video), self.cache, b"previous")
        with (
            patch("src.utils.utils_wallpaper.os.replace", side_effect=PermissionError),
            self.assertLogs("src.utils.utils_wallpaper", level="WARNING"),
        ):
            self.assertFalse(save_video_preview(str(self.video), self.cache, b"new"))
        self.assertEqual(Path(self.cache).read_bytes(), b"previous")


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


if __name__ == "__main__":
    unittest.main()
