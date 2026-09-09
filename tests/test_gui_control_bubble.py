"""控制模式气泡：真实 QML 点击、批量启停与退出操作。"""

import os
import subprocess
import sys
import textwrap
import unittest


class TestControlBubble(unittest.TestCase):
    def test_actions_and_dismissal(self):
        code = textwrap.dedent(
            """
            from pathlib import Path
            from unittest.mock import patch
            from PySide6.QtCore import QPoint, QPointF, Qt, QUrl
            from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterSingletonInstance
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication
            from src.gui.controllers.background import BackgroundController
            from src.gui.icons import UiIconProvider
            from src.gui.main_window import QmlBridge
            from src.service.app_service import AppService
            from tests.test_qml_launcher import _make_bridge

            app = QApplication.instance()
            with (
                patch.object(AppService, "get_dungeon_map", return_value={}),
                patch.object(AppService, "get_weekly_map", return_value=[]),
                patch.object(BackgroundController, "resolve_bg", return_value=None),
                patch("src.gui.controllers.task_card.get_dungeon", return_value=None),
                patch("src.gui.controllers.task_card.get_sequence", return_value=None),
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

                def click(name):
                    item = find_item(name)
                    point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
                    QTest.mouseClick(window, Qt.LeftButton, pos=point.toPoint())
                    QTest.qWait(150)

                bubble = find_item("controlBubble")
                assert not bubble.isVisible()
                for name in ("selectAllButton", "deselectAllButton", "addScriptButton"):
                    assert not find_item(name).isVisible()

                # 两个底部按钮不能重叠或越界，悬停只显示说明，点击才启动。
                launch_button = find_item("launchAllButton")
                mode_button = find_item("controlModeButton")
                mode_point = mode_button.mapToScene(QPointF(24, 24))
                QTest.mouseMove(window, mode_point.toPoint())
                QTest.qWait(200)
                mode_hint = find_item("controlModeHint")
                mode_hint_text = find_item("controlModeHintText")
                assert mode_hint.isVisible()
                assert mode_hint_text.property("text") == "控制模式"
                assert not bridge.controlMode
                top = launch_button.mapToScene(QPointF(0, 0))
                mode_bottom = mode_button.mapToScene(QPointF(0, mode_button.height()))
                assert top.y() > mode_bottom.y()
                assert top.y() + launch_button.height() <= window.height()
                with patch.object(bridge.launch, "launchAll") as launch_all:
                    point = launch_button.mapToScene(QPointF(24, 24))
                    QTest.mouseMove(window, point.toPoint())
                    QTest.qWait(200)
                    assert find_item("launchAllHint").isVisible()
                    assert not mode_hint.isVisible()
                    launch_all.assert_not_called()
                    click("launchAllButton")
                    launch_all.assert_called_once_with()

                click("controlModeButton")
                assert bridge.controlMode and bubble.isVisible()
                QTest.mouseMove(window, mode_point.toPoint())
                QTest.qWait(200)
                assert mode_hint.isVisible()
                assert mode_hint_text.property("text") == "退出控制模式"
                assert mode_hint.y() + mode_hint.height() < bubble.y()
                assert bubble.x() >= 80
                assert 0 <= bubble.y() <= window.height() - bubble.height()
                assert bubble.x() + bubble.width() <= window.width()
                click("deselectAllButton")
                assert bridge.enabledStates == [False, False]
                assert bubble.isVisible()
                click("scriptIcon0")
                assert bridge.enabledStates == [True, False]
                assert bubble.isVisible()
                click("selectAllButton")
                assert bridge.enabledStates == [True, True]
                click("controlModeButton")
                assert not bridge.controlMode and not bubble.isVisible()

                click("controlModeButton")
                QTest.mouseClick(window, Qt.LeftButton, pos=QPoint(900, 100))
                assert not bridge.controlMode and not bubble.isVisible()
                click("controlModeButton")
                QTest.keyClick(window, Qt.Key_Escape)
                assert not bridge.controlMode and not bubble.isVisible()

                click("controlModeButton")
                with patch.object(bridge.game_list, "addScript") as add_script:
                    click("addScriptButton")
                    add_script.assert_called_once_with()
                assert not bridge.controlMode and not bubble.isVisible()
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
