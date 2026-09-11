"""真实 QML 场景：点击第二个日常、滚动到末项，写回携带对应名字。"""

import os
import subprocess
import sys
import textwrap
import unittest


class TestDailyRows(unittest.TestCase):
    def test_nte_menus_disable_only_the_selected_daily(self):
        code = textwrap.dedent(
            r"""
            import traceback
            from copy import deepcopy
            from unittest.mock import patch
            from PySide6.QtCore import QTimer, QUrl, Qt, QPointF
            from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterSingletonInstance
            from PySide6.QtQuick import QQuickItem
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication
            from src.config import set_config as adapters
            from src.config.task_config import load_daily_map
            from src.gui.main_window import QmlBridge
            from src.gui.icons import UiIconProvider
            from src.service.app_service import AppService
            from src.utils.utils_sub_config import resolve_script_path

            app = QApplication([])
            definitions = load_daily_map()["ok-nte"]
            scripts = [{"display_name": "异环", "script_path": "scripts/ok-nte/ok-nte.exe",
                        "script_type": "external"}]
            main_path = adapters.NTEConfig._config_rel_path
            routine_path = adapters.NTEConfig._routine_config_rel_path
            native = {"daily_anomaly": {"任务类型": "空幕", "空幕序号": 1},
                      "daily_anomaly_hunter": {"追猎目标": "海囚"}}
            files = {main_path: deepcopy(native), routine_path: {"Routine Items": [
                {"id": "daily_anomaly", "enabled": True},
                {"id": "daily_anomaly_hunter", "enabled": True},
                {"id": "mail", "enabled": True}]}}
            def save(script, path, config):
                assert script == "ok-nte"
                files[path] = deepcopy(config)

            with (
                patch.object(AppService, "load_config", return_value={"script_list": scripts}),
                patch.object(AppService, "get_daily_map", return_value={"ok-nte": definitions}),
                patch.object(AppService, "get_weekly_map", return_value=[]),
                patch.object(adapters, "load_config", side_effect=lambda _, path: deepcopy(files[path])),
                patch.object(adapters, "save_config", side_effect=save),
            ):
                bridge = QmlBridge()
                qmlRegisterSingletonInstance(QmlBridge, "OneDragonHelper", 1, 0, "Bridge", bridge)
                engine = QQmlApplicationEngine()
                engine.addImageProvider("uiicon", UiIconProvider())
                engine.load(QUrl.fromLocalFile(resolve_script_path("src/gui/qml/main.qml")))
                assert engine.rootObjects(), "QML 场景未加载"
                win = engine.rootObjects()[0]

                def items(item):
                    yield item
                    for child in item.childItems():
                        yield from items(child)

                def click(item, x=None, y=None):
                    point = item.mapToScene(QPointF(
                        item.width() / 2 if x is None else x,
                        item.height() / 2 if y is None else y))
                    QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier, point.toPoint())
                    QTest.qWait(50)

                def verify():
                    try:
                        for index, daily_name in enumerate(("daily_anomaly", "daily_anomaly_hunter")):
                            card = win.findChild(QQuickItem, "cardRoot")
                            buttons = [item for item in items(card)
                                       if item.objectName() == "dailyTaskButton"]
                            assert len(buttons) == 2, len(buttons)
                            click(buttons[index])
                            popup = win.findChild(QQuickItem, "dailyTaskPopup")
                            assert popup.isVisible()
                            assert popup.property("dailyName") == daily_name
                            click(popup, 20, 20)  # 两个日常的首项均为“不启用”。
                            expected = [False, True, True] if index == 0 else [False, False, True]
                            assert [item["enabled"] for item in files[routine_path]["Routine Items"]] == expected
                            assert files[main_path] == native
                            rows = AppService().get_daily_items("ok-nte", definitions)
                            assert rows[index]["selection_label"] == "不启用"
                        card = win.findChild(QQuickItem, "cardRoot")
                        labels = [item.property("text") for item in items(card)]
                        assert labels.count("不启用") == 2, labels
                        assert "异象界域" in labels and "追猎目标" in labels, labels
                        assert "daily_anomaly" not in labels, labels
                        app.exit(0)
                    except Exception:
                        traceback.print_exc()
                        app.exit(1)

                QTimer.singleShot(500, verify)
                raise SystemExit(app.exec())
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=os.getcwd(),
            env={
                **os.environ,
                "QT_QPA_PLATFORM": "offscreen",
                "QML_DISABLE_DISK_CACHE": "1",
            },
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("ReferenceError", result.stderr)
        self.assertNotIn("TypeError", result.stderr)

    def test_click_and_scroll_keep_daily_identity(self):
        code = textwrap.dedent(
            """
            import traceback
            from unittest.mock import patch
            from PySide6.QtCore import QTimer, QUrl, Qt, QPointF
            from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterSingletonInstance
            from PySide6.QtQuick import QQuickItem
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication
            from src.gui.main_window import QmlBridge
            from src.gui.icons import UiIconProvider
            from src.service.app_service import AppService
            from src.utils.utils_sub_config import resolve_script_path

            app = QApplication([])
            definitions = [{'display_name': f'日常{i}', 'physical_name': f'daily_{i}', 'options': {'values': [{'display_name': f'副本{i}'}]}}
                           for i in range(8)]
            scripts = [{"display_name": "鸣潮", "script_path": "scripts/ok-ww/ok-ww.exe",
                        "script_type": "external"}]
            with (
                patch.object(AppService, "load_config", return_value={"script_list": scripts}),
                patch.object(AppService, "get_daily_map", return_value={"ok-ww": definitions}),
                patch.object(AppService, "get_weekly_map", return_value=[{"display_name": "周本", "type": "weekly"}]),
                patch("src.service.app_service.get_daily_task", return_value=(None, None)),
                patch("src.service.app_service.set_config") as write,
            ):
                bridge = QmlBridge()
                qmlRegisterSingletonInstance(QmlBridge, "OneDragonHelper", 1, 0, "Bridge", bridge)
                engine = QQmlApplicationEngine()
                engine.addImageProvider("uiicon", UiIconProvider())
                engine.load(QUrl.fromLocalFile(resolve_script_path("src/gui/qml/main.qml")))
                assert engine.rootObjects(), "QML 场景未加载"
                win = engine.rootObjects()[0]

                def items(item):
                    yield item
                    for child in item.childItems():
                        yield from items(child)

                def click(item, x=None, y=None):
                    point = item.mapToScene(QPointF(
                        item.width() / 2 if x is None else x,
                        item.height() / 2 if y is None else y))
                    QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier, point.toPoint())
                    QTest.qWait(30)

                def verify():
                    try:
                        card = win.findChild(QQuickItem, "cardRoot")
                        rows = win.findChild(QQuickItem, "taskRows")
                        popup = win.findChild(QQuickItem, "dailyTaskPopup")
                        buttons = [item for item in items(card)
                                   if item.objectName() == "dailyTaskButton"]
                        assert len(buttons) == 8, len(buttons)
                        daily_y = sorted(item.mapToItem(card, QPointF(0, 0)).y()
                                         for item in items(card) if item.property("text") == "日")
                        weekly_y = [item.mapToItem(card, QPointF(0, 0)).y()
                                    for item in items(card) if item.property("text") == "周"]
                        assert len(daily_y) == 8 and len(weekly_y) == 1
                        daily_gap = daily_y[1] - daily_y[0]
                        assert all(abs(b - a - daily_gap) < 0.01
                                   for a, b in zip(daily_y, daily_y[1:]))
                        assert abs(weekly_y[0] - daily_y[-1] - daily_gap) < 0.01, (daily_y, weekly_y)
                        assert rows.property("contentHeight") > rows.height()
                        assert card.height() <= 328
                        click(buttons[1])
                        assert popup.isVisible()
                        assert popup.property("dailyName") == "daily_1"
                        click(popup, 20, 20)
                        write.assert_called_once_with("ok-ww", daily_name="daily_1",
                                                      option_name="副本1", sequence=None)
                        rows.setProperty("contentY", rows.property("contentHeight") - rows.height())
                        QTest.qWait(30)
                        click(buttons[-1])
                        assert popup.isVisible()
                        assert popup.property("dailyName") == "daily_7"
                        click(popup, 20, 20)
                        write.assert_called_with("ok-ww", daily_name="daily_7",
                                                 option_name="副本7", sequence=None)
                        app.exit(0)
                    except Exception:
                        traceback.print_exc()
                        app.exit(1)

                QTimer.singleShot(500, verify)
                raise SystemExit(app.exec())
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=os.getcwd(),
            env={
                **os.environ,
                "QT_QPA_PLATFORM": "offscreen",
                "QML_DISABLE_DISK_CACHE": "1",
            },
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("ReferenceError", result.stderr)
        self.assertNotIn("TypeError", result.stderr)
