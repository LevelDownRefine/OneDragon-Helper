"""测试 src.gui.main_window 与 QML 应用骨架：脚本列表、背景切换、视频回退。

QML 引擎在 offscreen 下可加载场景（无视频渲染，但场景对象建立）；桥接逻辑
用 mock 隔离 ChainService 文件 I/O。脚本图标 provider 不在加载时触发（Image
渲染时才调用），避免 offscreen 依赖 exe 图标。

各职责已拆到 src/gui/controllers/ 下 mixin；monkeypatch 目标需指向实际引用
该名字的子模块（os/subprocess/webbrowser 指向标准库模块；ChainService 为类方法
patch 指向重导出的 main_window.ChainService；build_script_command 在 launch，
链接相关函数在 links，周常/适配相关函数在 task_card）。
"""

import os
import shutil
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
from src.gui.main_window import QmlBridge  # noqa: E402

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
    # 构造期用 with 屏蔽读盘（QmlBridge 初始化即读 config.yml）；
    # with 退出后失效，故构造后再持久 mock load_config，覆盖 reorderGames/
    # addScript 等构造后真实读盘路径（CI 环境无 config.yml，必须持续屏蔽）。
    with (
        patch.object(
            main_window.ChainService,
            "load_config",
            return_value={"script_list": list(_SCRIPTS)},
        ),
        patch.object(main_window.ChainService, "load_ui_state", return_value={}),
    ):
        b = QmlBridge()
    b.service.load_config = MagicMock(return_value={"script_list": list(_SCRIPTS)})
    # 隔离写盘：避免测试污染真实 config/gui_state.json / config.yml
    b.service.save_config = MagicMock()
    b.service.save_ui_state = MagicMock()
    return b


