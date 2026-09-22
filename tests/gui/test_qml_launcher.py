"""测试 src.gui.main_window 与 QML 应用骨架：脚本列表、背景切换、视频回退。

QML 引擎在 offscreen 下可加载场景（无视频渲染，但场景对象建立）；桥接逻辑
用 mock 隔离 chain_service 模块文件 I/O。脚本图标 provider 不在加载时触发（Image
渲染时才调用），避免 offscreen 依赖 exe 图标。

各职责已拆到 src/gui/controllers/ 下 mixin；monkeypatch 目标需指向实际引用
该名字的子模块（os/subprocess/webbrowser 指向标准库模块；config 读取走 AppService——
其 load_config 已委托 src.utils.utils_config，故 load_config 类方法 patch 指向
AppService；build_script_command 在 launch，链接相关函数在 links，
周常/适配相关函数在 task_card）。
"""

import os
import subprocess
import sys
import textwrap
import unittest
import webbrowser
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# 禁用 QML 磁盘缓存：损坏的 .qmlc 会导致类型解析错乱
# （Type IconButton unavailable / Cannot assign to "data"）。
os.environ.setdefault("QML_DISABLE_DISK_CACHE", "1")

from PySide6.QtWidgets import QApplication  # noqa: E402

from src.gui import main_window  # noqa: E402
from src.gui.controllers import launch, links  # noqa: E402
from src.gui.controllers.game_list import ScriptIconProvider  # noqa: E402
from src.gui.icons import UiIconProvider  # noqa: E402
from tests.gui.helpers import make_bridge  # noqa: E402

# 全局 QApplication 实例（offscreen 平台，CI 无显示器）
_app = QApplication.instance() or QApplication([])

_NATIVE_CONFIG_STUB = (
    "from unittest.mock import patch\n"
    "patch('src.utils.utils_sub_config._load_config_yml', "
    "return_value={'script_list': []}).start()\n"
)


def setUpModule():
    """只模拟原生脚本未安装，应用脚本列表仍由各用例提供。"""
    native_config = patch(
        "src.utils.utils_sub_config._load_config_yml",
        return_value={"script_list": []},
    )
    native_config.start()
    unittest.addModuleCleanup(native_config.stop)


class TestBridge(unittest.TestCase):
    """QmlBridge：脚本列表 / 背景切换 / 视频回退。"""

    def test_games_loaded_from_config(self):
        b = make_bridge()
        self.assertEqual([g["display_name"] for g in b.games], ["鸣潮", "测试脚本"])

    def test_bridges_have_independent_script_config(self):
        first = make_bridge()
        first.games[0]["display_name"] = "已修改"
        first.app_service.load_config()["script_list"][0]["display_name"] = "已保存"
        second = make_bridge()
        self.assertEqual(second.games[0]["display_name"], "鸣潮")
        self.assertEqual(
            second.app_service.load_config()["script_list"][0]["display_name"], "鸣潮"
        )

    def test_background_mode_default_gradient(self):
        # 脚本无 bg 配置且 DEFAULT_BG 不存在时走渐变兜底
        with patch.object(
            main_window.BackgroundController, "resolve_bg", return_value=None
        ):
            b = make_bridge()
        self.assertEqual(b.backgroundMode, "gradient")
        self.assertEqual(b.gradientChar, "鸣")

    def test_video_mode_when_bg_is_mp4(self):
        with (
            patch.object(
                main_window.BackgroundController,
                "resolve_bg",
                return_value="C:/fake/clip.mp4",
            ),
            patch.object(os.path, "isfile", return_value=True),
        ):
            b = make_bridge()
        self.assertEqual(b.backgroundMode, "video")
        self.assertTrue(b.backgroundUrl.endswith("clip.mp4"))

    def test_image_mode_when_bg_is_jpg(self):
        with (
            patch.object(
                main_window.BackgroundController,
                "resolve_bg",
                return_value="C:/fake/img.jpg",
            ),
            patch.object(os.path, "isfile", return_value=True),
        ):
            b = make_bridge()
        self.assertEqual(b.backgroundMode, "image")

    def test_select_game_switches_background(self):
        b = make_bridge()
        with patch.object(b.background, "resolve_bg", return_value=None):
            b.selectGame(1)
        self.assertEqual(b.currentIndex, 1)
        self.assertEqual(b.gradientChar, "测")

    def test_select_game_invalid_raises(self):
        b = make_bridge()
        with self.assertRaises(AssertionError):
            b.selectGame(99)

    def test_video_error_falls_back_gradient(self):
        b = make_bridge()
        with self.assertLogs(b.background.__class__.__module__, level="WARNING"):
            b.videoError("boom")
        self.assertEqual(b.backgroundMode, "gradient")


