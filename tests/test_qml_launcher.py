"""测试 src.gui.qml_bridge 与 QML 应用骨架：脚本列表、背景切换、视频回退。

QML 引擎在 offscreen 下可加载场景（无视频渲染，但场景对象建立）；桥接逻辑
用 mock 隔离 ChainService 文件 I/O。脚本图标 provider 不在加载时触发（Image
渲染时才调用），避免 offscreen 依赖 exe 图标。
"""

import os
import shutil
import subprocess
import sys
import textwrap
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# 禁用 QML 磁盘缓存：损坏的 .qmlc 会导致类型解析错乱
# （Type IconButton unavailable / Cannot assign to "data"）。
os.environ.setdefault("QML_DISABLE_DISK_CACHE", "1")

from PySide6.QtWidgets import QApplication  # noqa: E402

from src.gui import qml_bridge  # noqa: E402
from src.gui.qml_bridge import (  # noqa: E402
    QmlBridge,
    ScriptIconProvider,
    UiIconProvider,
)

# 清理损坏的 QML 磁盘缓存（需在 QQmlApplicationEngine 创建前，保证干净编译）
_local_appdata = os.environ.get("LOCALAPPDATA", "")
if _local_appdata:
    shutil.rmtree(
        os.path.join(_local_appdata, "python", "cache", "qmlcache"),
        ignore_errors=True,
    )

# 全局 QApplication 实例（offscreen 平台，CI 无显示器）
_app = QApplication.instance() or QApplication([])

_SCRIPTS = [
    {
        "display_name": "鸣潮",
        "script_path": "scripts/ok-ww/ok-ww.exe",
        "script_type": "external",
    },
    {
        "display_name": "测试脚本",
        "script_path": "scripts/t.py",
        "script_type": "python",
    },
]


def _make_bridge():
    with (
        patch.object(
            qml_bridge.ChainService,
            "load_config",
            return_value={"script_list": list(_SCRIPTS)},
        ),
        patch.object(qml_bridge.ChainService, "load_ui_state", return_value={}),
        patch.object(QmlBridge, "_wallpapers", return_value={}),
    ):
        return QmlBridge()


class TestBridge(unittest.TestCase):
    """QmlBridge：脚本列表 / 背景切换 / 视频回退。"""

    def test_games_loaded_from_config(self):
        b = _make_bridge()
        self.assertEqual([g["display_name"] for g in b.games], ["鸣潮", "测试脚本"])

    def test_background_mode_default_gradient(self):
        # 脚本无 bg 配置且 DEFAULT_BG 不存在时走渐变兜底
        with patch.object(QmlBridge, "_load_bg", return_value=None):
            b = _make_bridge()
        self.assertEqual(b.backgroundMode, "gradient")
        self.assertEqual(b.gradientChar, "鸣")

    def test_video_mode_when_bg_is_mp4(self):
        with (
            patch.object(QmlBridge, "_load_bg", return_value="C:/fake/clip.mp4"),
            patch.object(qml_bridge.os.path, "isfile", return_value=True),
        ):
            b = _make_bridge()
        self.assertEqual(b.backgroundMode, "video")
        self.assertTrue(b.backgroundUrl.endswith("clip.mp4"))

    def test_image_mode_when_bg_is_jpg(self):
        with (
            patch.object(QmlBridge, "_load_bg", return_value="C:/fake/img.jpg"),
            patch.object(qml_bridge.os.path, "isfile", return_value=True),
        ):
            b = _make_bridge()
        self.assertEqual(b.backgroundMode, "image")

    def test_select_game_switches_background(self):
        b = _make_bridge()
        with patch.object(b, "_load_bg", return_value=None):
            b.selectGame(1)
        self.assertEqual(b.currentIndex, 1)
        self.assertEqual(b.gradientChar, "测")

    def test_select_game_invalid_raises(self):
        b = _make_bridge()
        with self.assertRaises(AssertionError):
            b.selectGame(99)

    def test_video_error_falls_back_gradient(self):
        b = _make_bridge()
        with self.assertWarns(RuntimeWarning):
            b.videoError("boom")
        self.assertEqual(b.backgroundMode, "gradient")


