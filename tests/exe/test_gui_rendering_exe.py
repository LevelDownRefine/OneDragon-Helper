"""真实发布界面：验证自动选卡和 Windows WARP 软件渲染。"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from src.update.package import load_manifest, manifest_frontend
from tests.exe import package_dir

PACKAGE = package_dir()
EXE_NAME = "OneDragon-Helper.exe"


@unittest.skipUnless(
    sys.platform == "win32" and (PACKAGE / EXE_NAME).is_file(),
    "需要 Windows 和打包产物",
)
class TestPackagedRendering(unittest.TestCase):
    def test_native_window_renders_without_software_opengl(self):
        """各前端实际绘制窗口，不依赖 Qt software OpenGL DLL。"""
        self.assertFalse(list(PACKAGE.rglob("opengl32sw.dll")))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "app"
            shutil.copytree(PACKAGE, root)
            if manifest_frontend(load_manifest(root)) == "rust":
                self._check_rust_frame(root, Path(directory))
                return
            # 测试副本不配置任何脚本，避免倒计时启动游戏。
            (root / "config/config.yml").write_text(
                "script_list: []\n", encoding="utf-8"
            )
            qml = root / "src/gui/qml/main.qml"
            scene = qml.read_text(encoding="utf-8")
            self.assertIn("Window {", scene)
            # 整窗圆角靠 shell 的 MultiEffect 遮罩（依赖 QtQuick.Effects 与
            # Qt6QuickEffects.dll）：打包产物里这两者被裁掉时，圆角会静默失效。
            self.assertIn("maskSource: cornerMask", scene)
            # 只给测试副本加首帧退出钩子，仍由打包的主程序加载完整主场景。
            scene = scene.replace(
                "Window {",
                """Window {
    Item {
        id: renderProbe
        readonly property bool usesD3D11: GraphicsInfo.api === GraphicsInfo.Direct3D11
    }
    onFrameSwapped: {
        if (renderProbe.usesD3D11) {
            console.info("ODH_D3D11_FRAME_READY")
            Qt.quit()
        } else {
            console.error("ODH_UNEXPECTED_GRAPHICS_API", renderProbe.GraphicsInfo.api)
            Qt.exit(2)
        }
    }
""",
                1,
            )
            qml.write_text(scene, encoding="utf-8")
            log = root / "logs/onedragon_helper.log"
            for software in ("0", "1"):
                with self.subTest(prefer_software=software):
                    log.unlink(missing_ok=True)
                    env = dict(os.environ)
                    env.update(
                        QT_QPA_PLATFORM="windows",
                        QSG_RHI_PREFER_SOFTWARE_RENDERER=software,
                        LOCALAPPDATA=str(Path(directory) / "localappdata"),
                        # 只测渲染，用当前权限运行，避免 GUI manifest 触发 UAC。
                        __COMPAT_LAYER="RunAsInvoker",
                    )
                    env.pop("QSG_RHI_BACKEND", None)
                    env.pop("QT_QUICK_BACKEND", None)
                    env.pop("QT_PLUGIN_PATH", None)
                    result = subprocess.run(
                        [str(root / EXE_NAME)],
                        cwd=root,
                        env=env,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=45,
                    )
                    output = log.read_text(encoding="utf-8") if log.exists() else ""
                    detail = output + result.stdout + result.stderr
                    self.assertEqual(result.returncode, 0, detail)
                    self.assertIn("ODH_D3D11_FRAME_READY", output, detail)
                    self.assertNotIn("[CRITICAL]", output, detail)

    def _check_rust_frame(self, root: Path, directory: Path):
        from PySide6.QtGui import QImage

        (root / "config/config.yml").write_text(
            "script_list:\n- display_name: 绘制测试\n  script_path: render.py\n",
            encoding="utf-8",
        )
        (root / "render.py").write_text("# Fixture only; never executed.\n")
        for software in ("0", "1"):
            for window, arguments, minimum in (
                ("main", ["--after-update"], (640, 360)),
                # 仅运行独立确认窗；截图后取消，不调用 Python 关机动作。
                ("shutdown", ["--shutdown-confirm", "86400"], (400, 220)),
            ):
                with self.subTest(software=software, window=window):
                    screenshot = directory / f"rust-{window}-{software}.png"
                    result = subprocess.run(
                        [
                            str(root / EXE_NAME),
                            *arguments,
                            "--capture",
                            str(screenshot),
                        ],
                        cwd=root,
                        env={
                            **os.environ,
                            "__COMPAT_LAYER": "RunAsInvoker",
                            "ODH_FORCE_SOFTWARE_RENDERING": software,
                        },
                        capture_output=True,
                        timeout=45,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    image = QImage(str(screenshot))
                    self.assertFalse(image.isNull(), "Rust 未产生真实绘制截图")
                    self.assertGreaterEqual(image.width(), minimum[0])
                    self.assertGreaterEqual(image.height(), minimum[1])
                    if window == "main":
                        # 原界面抗锯齿边缘也有少量 alpha，不能退化为不透明矩形。
                        self.assertLess(image.pixelColor(0, 0).alpha(), 64)
                        self.assertEqual(
                            image.pixelColor(
                                image.width() // 2, image.height() // 2
                            ).alpha(),
                            255,
                        )
                    colors = {
                        image.pixel(x, y)
                        for x in range(0, image.width(), 10)
                        for y in range(0, image.height(), 10)
                    }
                    self.assertGreater(len(colors), 8, "Rust 截图只有空白或单色")