class TestLeftRail(unittest.TestCase):
    """QmlBridge 左侧栏交互：enabled 内存态 / 控制模式 / 重排 / 启动。"""

    def test_enabled_defaults_all_true(self):
        b = make_bridge()
        self.assertEqual(b.enabledStates, [True, True])

    def test_control_mode_select_toggles_enabled(self):
        b = make_bridge()
        b.toggleMode()
        self.assertTrue(b.controlMode)
        b.selectGame(0)
        self.assertEqual(b.enabledStates, [False, True])
        b.selectGame(0)  # 再点恢复
        self.assertEqual(b.enabledStates, [True, True])

    def test_browse_mode_select_switches_index(self):
        b = make_bridge()
        b.selectGame(1)
        self.assertEqual(b.currentIndex, 1)
        self.assertEqual(b.enabledStates, [True, True])  # 浏览模式不改 enabled

    def test_select_game_emits_current_index_changed(self):
        # 白圈（index === Bridge.currentIndex）靠 currentIndexChanged 通知 QML 重算；
        # currentIndex 现已用独立 notify 信号（不再复用 gamesChanged）。若 selectGame
        # 漏 emit，QML 端选中位永远不跟随（Python 层 property 读取测不出）。
        b = make_bridge()
        emissions = []
        b.currentIndexChanged.connect(lambda: emissions.append(1))
        b.selectGame(1)  # 0 → 1，切换选中
        self.assertEqual(len(emissions), 1)
        emissions.clear()
        b.selectGame(1)  # 同项，不切选中
        self.assertEqual(emissions, [])

    def test_select_all_and_deselect_all(self):
        b = make_bridge()
        b.deselectAll()
        self.assertEqual(b.enabledStates, [False, False])
        b.selectAll()
        self.assertEqual(b.enabledStates, [True, True])

    def test_reorder_games_syncs_config_and_enabled(self):
        b = make_bridge()
        b.app_service.save_config = MagicMock()
        b.deselectAll()
        b.selectAll()
        b.reorderGames(0, 1)  # 鸣潮 → 测试脚本之后
        self.assertEqual([g["display_name"] for g in b.games], ["测试脚本", "鸣潮"])
        b.app_service.save_config.assert_called_once()

    def test_launch_all_no_enabled_toasts(self):
        b = make_bridge()
        b.deselectAll()
        with patch.object(b.launch, "_confirm_run") as confirm:
            b.launchAll()
        confirm.assert_not_called()

    def test_launch_script_python(self):
        b = make_bridge()
        b.selectGame(1)  # 测试脚本（python）
        with (
            patch.object(os.path, "isfile", return_value=True),
            patch.object(
                launch,
                "build_script_command",
                return_value=(["python", "--script", "x"], ".", {}),
            ),
            patch.object(subprocess, "Popen") as popen,
        ):
            b.launchScript()
        popen.assert_called_once()


