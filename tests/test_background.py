"""测试 src/gui/controllers/background.py：自定义壁纸缓存与背景解析。

覆盖 _build_wallpaper_cache（大图压缩 / 小图跳过 / 损坏回退，调用方已保证是图像）、
_wallpaper_for（定位源 + 图/视频分类：视频直接返回源、图像委托缓存）与 resolve_bg 的优先级，
及 open_wallpaper 选视频不预压缓存。
"""

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

# 在导入 PySide6 之前设置 offscreen 平台插件（CI 无显示器环境）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

import src.gui.controllers.background as bgmod
from src.gui.controllers.background import (
    WALLPAPER_CACHE_DIR,
    WALLPAPER_MAX_SIDE,
    BackgroundController,
)


def _make_image(path: str, w: int, h: int, color: str = "red") -> str:
    """写一张 w×h 的 PNG 到 path，返回 path。"""
    img = QImage(w, h, QImage.Format_RGB888)
    img.fill(QColor(color))
    assert img.save(path, "PNG")
    return path


class TestWallpaperCache(unittest.TestCase):
    """_build_wallpaper_cache：压缩 / 跳过 / 回退。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._cache_dir = os.path.join(self._tmp, "wallpaper_cache")
        self._img_dir = os.path.join(self._tmp, "imgs")
        os.makedirs(self._img_dir)
        # 把缓存目录重定向到临时目录，避免污染项目 config/wallpaper_cache
        self._resolved = {}
        self._patcher = patch.object(
            bgmod,
            "resolve_script_path",
            side_effect=self._fake_resolve,
        )
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        self._app = QApplication.instance() or QApplication([])
        self.ctrl = BackgroundController(
            game_list=MagicMock(), task_card=MagicMock(), toast=MagicMock()
        )

    def _fake_resolve(self, path):
        if path == WALLPAPER_CACHE_DIR:
            return self._cache_dir
        return path

    def test_downscales_large_image(self):
        """大图应压缩到最长边 <= 上限，且缓存为有效 JPG。"""
        big = _make_image(os.path.join(self._img_dir, "big.png"), 3000, 2000)
        cache = self.ctrl._build_wallpaper_cache(big, "s1")
        self.assertIsNotNone(cache)
        out = QImage(cache)
        self.assertFalse(out.isNull())
        self.assertLessEqual(max(out.width(), out.height()), WALLPAPER_MAX_SIDE)
        # 比例保持：3000x2000 -> 1920x1280
        self.assertEqual((out.width(), out.height()), (1920, 1280))

    def test_skips_small_image(self):
        """已小于等于上限的图不缓存，返回 None。"""
        small = _make_image(os.path.join(self._img_dir, "small.png"), 800, 600)
        self.assertIsNone(self.ctrl._build_wallpaper_cache(small, "s2"))
        self.assertFalse(os.path.isfile(os.path.join(self._cache_dir, "s2.jpg")))

    def test_corrupt_image_warns_and_returns_none(self):
        """损坏图解码失败：记日志并回退 None（不崩溃）。"""
        corrupt = os.path.join(self._img_dir, "bad.png")
        with open(corrupt, "wb") as f:
            f.write(b"not an image")
        with self.assertLogs(bgmod.__name__, level="WARNING") as cm:
            result = self.ctrl._build_wallpaper_cache(corrupt, "s4")
        self.assertIsNone(result)
        self.assertTrue(any("解码失败" in r.getMessage() for r in cm.records))

    def test_force_rebuild_overrides_stale_cache(self):
        """换壁纸（force=True）：即便新源 mtime 比旧缓存更旧，也重建为最新源内容。

        这正是「改了壁纸却没变化」的根因——旧缓存被 mtime 误判为较新时，非 force
        路径会直接返回旧缓存（旧壁纸）。force=True 先删旧缓存再从新源重建。
        """
        a = _make_image(os.path.join(self._img_dir, "a.png"), 3000, 2000, "red")
        cache = self.ctrl._build_wallpaper_cache(a, "s1")
        self.assertIsNotNone(cache)
        # 新源 B：不同颜色；mtime 设为比旧缓存更旧，使非 force 路径误判旧缓存较新
        b = _make_image(os.path.join(self._img_dir, "b.png"), 3000, 2000, "blue")
        past = os.path.getmtime(cache) - 1000
        os.utime(b, (past, past))
        rebuilt = self.ctrl._build_wallpaper_cache(b, "s1", force=True)
        self.assertEqual(rebuilt, cache)
        out = QImage(cache)
        self.assertFalse(out.isNull())
        # 缓存内容应反映新源（整体蓝），而非旧的红色
        self.assertLess(out.pixelColor(out.width() // 2, out.height() // 2).red(), 50)


class TestWallpaperFor(unittest.TestCase):
    """_wallpaper_for：优先缓存 / 过期重建 / 源图缺失回退。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._cache_dir = os.path.join(self._tmp, "wallpaper_cache")
        self._img_dir = os.path.join(self._tmp, "imgs")
        os.makedirs(self._img_dir)
        self._patcher = patch.object(
            bgmod, "resolve_script_path", side_effect=self._fake_resolve
        )
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        self._app = QApplication.instance() or QApplication([])
        self.ctrl = BackgroundController(
            game_list=MagicMock(), task_card=MagicMock(), toast=MagicMock()
        )

    def _fake_resolve(self, path):
        if path == WALLPAPER_CACHE_DIR:
            return self._cache_dir
        return path

    def test_prefers_fresh_cache(self):
        """缓存存在且较新：直接返回缓存路径，不重新生成。"""
        big = _make_image(os.path.join(self._img_dir, "big.png"), 3000, 2000)
        cache = self.ctrl._build_wallpaper_cache(big, "s1")
        self.assertIsNotNone(cache)
        with patch.object(self.ctrl, "read_wallpapers", return_value={"s1": big}):
            returned = self.ctrl._wallpaper_for({"script_name": "s1"})
        self.assertEqual(returned, os.path.join(self._cache_dir, "s1.jpg"))

    def test_rebuilds_when_cache_stale(self):
        """源图比缓存新：重建缓存并返回缓存路径。"""
        big = _make_image(os.path.join(self._img_dir, "big.png"), 3000, 2000)
        cache = self.ctrl._build_wallpaper_cache(big, "s1")
        self.assertIsNotNone(cache)
        # 把源图 mtime 改到未来，使缓存变旧
        future = os.path.getmtime(big) + 10
        os.utime(big, (future, future))
        with patch.object(self.ctrl, "read_wallpapers", return_value={"s1": big}):
            returned = self.ctrl._wallpaper_for({"script_name": "s1"})
        self.assertEqual(returned, os.path.join(self._cache_dir, "s1.jpg"))

    def test_missing_src_returns_src(self):
        """源图缺失：返回源路径（交 resolve_bg 的 isfile 守卫走渐变兜底）。"""
        missing = os.path.join(self._img_dir, "gone.png")
        with patch.object(self.ctrl, "read_wallpapers", return_value={"s9": missing}):
            returned = self.ctrl._wallpaper_for({"script_name": "s9"})
        self.assertEqual(returned, missing)

    def test_video_returns_src_early(self):
        """视频壁纸：不走缓存逻辑，直接返回源路径且不生成缓存文件。"""
        video = os.path.join(self._img_dir, "clip.mp4")
        with open(video, "w", encoding="utf-8") as f:
            f.write("dummy")
        with patch.object(self.ctrl, "read_wallpapers", return_value={"s1": video}):
            returned = self.ctrl._wallpaper_for({"script_name": "s1"})
        self.assertEqual(returned, video)
        self.assertFalse(
            os.path.isfile(os.path.join(self._cache_dir, "s1.jpg")),
            "视频壁纸不应生成缓存文件",
        )


