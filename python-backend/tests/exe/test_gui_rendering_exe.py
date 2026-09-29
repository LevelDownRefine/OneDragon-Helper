"""真实发布界面：验证自动选卡和 Windows WARP 软件渲染。"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from src.update.package import load_manifest, manifest_frontend
from tests.exe import package_dir

PACKAGE = package_dir()
EXE_NAME = "OneDragon-Helper.exe"


def _rust_window_rects(process):
    """读取真正 HWND 的外框和客户区；GPU 截图不包含系统绘制的边缘。"""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetClientRect.argtypes = user32.GetWindowRect.argtypes
    user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    handles = []

    @callback_type
    def find_window(window, _):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(window, ctypes.byref(pid))
        if pid.value == process.pid and user32.IsWindowVisible(window):
            title = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(window, title, len(title))
            # winit 的消息窗口也可能可见，必须匹配主窗口。
            if title.value == "OneDragon · Rust Preview":
                handles.append(window)
        return True

    deadline = time.monotonic() + 30
    while process.poll() is None and time.monotonic() < deadline:
        if not user32.EnumWindows(find_window, 0):
            raise ctypes.WinError(ctypes.get_last_error())
        if handles:
            # 与 Rust 一样读取物理像素，避免 DPI 虚拟化掩盖 1px 偏移。
            previous = user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
            if previous is None:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                outer, client, origin = (
                    wintypes.RECT(),
                    wintypes.RECT(),
                    wintypes.POINT(),
                )
                for function, target in (
                    (user32.GetWindowRect, outer),
                    (user32.GetClientRect, client),
                    (user32.ClientToScreen, origin),
                ):
                    if not function(handles[0], ctypes.byref(target)):
                        raise ctypes.WinError(ctypes.get_last_error())
                return (
                    (outer.left, outer.top, outer.right, outer.bottom),
                    (
                        origin.x,
                        origin.y,
                        origin.x + client.right,
                        origin.y + client.bottom,
                    ),
                )
            finally:
                user32.SetThreadDpiAwarenessContext(previous)
        time.sleep(0.01)
    return None


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
                    try:
                        with subprocess.Popen(
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
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                        ) as process:
                            try:
                                rects = (
                                    _rust_window_rects(process)
                                    if window == "main"
                                    else None
                                )
                                _, stderr = process.communicate(timeout=45)
                            finally:
                                if process.poll() is None:
                                    process.kill()
                                    process.communicate()
                    except subprocess.TimeoutExpired as error:
                        backend_log = root / "logs/onedragon_helper.log"
                        detail = (
                            backend_log.read_text(encoding="utf-8", errors="replace")
                            if backend_log.exists()
                            else "未产生后端日志"
                        )
                        self.fail(f"{error}\n{error.stderr!r}\n{detail[-12000:]}")
                    self.assertEqual(process.returncode, 0, stderr)
                    image = QImage(str(screenshot))
                    self.assertFalse(image.isNull(), "Rust 未产生真实绘制截图")
                    self.assertGreaterEqual(image.width(), minimum[0])
                    self.assertGreaterEqual(image.height(), minimum[1])
                    if window == "main":
                        self.assertIsNotNone(rects, "未找到 Rust 原生主窗口")
                        self.assertEqual(rects[0], rects[1], "系统外框占用了窗口边缘")
                        # 圆角外必须完全透明，矩形遮光层不能残留在四角。
                        for x in (0, image.width() - 1):
                            for y in (0, image.height() - 1):
                                self.assertEqual(image.pixelColor(x, y).alpha(), 0)
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
