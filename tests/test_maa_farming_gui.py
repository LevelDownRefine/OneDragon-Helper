"""三个刷图日常在固定主界面中完整显示，并独立写回。"""

import subprocess
import sys
import textwrap
import unittest


class TestMaaTaskCard(unittest.TestCase):
    def test_last_daily_remains_reachable_and_popup_writes_its_native_flag(self):
        code = textwrap.dedent(
            """
            import copy
            from unittest.mock import patch
            from PySide6.QtCore import QPointF, Qt, QUrl
            from PySide6.QtWidgets import QApplication
            from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterSingletonInstance
            from PySide6.QtQuick import QQuickItem
            from PySide6.QtTest import QTest
            from src.gui.main_window import QmlBridge
            from src.gui.icons import UiIconProvider
            from src.service.app_service import AppService
            from src.utils.utils_sub_config import resolve_script_path
            from tests.test_arknights_config_safety import load_fixture
            from tests.config_diff import diff_paths

            app = QApplication([])
            data = load_fixture()
            queue = data["Configurations"]["Default"]["TaskQueue"]
            remain_index = next(i for i, task in enumerate(queue) if task["Name"] == "土")
            queue[remain_index]["Name"] = "剩余理智"
            queue[remain_index]["IsEnable"] = True
            before = copy.deepcopy(data)
            def save(script, path, value):
                data.clear()
                data.update(copy.deepcopy(value))
            scripts = [{"display_name": "明日方舟", "script_path": "scripts/MAA/MAA.exe", "script_type": "external"}]
            with (
                patch.object(AppService, "load_config", return_value={"script_list": scripts}),
                patch.object(AppService, "list_daily_plan_scripts", return_value=[]),
                patch("src.service.daily_plan.load_schedule", return_value={}),
                patch("src.config.daily.load_config", side_effect=lambda *args: copy.deepcopy(data)),
                patch("src.config.daily.save_config", side_effect=save),
                patch("src.config.daily_config.get_task_lists", return_value=STAGE_CHOICES),
                patch("src.gui.controllers.background.BackgroundController.resolve_bg", return_value=None),
            ):
                bridge = QmlBridge()
                assert len(bridge.dailyItems) == 3
                assert bridge.dailyItems[-1]["can_disable"]
                qmlRegisterSingletonInstance(QmlBridge, "OneDragonHelper", 1, 0, "Bridge", bridge)
                engine = QQmlApplicationEngine()
                engine.addImageProvider("uiicon", UiIconProvider())
                engine.addImageProvider("scripticon", bridge.game_list.icon_provider)
                engine.load(QUrl.fromLocalFile(resolve_script_path("src/gui/qml/main.qml")))
                assert len(engine.rootObjects()) == 1
                window = engine.rootObjects()[0]
                QTest.qWait(100)
                card = window.findChild(QQuickItem, "cardRoot")
                assert card.mapToScene(QPointF(0, card.height())).y() <= window.height()
                # Repeater 委托位于可视树，不一定挂在 QObject 父子树上。
                pending, chip = [card], None
                while pending:
                    item = pending.pop()
                    if item.objectName() == "dailyButton2":
                        chip = item
                    pending.extend(item.childItems())
                assert chip is not None
                center = chip.mapToScene(QPointF(chip.width() / 2, chip.height() / 2)).toPoint()
                assert 392 + 68 <= center.y() < window.height()
                QTest.mouseClick(window, Qt.LeftButton, pos=center)
                popup = card.findChild(QQuickItem, "dailyPopup")
                assert popup.isVisible() and popup.property("dailyName") == "剩余理智"
                top = popup.mapToScene(QPointF()).y()
                assert top >= 8 and top + popup.height() <= window.height() - 8
                pending, button = [popup], None
                while pending:
                    item = pending.pop()
                    if item.inherits("QQuickFlickable"):
                        item.setProperty("contentY", max(0, item.property("contentHeight") - item.height()))
                    if item.property("text") == "不启用":
                        button = item
                    pending.extend(item.childItems())
                assert button is not None
                QTest.qWait(20)
                point = button.mapToScene(QPointF(button.width() / 2, button.height() / 2)).toPoint()
                QTest.mouseClick(window, Qt.LeftButton, pos=point)
                assert not popup.isVisible()
                assert bridge.dailyItems[-1]["disabled"]
                assert {path for path, _, _ in diff_paths(before, data)} == {
                    f"Configurations.Default.TaskQueue[{remain_index}].IsEnable"
                }
                window.close()
                engine.deleteLater()
                QTest.qWait(20)
            """
        )
        code = code.replace(
            "STAGE_CHOICES", repr([f"1-{index}" for index in range(1, 403)])
        )
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, timeout=30
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for error in ("ReferenceError", "TypeError", "Binding loop", "Traceback"):
            self.assertNotIn(error, result.stderr)