class TestFloatBar(unittest.TestCase):
    """QmlBridge 悬浮条：打开链接 / 启动游戏 / 脚本目录 / 换壁纸。"""

    def test_open_home_uses_bridge(self):
        b = make_bridge()
        with (
            patch.object(links, "_get_game_link", return_value=""),
            patch.object(webbrowser, "open") as wb,
        ):
            b.openHome()
        wb.assert_called_once()

    def test_open_bilibili_uses_bridge(self):
        b = make_bridge()
        with (
            patch.object(links, "_get_game_link", return_value=""),
            patch.object(webbrowser, "open") as wb,
        ):
            b.openBilibili()
        wb.assert_called_once()

    def test_launch_game_starts_exe(self):
        b = make_bridge()
        with (
            patch.object(links, "_get_game_exe_path", return_value="D:/Game/game.exe"),
            patch.object(links, "open_in_explorer") as start,
        ):
            b.launchGame()
        start.assert_called_once_with("D:/Game/game.exe")

    def test_launch_game_missing_toasts(self):
        b = make_bridge()
        spy = MagicMock()
        b.toastRequested.connect(spy)
        with patch.object(links, "_get_game_exe_path", return_value=None):
            b.launchGame()
        spy.assert_called_once()

    def test_open_settings_starts_config(self):
        b = make_bridge()
        with (
            patch.object(
                links,
                "get_config_yml_path_under_root",
                return_value="C:/cfg/config.yml",
            ),
            patch.object(os.path, "isfile", return_value=True),
            patch.object(links, "open_in_explorer") as start,
        ):
            b.openSettings()
        start.assert_called_once_with("C:/cfg/config.yml")

    def test_open_settings_missing_toasts(self):
        b = make_bridge()
        spy = MagicMock()
        b.toastRequested.connect(spy)
        with (
            patch.object(
                links,
                "get_config_yml_path_under_root",
                return_value="C:/cfg/config.yml",
            ),
            patch.object(os.path, "isfile", return_value=False),
        ):
            b.openSettings()
        spy.assert_called_once()

    def test_open_log_folder_starts_dir(self):
        b = make_bridge()
        with (
            patch.object(
                links, "resolve_script_path", return_value="D:/Game/ok-ww.exe"
            ),
            patch.object(links, "get_log_dir", return_value="D:/Game/logs"),
            patch.object(os.path, "isdir", return_value=True),
            patch.object(links, "open_in_explorer") as start,
        ):
            b.openLogFolder()
        start.assert_called_once_with("D:/Game/logs")

    def test_open_log_folder_no_parser_toasts(self):
        b = make_bridge()
        spy = MagicMock()
        b.toastRequested.connect(spy)
        with (
            patch.object(
                links, "resolve_script_path", return_value="D:/Game/ok-ww.exe"
            ),
            patch.object(links, "get_log_dir", return_value=None),
        ):
            b.openLogFolder()
        spy.assert_called_once()

    def test_open_wallpaper_persists_and_switches(self):
        b = make_bridge()
        b.background.write_wallpapers = MagicMock()
        b.background.apply_current = MagicMock()
        with patch(
            "PySide6.QtWidgets.QFileDialog.getOpenFileName",
            return_value=("C:/w.mp4", ""),
        ):
            b.openWallpaper()
        b.background.write_wallpapers.assert_called_once()
        b.background.apply_current.assert_called_once()

    def test_add_script_emits_game_added(self):
        b = make_bridge()
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
                b.app_service,
                "build_script_entry",
                return_value=entry,
            ),
            patch.object(b.app_service, "add_script"),
        ):
            b.addScript()
            b.app_service.add_script.assert_called_once_with(entry)
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
            from PySide6.QtCore import QUrl, QTimer, QPointF, Qt
            from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterSingletonInstance
            from PySide6.QtQuick import QQuickItem
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication
            from src.utils.utils_sub_config import resolve_script_path
            from src.gui import main_window
            from src.service.app_service import AppService
            from src.gui.controllers.game_list import ScriptIconProvider
            from src.gui.icons import UiIconProvider
            from src.gui.main_window import QmlBridge

            app = QApplication([])
            scripts = [
                {"display_name": "鸣潮", "script_path": "scripts/ok-ww/ok-ww.exe", "script_type": "external"},
                {"display_name": "测试脚本", "script_path": "scripts/t.py", "script_type": "python"},
            ]
            with (
                patch.object(AppService, "load_config", return_value={"script_list": scripts}),
                patch.object(main_window.BackgroundController, "resolve_bg", return_value=None),
            ):
                with (
                    patch("src.service.daily_plan.load_schedule", return_value={}),
                    patch.object(AppService, "list_daily_plan_scripts", return_value=[]),
                ):
                    bridge = QmlBridge()
            qmlRegisterSingletonInstance(QmlBridge, "OneDragonHelper", 1, 0, "Bridge", bridge)
            engine = QQmlApplicationEngine()
            engine.addImageProvider("scripticon", bridge.game_list.icon_provider)
            engine.addImageProvider("uiicon", UiIconProvider())
            engine.load(QUrl.fromLocalFile(resolve_script_path("src/gui/qml/main.qml")))
            # 跑几帧事件循环：Loader 异步加载 TaskCard 后才会求值其绑定，
            # 缺 import OneDragonHelper 会导致 ReferenceError: Bridge is not defined
            QTimer.singleShot(600, app.quit)
            app.exec()
            print("ROOT_OBJECTS", len(engine.rootObjects()), flush=True)
            window = engine.rootObjects()[0]
            # 圆角改由 shell 的 MultiEffect 遮罩提供：窗口本体透明、整窗内容进底图
            # 后按 mask 的 alpha 合成。不再用 QWindow.setMask —— QRegion 是二值区域
            # （无 alpha），圆边只能落在整像素网格上，必现阶梯状锯齿（回归守卫）。
            assert window.mask().isEmpty(), "整窗不应再有 QRegion 遮罩"
            assert window.color().alpha() == 0, "窗口本体应为透明，圆角靠 alpha 提供"
            shell = window.findChild(QQuickItem, "windowShell")
            assert shell is not None, "缺少承载整窗内容的 shell"
            # 整窗内容必须都装在 shell 里，否则圆角遮罩裁不到（背景与侧栏仍是方角）
            assert any(c.objectName() == "gameList" for c in shell.childItems())
            mask_item = window.findChild(QQuickItem, "cornerMask")
            assert mask_item is not None, "缺少圆角遮罩源"
            assert float(mask_item.property("radius")) == 16.0
            # layer.effect 的 item 在视觉树上挂在 contentItem（QObject 无父），只能按
            # 视觉子项查找。
            effect = next(
                (
                    c
                    for c in window.contentItem().childItems()
                    if c.objectName() == "cornerMaskEffect"
                ),
                None,
            )
            assert effect is not None, "shell 缺圆角遮罩"
            assert effect.property("maskEnabled") is True
            # Repeater 委托的 QObject 所有权不等于视觉父子关系，按视觉树查找。
            def find_item(name):
                pending = [window.contentItem()]
                while pending:
                    item = pending.pop()
                    if item.objectName() == name:
                        return item
                    pending.extend(item.childItems())
                raise AssertionError(name)

            # 悬停只改变外观，不能触发重排或显示删除区。
            icon = find_item("scriptIcon0")
            original_y = icon.y()
            for y in (4, 46):
                point = icon.mapToScene(QPointF(icon.width() / 2, y))
                QTest.mouseMove(window, point.toPoint())
            assert icon.y() == original_y
            assert not find_item("gameList").property("dragActive")

            config = find_item("configButton")
            assert config is not None
            position = config.mapToScene(QPointF(config.width() / 2, config.height() / 2))
            with patch.object(bridge.backup, "openConfig") as open_config:
                QTest.mouseClick(window, Qt.LeftButton, pos=position.toPoint())
                open_config.assert_called_once_with()
            # 每日计划只在配置界面编辑，主界面不显示计划卡或快捷按钮。
            for name in ("dailyPlanCard", "dailyPlanSummary", "editDailyPlanButton", "toggleDailyPlanButton"):
                assert window.findChild(QQuickItem, name) is None
            # 主操作与脚本配置相邻，点配置不能误触启动。
            with (
                patch.object(bridge.launch, "launchScript") as launch,
                patch.object(bridge.game_list, "configCurrent") as settings,
            ):
                for name in ("scriptSettingsButton", "launchScriptButton"):
                    item = find_item(name)
                    assert item is not None
                    point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
                    QTest.mouseClick(window, Qt.LeftButton, pos=point.toPoint())
                    if name == "scriptSettingsButton":
                        settings.assert_called_once_with()
                        launch.assert_not_called()
                    else:
                        launch.assert_called_once_with()
                        settings.assert_called_once_with()
            # 长路径提示应换行且完整留在窗口里。
            bridge.toastRequested.emit("配置已备份：" + "folder/" * 70 + "backup.zip")
            QTest.qWait(50)
            toast = window.findChild(QQuickItem, "toast")
            text = window.findChild(QQuickItem, "toastText")
            assert toast.isVisible()
            assert text.property("lineCount") > 1
            assert toast.x() >= 80 and toast.y() >= 0
            assert toast.x() + toast.width() <= window.width()
            assert toast.y() + toast.height() <= window.height()
            """
        )
        proc = subprocess.run(
            [sys.executable, "-c", _NATIVE_CONFIG_STUB + code],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=os.getcwd(),
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("ROOT_OBJECTS 1", proc.stdout)
        # 回归守卫：子组件（TaskCard 等）必须 import OneDragonHelper 才能在
        # 事件循环中解析 Bridge；缺 import 会让所有 Bridge.xxx 绑定 ReferenceError。
        self.assertNotIn("ReferenceError", proc.stderr)
        self.assertNotIn("TypeError", proc.stderr)
        self.assertNotIn("Binding loop", proc.stderr)


class TestTaskCardPopupGeometry(unittest.TestCase):
    """下拉必须完整落在窗口内：超出窗口的部分不可见且滚不到（副本显示不全）。

    弹窗原先锚在周常区下方（卡片 y≈242 → 窗口 y≈634），长清单高度越过 720 底边；
    又因内容 < 视口而无法滚动，实际只看得到 3 项。placePopup 在下方装不下时上翻并按余量封顶。

    真实声明当前无周常带副本选型，故这里桩掉周常菜单，给一条带 9 个副本的假声明——
    本用例只验证弹窗几何，与真实清单内容无关。
    """

    def test_popups_fit_inside_window(self):
        """离屏加载 main.qml，打开周常 / 日常两个下拉，断言几何完整落在窗口内。"""
        code = textwrap.dedent(
            """
            import os
            os.environ["QT_QPA_PLATFORM"] = "offscreen"
            os.environ["QML_DISABLE_DISK_CACHE"] = "1"
            from unittest.mock import patch
            from PySide6.QtCore import QUrl, QTimer, QPointF
            from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterSingletonInstance
            from PySide6.QtQuick import QQuickItem
            from PySide6.QtWidgets import QApplication
            from src.utils.utils_sub_config import resolve_script_path
            from src.gui import main_window
            from src.service.app_service import AppService
            from src.gui.icons import UiIconProvider
            from src.gui.main_window import QmlBridge

            app = QApplication([])
            scripts = [{
                "display_name": "崩坏：星穹铁道",
                "script_path": "scripts/March7th-Launcher/March7th-Launcher.exe",
                "script_type": "external",
            }]
            fake_tasks = [f"副本{i}" for i in range(1, 10)]
            fake_weekly = [{
                "display_name": "历战余响",
                "options": {
                    "values": [
                        {"display_name": t, "physical_name": t} for t in fake_tasks
                    ]
                },
            }]
            with (
                patch.object(AppService, "load_config",
                             return_value={"script_list": scripts}),
                patch.object(main_window.BackgroundController, "resolve_bg",
                             return_value=None),
                patch("src.service.app_service.get_weekly_map",
                      return_value=fake_weekly),
            ):
                with (
                    patch("src.service.daily_plan.load_schedule", return_value={}),
                    patch.object(AppService, "list_daily_plan_scripts", return_value=[]),
                ):
                    bridge = QmlBridge()
                qmlRegisterSingletonInstance(
                    QmlBridge, "OneDragonHelper", 1, 0, "Bridge", bridge)
                engine = QQmlApplicationEngine()
                engine.addImageProvider("uiicon", UiIconProvider())
                engine.load(QUrl.fromLocalFile(resolve_script_path("src/gui/qml/main.qml")))
                win = engine.rootObjects()[0]

                def report(name):
                    item = win.findChild(QQuickItem, name)
                    top = item.mapToScene(QPointF(0, 0)).y()
                    print(f"{name} TOP {top:.0f} H {item.height():.0f} "
                          f"WIN {win.height()}", flush=True)

                def measure():
                    wk = win.findChild(QQuickItem, "weeklyPopup")
                    wk.setProperty("weeklyName", "历战余响")
                    wk.setProperty("visible", True)
                    dg = win.findChild(QQuickItem, "dailyPopup")
                    dg.setProperty("visible", True)
                    QTimer.singleShot(200, lambda: (report("weeklyPopup"),
                                                    report("dailyPopup"),
                                                    app.quit()))

                QTimer.singleShot(600, measure)
                app.exec()
                print("OPTS", len(bridge.weeklyOptions("历战余响")), flush=True)
            """
        )
        proc = subprocess.run(
            [sys.executable, "-c", _NATIVE_CONFIG_STUB + code],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=os.getcwd(),
        )
        self.assertNotIn("ReferenceError", proc.stderr)
        opts_line = [ln for ln in proc.stdout.splitlines() if ln.startswith("OPTS")]
        self.assertTrue(opts_line, f"未取到副本数，stdout={proc.stdout}")
        n_opts = int(opts_line[0].split()[1])
        self.assertGreater(n_opts, 3, "副本清单应多于 3（否则测不出显示不全）")

        measured = {}
        for line in proc.stdout.splitlines():
            parts = line.split()
            if len(parts) == 7 and parts[1] == "TOP":
                measured[parts[0]] = (int(parts[2]), int(parts[4]), int(parts[6]))
        for name in ("weeklyPopup", "dailyPopup"):
            self.assertIn(name, measured, f"未测到 {name}，stdout={proc.stdout}")
            top, height, win_h = measured[name]
            self.assertGreaterEqual(top, 0, f"{name} 顶部超出窗口上沿")
            self.assertLessEqual(
                top + height, win_h, f"{name} 底部超出窗口（top={top} h={height}）"
            )
        # 周常下拉高度 = 选项数 * 32 + 8，应完整放下不被截断
        self.assertEqual(measured["weeklyPopup"][1], n_opts * 32 + 8)


class TestTaskCardWeeklyHiddenForUnsupportedScript(unittest.TestCase):
    """无周常的已适配脚本不应显示周常区及总开关（回归 issue）。"""

    def test_weekly_area_hidden_when_not_supported(self):
        code = textwrap.dedent(
            r"""
            from PySide6.QtCore import QTimer, QUrl
            from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterSingletonInstance
            from PySide6.QtQuick import QQuickItem
            from PySide6.QtWidgets import QApplication
            from unittest.mock import patch
            from src.utils.utils_sub_config import resolve_script_path
            from src.gui import main_window
            from src.service.app_service import AppService
            from src.gui.icons import UiIconProvider
            from src.gui.main_window import QmlBridge

            app = QApplication([])
            # 异环 ok-nte：已适配（在 set_config 注册）但 weekly_list.yml 未声明周常
            scripts = [{
                "display_name": "异环",
                "script_path": "scripts/ok-nte/ok-nte.exe",
                "script_type": "external",
            }]
            with (
                patch.object(AppService, "load_config",
                             return_value={"script_list": scripts}),
                patch.object(main_window.BackgroundController, "resolve_bg",
                             return_value=None),
            ):
                with (
                    patch("src.service.daily_plan.load_schedule", return_value={}),
                    patch.object(AppService, "list_daily_plan_scripts", return_value=[]),
                ):
                    bridge = QmlBridge()
            qmlRegisterSingletonInstance(
                QmlBridge, "OneDragonHelper", 1, 0, "Bridge", bridge)
            engine = QQmlApplicationEngine()
            engine.addImageProvider("uiicon", UiIconProvider())
            engine.load(QUrl.fromLocalFile(resolve_script_path("src/gui/qml/main.qml")))
            win = engine.rootObjects()[0]

            def report():
                wk_area = win.findChild(QQuickItem, "weeklyArea")
                daily_area = win.findChild(QQuickItem, "dailyArea")
                card = win.findChild(QQuickItem, "cardRoot")
                print(f"WEEKLY_VISIBLE {wk_area.isVisible()} CARD_H {card.height():.0f} "
                      f"BOT_PAD {card.height() - (daily_area.y() + daily_area.height()):.0f}")
                app.quit()

            # 等 Loader 自动加载第 0 个脚本的任务卡
            QTimer.singleShot(600, report)
            app.exec()
            """
        )
        proc = subprocess.run(
            [sys.executable, "-c", _NATIVE_CONFIG_STUB + code],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=os.getcwd(),
        )
        self.assertNotIn("ReferenceError", proc.stderr)
        # 输出样例：WEEKLY_VISIBLE false CARD_H 196 BOT_PAD 16
        visible = None
        height = bot_pad = None
        for line in proc.stdout.splitlines():
            if line.startswith("WEEKLY_VISIBLE"):
                parts = line.split()
                visible = parts[1]
                height = int(parts[3])
                bot_pad = int(parts[5])
        self.assertEqual(
            visible, "False", f"无周常脚本应隐藏周常区，stdout={proc.stdout}"
        )
        # 68（分隔线后日常区上沿）+ 行高56*2（异环两个日常各一行）+ 底部留白16 = 196
        self.assertEqual(
            height, 196, f"无周常脚本卡片高度应为 196，stdout={proc.stdout}"
        )
        # 日常区是最后一个区块：卡片底部到它的距离 = 底部留白 16（与有周常时一致）
        self.assertEqual(bot_pad, 16, f"日常区下方背景应留 16，stdout={proc.stdout}")


class TestTaskCardWeeklyAreaHeightForSupportedScript(unittest.TestCase):
    """有周常的已适配脚本：周常区高度必须由数据模型长度推导（回归 issue）。

    历史 bug：周常区高度曾绑定 `weeklyItemsCol.count`，但 Column 类型并无
    count 属性（那是 Repeater 的），绑定求值出错回退为 0，导致卡片背景被
    算成 134+0+padding、把周常内容截短（"背景不够长"）。正确来源是
    Bridge.weeklyItems.length（与 Repeater 渲染数一致）。此测试把高度钉死，
    防止再次回退到 Column.count / 写错模型长度。
    """

    def test_weekly_area_height_matches_item_count(self):
        code = textwrap.dedent(
            r"""
            from PySide6.QtCore import QTimer, QUrl
            from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterSingletonInstance
            from PySide6.QtQuick import QQuickItem
            from PySide6.QtWidgets import QApplication
            from unittest.mock import patch
            from src.utils.utils_sub_config import resolve_script_path
            from src.gui import main_window
            from src.service.app_service import AppService
            from src.gui.icons import UiIconProvider
            from src.gui.main_window import QmlBridge

            app = QApplication([])
            # 崩铁 March7th-Launcher：weekly_task_list.yml 声明 3 种周常
            # （货币战争 / 历战余响 / 模拟宇宙），均无副本选型，故不读游戏侧资源。
            scripts = [{
                "display_name": "崩坏：星穹铁道",
                "script_path": "scripts/March7th-Launcher/March7th-Launcher.exe",
                "script_type": "external",
            }]
            # patch 必须常驻到子进程结束：QML 属性在 600ms 后求值，届时 with 块早已退出。
            patch.object(AppService, "load_config",
                         return_value={"script_list": scripts}).start()
            patch.object(main_window.BackgroundController, "resolve_bg",
                         return_value=None).start()
            patch("src.config.daily_config.read_task_source",
                  return_value=["无", "坏灭的喜剧", "铁骸的锈冢", "晨昏的回眸",
                                "心兽的战场", "尘梦的赞礼", "蛀星的旧靥",
                                "不死的神实", "寒潮的落幕", "毁灭的开端"]).start()
            # 周几起落在 weekly.yml（用户文件，CI 无、本地格式随版本而变）：指向不存在的
            # 路径，读取器按「未设置」回退空结构，测试不依赖运行时数据。
            patch("src.utils.utils_weekly.get_weekly_yml_path_under_root",
                  return_value="__no_weekly_yml__").start()
            patch("src.service.daily_plan.load_schedule", return_value={}).start()
            patch.object(AppService, "list_daily_plan_scripts", return_value=[]).start()
            bridge = QmlBridge()
            qmlRegisterSingletonInstance(
                QmlBridge, "OneDragonHelper", 1, 0, "Bridge", bridge)
            engine = QQmlApplicationEngine()
            engine.addImageProvider("uiicon", UiIconProvider())
            engine.load(QUrl.fromLocalFile(resolve_script_path("src/gui/qml/main.qml")))
            win = engine.rootObjects()[0]

            def report():
                wk_area = win.findChild(QQuickItem, "weeklyArea")
                daily_area = win.findChild(QQuickItem, "dailyArea")
                card = win.findChild(QQuickItem, "cardRoot")
                print(f"WEEKLY_VISIBLE {wk_area.isVisible()} "
                      f"WK_H {wk_area.height():.0f} CARD_H {card.height():.0f} "
                      f"SEC_GAP {wk_area.y() - (daily_area.y() + daily_area.height()):.0f} "
                      f"BOT_PAD {card.height() - (wk_area.y() + wk_area.height()):.0f}")
                app.quit()

            QTimer.singleShot(600, report)
            app.exec()
            """
        )
        proc = subprocess.run(
            [sys.executable, "-c", _NATIVE_CONFIG_STUB + code],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=os.getcwd(),
        )
        self.assertNotIn("ReferenceError", proc.stderr)
        visible = wk_h = card_h = sec_gap = bot_pad = None
        for line in proc.stdout.splitlines():
            if line.startswith("WEEKLY_VISIBLE"):
                parts = line.split()
                visible = parts[1]
                wk_h = int(parts[3])
                card_h = int(parts[5])
                sec_gap = int(parts[7])
                bot_pad = int(parts[9])
        self.assertEqual(visible, "True", f"崩铁应显示周常区，stdout={proc.stdout}")
        # 周常区 = 项数(3) * 行高(56) = 168（底部留白不在区块高度里）
        # 卡片 = 68（日常区上沿）+ 56*1（崩铁一个日常）+ 168 + 卡片底部留白(16) = 308
        self.assertEqual(wk_h, 168, f"周常区高度应=168，stdout={proc.stdout}")
        self.assertEqual(card_h, 308, f"卡片高度应=308，stdout={proc.stdout}")
        # 区块间距为 0：任务行自带上下留白（各 10），区块外沿直接相接时
        # 「日常→周常」的净距 = 20 = 「日常→日常」的行间净距，纵向节奏才一致。
        self.assertEqual(
            sec_gap, 0, f"日常区与周常区之间不应有额外间距，stdout={proc.stdout}"
        )
        # 周常区是最后一个区块：卡片底部到它的距离同样 = 16，与无周常时的日常区一致。
        self.assertEqual(bot_pad, 16, f"周常区下方背景应留 16，stdout={proc.stdout}")


class TestWeeklyRowChipGeometry(unittest.TestCase):
    """周常行拆成「周几起 + 副本」两块 chip：合计宽 = 日常单个 chip 宽，右边界对齐。

    真实声明当前无周常带副本选型，故桩掉周常菜单，用两条假周常同时覆盖两种形态：
    无副本（只有周几起，独占整宽）与有副本（周几起 + 副本各占半宽）。
    """

    def test_weekly_chips_split_daily_chip_width(self):
        code = textwrap.dedent(
            """
            import os
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            from PySide6.QtCore import QTimer, QUrl
            from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterSingletonInstance
            from PySide6.QtQuick import QQuickItem
            from PySide6.QtWidgets import QApplication
            from unittest.mock import patch
            from src.utils.utils_sub_config import resolve_script_path
            from src.gui import main_window
            from src.service.app_service import AppService
            from src.gui.icons import UiIconProvider
            from src.gui.main_window import QmlBridge

            app = QApplication([])
            scripts = [{
                "display_name": "崩坏：星穹铁道",
                "script_path": "scripts/March7th-Launcher/March7th-Launcher.exe",
                "script_type": "external",
            }]
            # 真实声明当前无周常带副本选型，故桩掉周常菜单，给两条假周常覆盖两种形态：
            # 无副本（周几起独占整宽）与有副本（周几起 + 副本各占半宽）。
            fake_weekly = [
                {"display_name": "无副本周常"},
                {
                    "display_name": "有副本周常",
                    "options": {
                        "values": [
                            {"display_name": f"副本{i}", "physical_name": f"副本{i}"}
                            for i in range(1, 4)
                        ]
                    },
                },
            ]
            patch.object(AppService, "load_config",
                         return_value={"script_list": scripts}).start()
            patch.object(main_window.BackgroundController, "resolve_bg",
                         return_value=None).start()
            patch("src.service.app_service.get_weekly_map",
                  return_value=fake_weekly).start()
            # 周几起落用户文件：指向不存在的路径，按「未设置」回退。
            patch("src.utils.utils_weekly.get_weekly_yml_path_under_root",
                  return_value="__no_weekly_yml__").start()
            patch("src.service.daily_plan.load_schedule", return_value={}).start()
            patch.object(AppService, "list_daily_plan_scripts", return_value=[]).start()
            bridge = QmlBridge()
            qmlRegisterSingletonInstance(
                QmlBridge, "OneDragonHelper", 1, 0, "Bridge", bridge)
            engine = QQmlApplicationEngine()
            engine.addImageProvider("uiicon", UiIconProvider())
            engine.load(QUrl.fromLocalFile(resolve_script_path("src/gui/qml/main.qml")))
            win = engine.rootObjects()[0]

            found = {}

            # Repeater 的 delegate 不在 QObject 子树里（findChild 找不到），
            # 只能沿可视子树 childItems() 递归收集 objectName。
            def walk(item):
                for child in item.childItems():
                    name = child.objectName()
                    if name and name not in found:
                        found[name] = child
                    walk(child)

            def chip(key):
                item = found[key]
                return f"{item.x():.0f},{item.width():.0f},{int(item.isVisible())}"

            def report():
                walk(win.contentItem())
                print("DAILY", chip("dailyButton"))
                print("START0", chip("weeklyStartButton0"))
                print("TASK0", chip("weeklyTaskButton0"))
                print("START1", chip("weeklyStartButton1"))
                print("TASK1", chip("weeklyTaskButton1"))
                # 副本下拉：打开「有副本周常」那行的下拉，检查它挂在副本 chip 下面
                area = found["weeklyArea"]
                row_h = int(area.property("rowH"))
                top = area.y() + row_h
                popup = found["weeklyPopup"]
                popup.setProperty("weeklyName", "有副本周常")
                popup.setProperty("anchorTop", top)
                popup.setProperty("anchorBottom", top + row_h)
                popup.setProperty("visible", True)
                QTimer.singleShot(150, report_popup)

            def report_popup():
                from PySide6.QtCore import QPointF
                chip_item = found["weeklyTaskButton1"]
                popup = found["weeklyPopup"]
                card = found["cardRoot"]
                chip_right = chip_item.mapToScene(QPointF()).x() + chip_item.width()
                popup_left = popup.mapToScene(QPointF()).x()
                popup_right = popup_left + popup.width()
                card_left = card.mapToScene(QPointF()).x()
                card_right = card_left + card.width()
                inside = int(card_left <= popup_left and popup_right <= card_right)
                print("POPUP", f"{chip_right:.0f},{popup_left:.0f},{popup_right:.0f},{inside}")
                app.quit()

            QTimer.singleShot(600, report)
            app.exec()
            """
        )
        proc = subprocess.run(
            [sys.executable, "-c", _NATIVE_CONFIG_STUB + code],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=os.getcwd(),
        )
        for error in ("ReferenceError", "TypeError", "Binding loop"):
            self.assertNotIn(error, proc.stderr)

        def rect(key):
            line = next(
                (ln for ln in proc.stdout.splitlines() if ln.startswith(key + " ")),
                None,
            )
            self.assertIsNotNone(line, f"未见 {key}，stdout={proc.stdout}")
            return [float(v) for v in line.split()[1].split(",")]

        daily = rect("DAILY")
        start0 = rect("START0")
        task0 = rect("TASK0")
        start1 = rect("START1")
        task1 = rect("TASK1")
        popup = rect("POPUP")

        daily_w = daily[1]
        # 两块 chip 起点同为 chipX，与日常 chip 左对齐
        self.assertEqual(start0[0], daily[0])
        self.assertEqual(start1[0], daily[0])
        # 周几起 + 副本（含中间 gap）合计宽 = 日常单个 chip 宽 → 右边界对齐
        gap = task1[0] - (start1[0] + start1[1])
        self.assertEqual(start1[1] + gap + task1[1], daily_w)
        self.assertEqual(task1[0] + task1[1], daily[0] + daily_w)
        # 无副本选型：只有周几起，且它独占整宽、与日常 chip 等宽（完全对齐）；
        # 有副本选型：周几起 + 副本并存
        self.assertEqual(task0[2], 0, "无需选副本的周常不应显示副本 chip")
        self.assertEqual(
            start0[1], daily_w, "无副本选型时「周几起」应独占整宽，与日常 chip 对齐"
        )
        self.assertEqual(task1[2], 1, "需选副本的周常应显示副本 chip")
        # 副本下拉挂在副本 chip 下方：右边界与副本 chip 齐平，且整块留在卡片内
        self.assertEqual(popup[2], popup[0], "下拉右边界应与副本 chip 右边界对齐")
        self.assertEqual(popup[3], 1, "下拉应完整落在卡片内")


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

    def test_refresh_recomputes_all(self):
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QPixmap

        provider = ScriptIconProvider([{"script_name": "a", "script_data": {}}])
        provider._cache = {"a": QPixmap(1, 1)}
        # 全量重算：既有 a 也重新取图标（改路径后需即时刷新），而非仅新增 b
        with patch.object(
            ScriptIconProvider, "_load_icon", return_value=QPixmap(5, 5)
        ) as mock_load:
            provider.refresh(
                [
                    {"script_name": "a", "script_data": {}},
                    {"script_name": "b", "script_data": {}},
                ]
            )
        # a、b 都被重新提取（全量重算，不跳过既有项）
        self.assertEqual(mock_load.call_count, 2)
        self.assertEqual(provider.requestPixmap("a", None, QSize()).width(), 5)
        self.assertEqual(provider.requestPixmap("b", None, QSize()).width(), 5)


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
            "play",
            "play_all",
            "chevron_down",
            "grid",
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


if __name__ == "__main__":
    unittest.main()