class TestLeftRail(unittest.TestCase):
    """QmlBridge 左侧栏交互：enabled 内存态 / 控制模式 / 重排 / 启动。"""

    def test_enabled_defaults_all_true(self):
        b = _make_bridge()
        self.assertEqual(b.enabledStates, [True, True])

    def test_control_mode_select_toggles_enabled(self):
        b = _make_bridge()
        b.toggleMode()
        self.assertTrue(b.controlMode)
        b.selectGame(0)
        self.assertEqual(b.enabledStates, [False, True])
        b.selectGame(0)  # 再点恢复
        self.assertEqual(b.enabledStates, [True, True])

    def test_browse_mode_select_switches_index(self):
        b = _make_bridge()
        b.selectGame(1)
        self.assertEqual(b.currentIndex, 1)
        self.assertEqual(b.enabledStates, [True, True])  # 浏览模式不改 enabled

    def test_select_all_and_deselect_all(self):
        b = _make_bridge()
        b.deselectAll()
        self.assertEqual(b.enabledStates, [False, False])
        b.selectAll()
        self.assertEqual(b.enabledStates, [True, True])

    def test_reorder_games_syncs_config_and_enabled(self):
        b = _make_bridge()
        b.service.save_config = MagicMock()
        b.deselectAll()
        b.selectAll()
        b.reorderGames(0, 1)  # 鸣潮 → 测试脚本之后
        self.assertEqual([g["display_name"] for g in b.games], ["测试脚本", "鸣潮"])
        b.service.save_config.assert_called_once()

    def test_launch_all_no_enabled_toasts(self):
        b = _make_bridge()
        b.deselectAll()
        with patch.object(b, "_confirm_run") as confirm:
            b.launchAll()
        confirm.assert_not_called()

    def test_launch_script_python(self):
        b = _make_bridge()
        b.selectGame(1)  # 测试脚本（python）
        with (
            patch.object(qml_bridge.os.path, "isfile", return_value=True),
            patch.object(
                qml_bridge,
                "build_script_command",
                return_value=(["python", "--script", "x"], ".", {}),
            ),
            patch.object(qml_bridge.subprocess, "Popen") as popen,
        ):
            b.launchScript()
        popen.assert_called_once()


class TestFloatBar(unittest.TestCase):
    """QmlBridge 悬浮条：打开链接 / 启动游戏 / 脚本目录 / 换壁纸。"""

    def test_open_home_uses_bridge(self):
        b = _make_bridge()
        with (
            patch.object(qml_bridge, "_get_game_homepage", return_value=""),
            patch.object(qml_bridge.webbrowser, "open") as wb,
        ):
            b.openHome()
        wb.assert_called_once()

    def test_open_bilibili_uses_bridge(self):
        b = _make_bridge()
        with (
            patch.object(qml_bridge, "_get_game_bilibili", return_value=""),
            patch.object(qml_bridge.webbrowser, "open") as wb,
        ):
            b.openBilibili()
        wb.assert_called_once()

    def test_launch_game_starts_exe(self):
        b = _make_bridge()
        with (
            patch.object(
                qml_bridge, "_get_game_exe_path", return_value="D:/Game/game.exe"
            ),
            patch("os.startfile", create=True) as start,
        ):
            b.launchGame()
        start.assert_called_once_with("D:/Game/game.exe")

    def test_launch_game_missing_toasts(self):
        b = _make_bridge()
        spy = MagicMock()
        b.toastRequested.connect(spy)
        with patch.object(qml_bridge, "_get_game_exe_path", return_value=None):
            b.launchGame()
        spy.assert_called_once()

    def test_open_settings_starts_config(self):
        b = _make_bridge()
        with (
            patch.object(
                qml_bridge,
                "get_config_yml_path_under_root",
                return_value="C:/cfg/config.yml",
            ),
            patch.object(qml_bridge.os.path, "isfile", return_value=True),
            patch("os.startfile", create=True) as start,
        ):
            b.openSettings()
        start.assert_called_once_with("C:/cfg/config.yml")

    def test_open_settings_missing_toasts(self):
        b = _make_bridge()
        spy = MagicMock()
        b.toastRequested.connect(spy)
        with (
            patch.object(
                qml_bridge,
                "get_config_yml_path_under_root",
                return_value="C:/cfg/config.yml",
            ),
            patch.object(qml_bridge.os.path, "isfile", return_value=False),
        ):
            b.openSettings()
        spy.assert_called_once()

    def test_open_wallpaper_persists_and_switches(self):
        b = _make_bridge()
        b._save_wallpapers = MagicMock()
        b._apply_current = MagicMock()
        with (
            patch(
                "PySide6.QtWidgets.QFileDialog.getOpenFileName",
                return_value=("C:/w.mp4", ""),
            ),
            patch.object(b, "_wallpapers", return_value={}),
        ):
            b.openWallpaper()
        b._save_wallpapers.assert_called_once()
        b._apply_current.assert_called_once()

    def test_add_script_emits_game_added(self):
        b = _make_bridge()
        spy = MagicMock()
        b.gameAdded.connect(spy)
        entry = {
            "display_name": "新脚本",
            "script_path": "scripts/new.py",
            "script_type": "python",
        }
        with (
            patch(
                "PySide6.QtWidgets.QFileDialog.getOpenFileName",
                return_value=("C:/scripts/new.py", ""),
            ),
            patch.object(
                b.service._script_service,
                "build_script_entry",
                return_value=entry,
            ),
            patch.object(b.service, "add_script"),
        ):
            b.addScript()
            b.service.add_script.assert_called_once_with(entry)
        spy.assert_called_once()