class TestBridge(unittest.TestCase):
    """QmlBridge：脚本列表 / 背景切换 / 视频回退。"""

    def test_games_loaded_from_config(self):
        b = _make_bridge()
        self.assertEqual([g["display_name"] for g in b.games], ["鸣潮", "测试脚本"])

    def test_background_mode_default_gradient(self):
        # 脚本无 bg 配置且 DEFAULT_BG 不存在时走渐变兜底
        with patch.object(
            main_window.BackgroundController, "resolve_bg", return_value=None
        ):
            b = _make_bridge()
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
            b = _make_bridge()
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
            b = _make_bridge()
        self.assertEqual(b.backgroundMode, "image")

    def test_select_game_switches_background(self):
        b = _make_bridge()
        with patch.object(b.background, "resolve_bg", return_value=None):
            b.selectGame(1)
        self.assertEqual(b.currentIndex, 1)
        self.assertEqual(b.gradientChar, "测")

    def test_select_game_invalid_raises(self):
        b = _make_bridge()
        with self.assertRaises(AssertionError):
            b.selectGame(99)

    def test_video_error_falls_back_gradient(self):
        b = _make_bridge()
        with self.assertLogs(b.background.__class__.__module__, level="WARNING"):
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

    def test_select_game_emits_current_index_changed(self):
        # 白圈（index === Bridge.currentIndex）靠 currentIndexChanged 通知 QML 重算；
        # currentIndex 现已用独立 notify 信号（不再复用 gamesChanged）。若 selectGame
        # 漏 emit，QML 端选中位永远不跟随（Python 层 property 读取测不出）。
        b = _make_bridge()
        emissions = []
        b.currentIndexChanged.connect(lambda: emissions.append(1))
        b.selectGame(1)  # 0 → 1，切换选中
        self.assertEqual(len(emissions), 1)
        emissions.clear()
        b.selectGame(1)  # 同项，不切选中
        self.assertEqual(emissions, [])

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
        with patch.object(b.launch, "_confirm_run") as confirm:
            b.launchAll()
        confirm.assert_not_called()

    def test_launch_script_python(self):
        b = _make_bridge()
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
        b = _make_bridge()
        with (
            patch.object(links, "_get_game_link", return_value=""),
            patch.object(webbrowser, "open") as wb,
        ):
            b.openHome()
        wb.assert_called_once()

    def test_open_bilibili_uses_bridge(self):
        b = _make_bridge()
        with (
            patch.object(links, "_get_game_link", return_value=""),
            patch.object(webbrowser, "open") as wb,
        ):
            b.openBilibili()
        wb.assert_called_once()

    def test_launch_game_starts_exe(self):
        b = _make_bridge()
        with (
            patch.object(links, "_get_game_exe_path", return_value="D:/Game/game.exe"),
            patch.object(links, "open_in_explorer") as start,
        ):
            b.launchGame()
        start.assert_called_once_with("D:/Game/game.exe")

    def test_launch_game_missing_toasts(self):
        b = _make_bridge()
        spy = MagicMock()
        b.toastRequested.connect(spy)
        with patch.object(links, "_get_game_exe_path", return_value=None):
            b.launchGame()
        spy.assert_called_once()

    def test_open_settings_starts_config(self):
        b = _make_bridge()
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
        b = _make_bridge()
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
        b = _make_bridge()
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
        b = _make_bridge()
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
        b = _make_bridge()
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
            from src.gui import main_window
            from src.gui.controllers.game_list import ScriptIconProvider
            from src.gui.icons import UiIconProvider
            from src.gui.main_window import QmlBridge

            app = QApplication([])
            scripts = [
                {"display_name": "鸣潮", "script_path": "scripts/ok-ww/ok-ww.exe", "script_type": "external"},
                {"display_name": "测试脚本", "script_path": "scripts/t.py", "script_type": "python"},
            ]
            with (
                patch.object(main_window.ChainService, "load_config", return_value={"script_list": scripts}),
                patch.object(main_window.ChainService, "load_ui_state", return_value={}),
                patch.object(main_window.BackgroundController, "resolve_bg", return_value=None),
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


class TestTaskCardPopupGeometry(unittest.TestCase):
    """下拉必须完整落在窗口内：超出窗口的部分不可见且滚不到（副本显示不全）。

    崩铁历战余响 9 个副本原先锚在周常区下方（卡片 y≈242 → 窗口 y≈634），
    弹窗高 296 越过 720 底边；又因内容(286) < 视口(288) 而无法滚动，
    实际只看得到 3 个。placePopup 在下方装不下时上翻并按余量封顶高度。
    """

    def test_popups_fit_inside_window(self):
        """离屏加载 main.qml，打开两个下拉，断言几何完整落在窗口内。"""
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
            from src.config.subscript import resolve_script_path
            from src.gui import main_window
            from src.gui.icons import UiIconProvider
            from src.gui.main_window import QmlBridge

            app = QApplication([])
            # 崩铁：真实 config/weekly_list.yml 里历战余响声明了 9 个副本
            scripts = [{
                "display_name": "崩坏：星穹铁道",
                "script_path": "scripts/March7th-Assistant/March7th-Assistant.exe",
                "script_type": "external",
            }]
            with (
                patch.object(main_window.ChainService, "load_config",
                             return_value={"script_list": scripts}),
                patch.object(main_window.ChainService, "load_ui_state", return_value={}),
                patch.object(main_window.BackgroundController, "resolve_bg",
                             return_value=None),
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
                wk = win.findChild(QQuickItem, "weeklyDungeonPopup")
                wk.setProperty("weeklyName", "历战余响")
                wk.setProperty("visible", True)
                dg = win.findChild(QQuickItem, "dungeonPopup")
                dg.setProperty("visible", True)
                QTimer.singleShot(200, lambda: (report("weeklyDungeonPopup"),
                                                report("dungeonPopup"),
                                                app.quit()))

            QTimer.singleShot(600, measure)
            app.exec()
            print("OPTS", len(bridge.weeklyDungeonOptions("历战余响")), flush=True)
            """
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
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
        for name in ("weeklyDungeonPopup", "dungeonPopup"):
            self.assertIn(name, measured, f"未测到 {name}，stdout={proc.stdout}")
            top, height, win_h = measured[name]
            self.assertGreaterEqual(top, 0, f"{name} 顶部超出窗口上沿")
            self.assertLessEqual(
                top + height, win_h, f"{name} 底部超出窗口（top={top} h={height}）"
            )
        # 周常下拉高度 = 选项数 * 32 + 8，应完整放下不被截断
        self.assertEqual(measured["weeklyDungeonPopup"][1], n_opts * 32 + 8)


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
            from src.config.subscript import resolve_script_path
            from src.gui import main_window
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
                patch.object(main_window.ChainService, "load_config",
                             return_value={"script_list": scripts}),
                patch.object(main_window.ChainService, "load_ui_state", return_value={}),
                patch.object(main_window.BackgroundController, "resolve_bg",
                             return_value=None),
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
                card = win.findChild(QQuickItem, "cardRoot")
                print(f"WEEKLY_VISIBLE {wk_area.isVisible()} CARD_H {card.height():.0f}")
                app.quit()

            # 等 Loader 自动加载第 0 个脚本的任务卡
            QTimer.singleShot(600, report)
            app.exec()
            """
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=os.getcwd(),
        )
        self.assertNotIn("ReferenceError", proc.stderr)
        # 输出样例：WEEKLY_VISIBLE false CARD_H 134
        visible = None
        height = None
        for line in proc.stdout.splitlines():
            if line.startswith("WEEKLY_VISIBLE"):
                parts = line.split()
                visible = parts[1]
                height = int(parts[3])
        self.assertEqual(
            visible, "False", f"无周常脚本应隐藏周常区，stdout={proc.stdout}"
        )
        # 128 = 标题+分隔线+日常行(56) 的固定高度，不含周常区（与周常上沿对齐）
        self.assertEqual(
            height, 128, f"无周常脚本卡片高度应为 128，stdout={proc.stdout}"
        )


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
            from src.config.subscript import resolve_script_path
            from src.gui import main_window
            from src.gui.icons import UiIconProvider
            from src.gui.main_window import QmlBridge

            app = QApplication([])
            # 崩铁 March7th-Assistant：weekly_list.yml 声明 2 种周常
            # （货币战争 / 历战余响），历战余响需选副本
            scripts = [{
                "display_name": "崩坏：星穹铁道",
                "script_path": "scripts/March7th-Assistant/March7th-Assistant.exe",
                "script_type": "external",
            }]
            with (
                patch.object(main_window.ChainService, "load_config",
                             return_value={"script_list": scripts}),
                patch.object(main_window.ChainService, "load_ui_state", return_value={}),
                patch.object(main_window.BackgroundController, "resolve_bg",
                             return_value=None),
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
                card = win.findChild(QQuickItem, "cardRoot")
                print(f"WEEKLY_VISIBLE {wk_area.isVisible()} "
                      f"WK_H {wk_area.height():.0f} CARD_H {card.height():.0f}")
                app.quit()

            QTimer.singleShot(600, report)
            app.exec()
            """
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=os.getcwd(),
        )
        self.assertNotIn("ReferenceError", proc.stderr)
        visible = wk_h = card_h = None
        for line in proc.stdout.splitlines():
            if line.startswith("WEEKLY_VISIBLE"):
                parts = line.split()
                visible = parts[1]
                wk_h = int(parts[3])
                card_h = int(parts[5])
        self.assertEqual(visible, "True", f"崩铁应显示周常区，stdout={proc.stdout}")
        # 周常区 = 项数(2) * 行高(56) + 底部留白(16) = 128
        # 卡片 = 128 + 周常区 + 卡片底部留白(16) = 272
        self.assertEqual(wk_h, 128, f"周常区高度应=128，stdout={proc.stdout}")
        self.assertEqual(card_h, 272, f"卡片高度应=272，stdout={proc.stdout}")


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


if __name__ == "__main__":
    unittest.main()
