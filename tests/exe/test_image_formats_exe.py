"""打包产物的 Qt 图片插件防回归测试。

背景（2026-09-05 翻车）：瘦身时按「这格式不常用」从 plugins/imageformats 删了
qwebp.dll。GUI 照常启动、tests/exe 的 13 项 CLI 测试全过，但绝区零壁纸加载不出来——
``ZenlessZoneZeroConfig.background`` 指向 ``assets/ui/static_background.webp``，
文件存在、Qt 却解不了码，表现为空白背景且不报错、不写日志。

本测试把「项目声明用到的图片格式」与「打包产物里实际带的 Qt 图片插件」对齐，
并真实解码一遍，防止再次误删。
"""

import os
import unittest

from src.config import set_config
from src.config.set_config import get_background_rel_path
from tests.exe import project_root

PROJECT_ROOT = str(project_root())
IMAGEFORMATS = os.path.join(
    PROJECT_ROOT,
    "deploy",
    "dist",
    "OneDragon-Helper",
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

HAS_DIST = os.path.isdir(IMAGEFORMATS)
_SKIP_REASON = f"需要打包产物中的图片插件目录: {IMAGEFORMATS}"


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
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtGui import QGuiApplication, QImage

        app = QGuiApplication.instance() or QGuiApplication([])
        assert app is not None
        # 必须强制只搜打包产物这一处：QT_PLUGIN_PATH 是追加而非替换，
        # 混进开发环境的插件会让已删除的格式仍显示在 supportedImageFormats() 里。
        QCoreApplication.setLibraryPaths([os.path.dirname(IMAGEFORMATS)])

        from src.utils.utils_sub_config import get_script_root_dir_soft

        checked = 0
        for name, rel in _declared_backgrounds().items():
            if name == "__default__":
                path = os.path.join(PROJECT_ROOT, rel)
            else:
                root = get_script_root_dir_soft(name)
                if not root:
                    continue
                path = os.path.join(root, rel)
            if not os.path.isfile(path):
                continue  # 本机没装该脚本，跳过（插件存在性由上一个用例兜底）
            image = QImage(path)
            self.assertFalse(
                image.isNull(),
                f"打包插件集无法解码 {name} 的背景图: {path}（格式 "
                f"{os.path.splitext(rel)[1]}），检查对应插件是否被误删。",
            )
            checked += 1
        self.assertGreaterEqual(checked, 1, "没有任何背景图可供解码验证")


if __name__ == "__main__":
    unittest.main()
