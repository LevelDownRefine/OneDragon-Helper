"""打包产物的 Qt 图片插件防回归测试。

本测试把「项目声明用到的图片格式」与「打包产物里实际带的 Qt 图片插件」对齐，
并真实解码一遍，防止再次误删。
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.config import set_config
from src.config.set_config import get_background_rel_path
from tests.exe import package_dir, project_root
from tools.release_package import cleanup_test_directory

PROJECT_ROOT = str(project_root())
IMAGEFORMATS = os.path.join(
    package_dir(),
    "_internal",
    "PySide6",
    "plugins",
    "imageformats",
)

# 与 src/gui/controllers/background.py 的 DEFAULT_BG 一致（脚本未声明背景时的兜底图）
DEFAULT_BG = "assets/ds.jpg"

# 扩展名 → 提供该格式解码能力的 Qt 图片插件。
# png / bmp 等由 Qt 内建支持，不需要插件，故不在表内。
_EXT_PLUGIN = {
    ".jpg": "qjpeg.dll",
    ".jpeg": "qjpeg.dll",
    ".svg": "qsvg.dll",
    ".ico": "qico.dll",
    ".gif": "qgif.dll",
    ".webp": "qwebp.dll",
}

HAS_DIST = sys.platform == "win32" and os.path.isdir(IMAGEFORMATS)
_SKIP_REASON = f"需要 Windows 和打包产物中的图片插件目录: {IMAGEFORMATS}"


def _declared_backgrounds() -> dict[str, str]:
    """收集项目声明用到的背景图：脚本标识 → 相对路径（含兜底图）。

    Returns:
        脚本标识到背景图相对路径的映射；兜底图以键 ``__default__`` 表示。
    """
    backgrounds = {"__default__": DEFAULT_BG}
    for name in set_config._CONFIGS:
        rel = get_background_rel_path(name)
        if rel:
            backgrounds[name] = rel
    return backgrounds


def _required_plugins() -> dict[str, str]:
    """按项目声明的背景图格式，算出打包产物必须携带的图片插件。

    Returns:
        插件文件名到「需要它的来源说明」的映射。
    """
    required: dict[str, str] = {}
    for name, rel in _declared_backgrounds().items():
        ext = os.path.splitext(rel)[1].lower()
        plugin = _EXT_PLUGIN.get(ext)
        assert plugin is not None, (
            f"{name} 的背景图格式 {ext} 无对应 Qt 插件（{rel}）。"
            f"若该格式由 Qt 内建支持，请把它从 _EXT_PLUGIN 的校验范围中排除。"
        )
        required.setdefault(plugin, f"{name}: {rel}")
    return required


@unittest.skipUnless(HAS_DIST, _SKIP_REASON)
class TestPackagedImageFormats(unittest.TestCase):
    """打包产物的图片插件必须覆盖项目实际用到的所有格式。"""

    def test_declared_formats_have_plugin(self):
        """项目声明用到的每种图片格式，打包产物里都得有对应插件。"""
        missing = {
            plugin: src
            for plugin, src in _required_plugins().items()
            if not os.path.isfile(os.path.join(IMAGEFORMATS, plugin))
        }
        self.assertEqual(
            missing,
            {},
            f"打包产物缺少图片插件 {sorted(missing)}，"
            f"对应来源: {missing}。误删插件会导致图片存在但解不了码（空白背景，无报错）。",
        )

    def test_packaged_plugins_decode_declared_backgrounds(self):
        """用打包产物自己的插件集，真实解码一遍项目声明的背景图。"""
        samples = {
            "qjpeg.dll": os.path.join(package_dir(), DEFAULT_BG),
            "qwebp.dll": os.path.join(
                PROJECT_ROOT, "tests", "fixtures", "background.webp"
            ),
        }
        paths = []
        for plugin, source in _required_plugins().items():
            self.assertIn(plugin, samples, f"{source} 缺少独立解码夹具")
            path = samples[plugin]
            self.assertTrue(os.path.isfile(path), f"解码夹具缺失: {path}")
            paths.append(path)
        self._decode(os.path.dirname(IMAGEFORMATS), paths)

    def _decode(self, plugins, samples, expected_code=0):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tests.support.qt_image_probe",
                str(plugins),
                *map(str, samples),
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        self.assertEqual(
            result.returncode, expected_code, result.stdout + result.stderr
        )
        if expected_code:
            self.assertIn("打包插件无法解码图片", result.stderr)

    def test_decode_releases_dll_and_missing_plugin_cannot_use_cached_decoder(self):
        with tempfile.TemporaryDirectory(prefix="odh_package_tests_") as directory:
            plugins = Path(directory) / "plugins"
            formats = plugins / "imageformats"
            formats.mkdir(parents=True)
            jpeg = formats / "qjpeg.dll"
            shutil.copy2(Path(IMAGEFORMATS) / jpeg.name, jpeg)
            image = package_dir() / DEFAULT_BG
            self._decode(plugins, [image])
            # 子进程退出后立刻删除真正加载过的 DLL，不能留到测试套件结束。
            jpeg.unlink()
            self._decode(plugins, [image], expected_code=1)

    def test_package_cleanup_waits_for_transient_dll_lock(self):
        directory = tempfile.TemporaryDirectory(prefix="odh_package_tests_")
        path = Path(directory.name) / "qjpeg.dll"
        shutil.copy2(Path(IMAGEFORMATS) / path.name, path)
        stream = path.open("rb")
        try:
            with (
                self.assertLogs("tools.release_package", level="WARNING"),
                patch(
                    "tools.release_package.time.sleep",
                    side_effect=lambda delay: stream.close(),
                ) as sleep,
            ):
                cleanup_test_directory(directory)
            sleep.assert_called_once()
            self.assertFalse(Path(directory.name).exists())
        finally:
            stream.close()
            directory.cleanup()


if __name__ == "__main__":
    unittest.main()