class TestQmlApp(unittest.TestCase):
    """QML 场景：main.qml 可构建 + image provider 注册。"""

    def test_main_qml_loads(self):
        """子进程离屏加载 main.qml，验证场景可构建。

        用子进程而非本进程：unittest.main 环境下 PySide6 QML 引擎对 Loader
        类型解析异常（rootObjects=0 且无 warnings），子进程与真实运行环境一致。
        """
        code = textwrap.dedent(
            """
            import os
            os.environ["QT_QPA_PLATFORM"] = "offscreen"
            os.environ["QML_DISABLE_DISK_CACHE"] = "1"
            from unittest.mock import patch
            from PySide6.QtCore import QUrl, QTimer
            from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterSingletonInstance
            from PySide6.QtWidgets import QApplication
            from src.config.subscript import resolve_script_path
            from src.gui import qml_bridge
            from src.gui.qml_bridge import QmlBridge, ScriptIconProvider, UiIconProvider

            app = QApplication([])
            scripts = [
                {"display_name": "鸣潮", "script_path": "scripts/ok-ww/ok-ww.exe", "script_type": "external"},
                {"display_name": "测试脚本", "script_path": "scripts/t.py", "script_type": "python"},
            ]
            with (
                patch.object(qml_bridge.ChainService, "load_config", return_value={"script_list": scripts}),
                patch.object(qml_bridge.ChainService, "load_ui_state", return_value={}),
                patch.object(QmlBridge, "_wallpapers", return_value={}),
                patch.object(QmlBridge, "_load_bg", return_value=None),
            ):
                bridge = QmlBridge()
            qmlRegisterSingletonInstance(QmlBridge, "OneDragonHelper", 1, 0, "Bridge", bridge)
            engine = QQmlApplicationEngine()
            engine.addImageProvider("scripticon", ScriptIconProvider(bridge.games))
            engine.addImageProvider("uiicon", UiIconProvider())
            engine.load(QUrl.fromLocalFile(resolve_script_path("assets/qml/main.qml")))
            # 跑几帧事件循环：Loader 异步加载 TaskCard 后才会求值其绑定，
            # 缺 import OneDragonHelper 会导致 ReferenceError: Bridge is not defined
            QTimer.singleShot(600, app.quit)
            app.exec()
            print("ROOT_OBJECTS", len(engine.rootObjects()), flush=True)
            """
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=os.getcwd(),
        )
        self.assertIn("ROOT_OBJECTS 1", proc.stdout)
        # 回归守卫：子组件（TaskCard 等）必须 import OneDragonHelper 才能在
        # 事件循环中解析 Bridge；缺 import 会让所有 Bridge.xxx 绑定 ReferenceError。
        self.assertNotIn("ReferenceError", proc.stderr)