class TestOpenWallpaper(unittest.TestCase):
    """open_wallpaper：选图/视频的入口分类（视频不预压缓存）。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._img_dir = os.path.join(self._tmp, "imgs")
        os.makedirs(self._img_dir)
        self._app = QApplication.instance() or QApplication([])
        self.ctrl = BackgroundController(
            game_list=MagicMock(), task_card=MagicMock(), toast=MagicMock()
        )

    def _video(self) -> str:
        p = os.path.join(self._img_dir, "clip.mp4")
        with open(p, "w", encoding="utf-8") as f:
            f.write("dummy")
        return p

    def test_skips_cache_for_video(self):
        """选视频：不预压缓存，壁纸表写入视频路径。"""
        video = self._video()
        with (
            patch(
                "src.gui.controllers.background.QFileDialog.getOpenFileName",
                return_value=(video, ""),
            ),
            patch.object(self.ctrl, "read_wallpapers", return_value={}),
            patch.object(self.ctrl, "write_wallpapers") as mock_write,
            patch.object(self.ctrl, "_build_wallpaper_cache") as mock_build,
            patch.object(self.ctrl, "apply_current"),
        ):
            self.ctrl.open_wallpaper()
        mock_build.assert_not_called()
        self.assertEqual(list(mock_write.call_args[0][0].values()), [video])

    def test_builds_cache_with_force_for_image(self):
        """选图片：以 force=True 预压缓存，确保换图后旧缓存被覆盖。"""
        img = _make_image(os.path.join(self._img_dir, "pic.png"), 3000, 2000)
        with (
            patch(
                "src.gui.controllers.background.QFileDialog.getOpenFileName",
                return_value=(img, ""),
            ),
            patch.object(self.ctrl, "read_wallpapers", return_value={}),
            patch.object(self.ctrl, "write_wallpapers"),
            patch.object(self.ctrl, "apply_current"),
            patch.object(self.ctrl, "_build_wallpaper_cache") as mock_build,
        ):
            self.ctrl.open_wallpaper()
        mock_build.assert_called_once_with(
            img, self.ctrl._game_list.current_game["script_name"], force=True
        )


class TestScriptBackground(unittest.TestCase):
    """_script_background：读 set_config.background（相对脚本根），isfile 守卫。"""

    def setUp(self):
        self._app = QApplication.instance() or QApplication([])
        self.ctrl = BackgroundController(
            game_list=MagicMock(), task_card=MagicMock(), toast=MagicMock()
        )

    @patch.object(bgmod, "get_background_rel_path", return_value="assets/x.webp")
    @patch.object(bgmod, "_get_script_root_dir_soft", return_value="/script/root")
    def test_declared_and_present(self, _mock_root, _mock_rel):
        # 声明且文件存在：返回脚本根拼接的绝对路径
        with patch.object(bgmod.os.path, "isfile", return_value=True):
            self.assertEqual(
                self.ctrl._script_background("ok-ww"),
                os.path.join("/script/root", "assets/x.webp"),
            )

    @patch.object(bgmod, "get_background_rel_path", return_value="assets/x.webp")
    @patch.object(bgmod, "_get_script_root_dir_soft", return_value="/script/root")
    def test_declared_but_missing(self, _mock_root, _mock_rel):
        # 声明但文件缺失：返回空字符串（交 DEFAULT_BG 兜底）
        with patch.object(bgmod.os.path, "isfile", return_value=False):
            self.assertEqual(self.ctrl._script_background("ok-ww"), "")

    @patch.object(bgmod, "get_background_rel_path", return_value="")
    def test_not_declared(self, _mock_rel):
        # 子类未声明 background（如原神）：返回空字符串
        self.assertEqual(self.ctrl._script_background("BetterGI"), "")

    def test_unadapted_script(self):
        # 未适配脚本：返回空字符串（get_background_rel_path 返回 ""）
        self.assertEqual(self.ctrl._script_background("不存在"), "")


class TestResolveBg(unittest.TestCase):
    """resolve_bg：自定义壁纸缓存优先于原图，缺失文件安全回退。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._cache_dir = os.path.join(self._tmp, "wallpaper_cache")
        self._img_dir = os.path.join(self._tmp, "imgs")
        os.makedirs(self._img_dir)
        self._patcher = patch.object(
            bgmod, "resolve_script_path", side_effect=self._fake_resolve
        )
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        self._app = QApplication.instance() or QApplication([])
        self.ctrl = BackgroundController(
            game_list=MagicMock(), task_card=MagicMock(), toast=MagicMock()
        )

    def _fake_resolve(self, path):
        if path == WALLPAPER_CACHE_DIR:
            return self._cache_dir
        return path

    def test_custom_wallpaper_returns_cache(self):
        """有自定义大图壁纸：resolve_bg 优先返回缓存（而非原始大图路径）。"""
        big = _make_image(os.path.join(self._img_dir, "big.png"), 3000, 2000)
        with patch.object(self.ctrl, "read_wallpapers", return_value={"game_x": big}):
            bg = self.ctrl.resolve_bg({"script_name": "game_x"})
        self.assertEqual(bg, os.path.join(self._cache_dir, "game_x.jpg"))

    def test_missing_custom_falls_back_to_none(self):
        """自定义壁纸源图已删除：resolve_bg 返回 None（渐变兜底），不抛异常。"""
        missing = os.path.join(self._img_dir, "gone.png")
        with patch.object(
            self.ctrl, "read_wallpapers", return_value={"game_x": missing}
        ):
            self.assertIsNone(self.ctrl.resolve_bg({"script_name": "game_x"}))


class TestApplyCurrent(unittest.TestCase):
    """apply_current：每次刷新自增 background_version，供 QML 强制重载图片。"""

    def setUp(self):
        self._app = QApplication.instance() or QApplication([])
        self.ctrl = BackgroundController(
            game_list=MagicMock(), task_card=MagicMock(), toast=MagicMock()
        )

    def test_version_increments_on_apply(self):
        """换壁纸 / 切脚本都走 apply_current：版本号自增，使 QML source 身份变化触发重载。"""
        game = {"script_name": "g", "color": "#111", "char": "X"}
        v0 = self.ctrl.background_version
        self.ctrl.apply_current(game)
        v1 = self.ctrl.background_version
        self.ctrl.apply_current(game)
        v2 = self.ctrl.background_version
        self.assertEqual((v1, v2), (v0 + 1, v0 + 2))


if __name__ == "__main__":
    unittest.main()
