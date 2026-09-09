"""启动游戏悬停提示：显示图标、缺失回退与切换刷新。"""

import os
import subprocess
import sys
import textwrap
import unittest


class TestGameIconHint(unittest.TestCase):
    def test_hover_icon_fallback_and_selection_refresh(self):
        code = textwrap.dedent(
            """
            from pathlib import Path
            from unittest.mock import patch
            from PySide6.QtCore import QPointF, Qt, QUrl
            from PySide6.QtGui import QIcon
            from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterSingletonInstance
            from PySide6.QtTest import QTest
            from src.gui.controllers.background import BackgroundController
            from src.gui.icons import UiIconProvider
            from src.gui.main_window import QmlBridge
            from src.service.app_service import AppService
            from tests.test_qml_launcher import _make_bridge

            icon_path = str(Path("assets/ds.ico").resolve())
            with (
                patch.object(AppService, "get_dungeon_map", return_value={}),
                patch.object(AppService, "get_weekly_map", return_value=[]),
                patch.object(BackgroundController, "resolve_bg", return_value=None),
                patch("src.gui.controllers.task_card.get_dungeon", return_value=None),
                patch("src.gui.controllers.task_card.get_sequence", return_value=None),
                patch("src.gui.controllers.links._get_game_exe_path", return_value=icon_path) as read_path,
                patch("src.gui.icons._exe_icon", return_value=QIcon(icon_path)),
            ):
                bridge = _make_bridge()
                qmlRegisterSingletonInstance(QmlBridge, "OneDragonHelper", 1, 0, "Bridge", bridge)
                engine = QQmlApplicationEngine()
                engine.addImageProvider("scripticon", bridge.game_list.icon_provider)
                engine.addImageProvider("uiicon", UiIconProvider())
                engine.load(QUrl.fromLocalFile(str(Path("src/gui/qml/main.qml").resolve())))
                assert len(engine.rootObjects()) == 1
                window = engine.rootObjects()[0]
                window.requestActivate()
                QTest.qWait(200)

                def find_item(name):
                    pending = [window.contentItem()]
                    while pending:
                        item = pending.pop()
                        if item.objectName() == name:
                            return item
                        pending.extend(item.childItems())
                    raise AssertionError(name)

                def hover(name):
                    item = find_item(name)
                    point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
                    QTest.mouseMove(window, point.toPoint())
                    QTest.qWait(200)
                    return point.toPoint()

                hint = find_item("linkHint_game")
                icon = find_item("linkHintIcon_game")
                label = find_item("linkHintText_game")
                assert not hint.isVisible()
                read_path.assert_not_called()
                with patch.object(bridge.links, "launchGame") as launch:
                    point = hover("linkButton_game")
                    assert hint.isVisible() and icon.isVisible() and not label.isVisible()
                    assert hint.width() == 72 and hint.height() == 72
                    assert icon.property("source").toString().startswith("data:image/png;base64,")
                    read_path.assert_called_with("ok-ww")
                    launch.assert_not_called()
                    QTest.mouseClick(window, Qt.LeftButton, pos=point)
                    launch.assert_called_once_with()

                # 鼠标仍停在按钮上时切换脚本，旧图必须立即变为文字。
                read_path.return_value = None
                bridge.selectGame(1)
                QTest.qWait(200)
                assert hint.isVisible() and label.isVisible() and not icon.isVisible()
                assert label.property("text") == "启动游戏" and hint.height() == 32
                read_path.assert_called_with(bridge.games[1]["script_name"])

                # 外部配置补好后，再次悬停即可重读，无需重启。
                hover("linkButton_home")
                assert not hint.isVisible()
                assert find_item("linkHintText_home").property("text") == "项目主页"
                read_path.return_value = icon_path
                hover("linkButton_game")
                assert icon.isVisible() and not label.isVisible()
                read_path.return_value = None
                bridge.gamesChanged.emit()
                QTest.qWait(200)
                assert label.isVisible() and not icon.isVisible()

                # 图片解码失败也退回文字，气泡不能空白。
                with patch.object(bridge.links, "gameIconSource", return_value="data:image/png;base64,AA=="):
                    bridge.gamesChanged.emit()
                    QTest.qWait(200)
                    assert label.isVisible() and not icon.isVisible()
                window.close()
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("ReferenceError", result.stderr)
        self.assertNotIn("TypeError", result.stderr)
        self.assertNotIn("Binding loop", result.stderr)