class TestScriptIconProvider(unittest.TestCase):
    """图标缓存按 script_name（稳定身份）索引，而非行 index。

    根因回归测试：重排只改行位置、index 不变，若按 index 缓存每格图标会停在
    启动时的旧图标（"图标不跟着重排"）。
    """

    def test_request_keys_by_script_name_not_index(self):
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QPixmap

        provider = ScriptIconProvider(
            [
                {"script_name": "a", "script_data": {}},
                {"script_name": "b", "script_data": {}},
            ]
        )
        # 用确定性 Pixmap 替换真实提取，单独验证 cache key 是 script_name
        pmap_a = QPixmap(1, 1)
        pmap_b = QPixmap(2, 2)
        provider._cache = {"a": pmap_a, "b": pmap_b}
        # 按 script_name 取到对应图标
        self.assertIs(provider.requestPixmap("a", None, QSize()), pmap_a)
        self.assertIs(provider.requestPixmap("b", None, QSize()), pmap_b)
        # 旧语义（按行 index）已失效：index 字符串取不到图标
        self.assertTrue(provider.requestPixmap("0", None, QSize()).isNull())

    def test_refresh_adds_missing_only(self):
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QPixmap

        provider = ScriptIconProvider([{"script_name": "a", "script_data": {}}])
        pmap_a = QPixmap(1, 1)
        provider._cache = {"a": pmap_a}
        # 增量刷新：保留已有 a，新增 b
        provider.refresh(
            [
                {"script_name": "a", "script_data": {}},
                {"script_name": "b", "script_data": {}},
            ]
        )
        self.assertIs(provider.requestPixmap("a", None, QSize()), pmap_a)
        self.assertFalse(provider.requestPixmap("b", None, QSize()).isNull())


class TestUiIconProvider(unittest.TestCase):
    """通用 UI 矢量图标（image://uiicon/<name>）全部 name 都能渲染出非透明 pixmap。"""

    def test_all_named_icons_render_non_null(self):
        from PySide6.QtCore import QSize

        names = [
            "home",
            "game",
            "folder",
            "bili",
            "github",
            "wallpaper",
            "settings",
            "min",
            "close",
        ]
        provider = UiIconProvider()
        for name in names:
            pm = provider.requestPixmap(name, None, QSize())
            self.assertFalse(pm.isNull(), f"图标 {name} 渲染为空")
            self.assertEqual((pm.width(), pm.height()), (48, 48))

    def test_unknown_name_returns_null(self):
        from PySide6.QtCore import QSize

        self.assertTrue(UiIconProvider().requestPixmap("nope", None, QSize()).isNull())

    def test_github_icon_paints_at_same_scale_as_others(self):
        """GitHub 图标应与同组图标视觉尺寸一致（此前仅渲染 20×20，明显偏小）。

        测量非透明像素包围盒跨度：github 应 ≈30px，与其余图标（22~32）同级，
        明显大于修复前的 20px。
        """
        from PySide6.QtCore import QSize

        provider = UiIconProvider()
        img = provider.requestPixmap("github", None, QSize()).toImage()
        xs = [
            x
            for y in range(img.height())
            for x in range(img.width())
            if img.pixelColor(x, y).alpha() > 0
        ]
        span = (max(xs) - min(xs) + 1) if xs else 0
        self.assertGreaterEqual(span, 26)
        self.assertLessEqual(span, 32)


class TestWeeklyToggleInit(unittest.TestCase):
    """周常开关应在启动时按 weekly_start 还原（对齐旧 GUI，此前漏迁移）。"""

    def test_init_from_weekly_start(self):
        # 鸣潮 是 exe 脚本，script_name = 进程名 ok-ww（非 display_name）
        b = _make_bridge()
        b._ui_state = {"ok-ww": {"weekly_start": 2}}
        with (
            patch.object(qml_bridge, "_supports_weekly", return_value=True),
            patch.object(qml_bridge, "is_weekly_start_reached", return_value=True),
        ):
            states = b._init_weekly_toggle_states()
        self.assertEqual(states.get("ok-ww"), True)

    def test_unsupported_or_no_start_is_false(self):
        b = _make_bridge()
        b._ui_state = {"ok-ww": {"weekly_start": 2}}
        with patch.object(qml_bridge, "_supports_weekly", return_value=False):
            states = b._init_weekly_toggle_states()
        self.assertEqual(states.get("ok-ww", "absent"), "absent")

    def test_bridge_init_populates_toggle_state(self):
        with (
            patch.object(
                qml_bridge.ChainService,
                "load_config",
                return_value={"script_list": list(_SCRIPTS)},
            ),
            patch.object(
                qml_bridge.ChainService,
                "load_ui_state",
                return_value={"ok-ww": {"weekly_start": 2}},
            ),
            patch.object(qml_bridge, "_supports_weekly", return_value=True),
            patch.object(qml_bridge, "is_weekly_start_reached", return_value=True),
            patch.object(QmlBridge, "_wallpapers", return_value={}),
        ):
            b = QmlBridge()
        self.assertEqual(b._weekly_toggle_state.get("ok-ww"), True)


if __name__ == "__main__":
    unittest.main()
