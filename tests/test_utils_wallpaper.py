"""测试 src/utils/utils_wallpaper.py：壁纸表读写的损坏兜底与原子写。"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from src.utils.utils_wallpaper import load_wallpapers, save_wallpapers


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
    def test_saves_mapping(self):
        save_wallpapers({"wu": "C:/w.png"})
        with open(self.json_path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"wu": "C:/w.png"})

    def test_overwrite_replaces_content(self):
        save_wallpapers({"wu": "C:/a.png"})
        save_wallpapers({"wu": "C:/b.png", "ef": "C:/c.mp4"})
        self.assertEqual(load_wallpapers(), {"wu": "C:/b.png", "ef": "C:/c.mp4"})

    def test_atomic_write_leaves_no_tmp(self):
        save_wallpapers({"wu": "C:/w.png"})
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


if __name__ == "__main__":
    unittest.main()
