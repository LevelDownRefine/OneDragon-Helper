"""布局参数改动须同时作用于窗口裁切、菜单边界和点击区域。"""

import os
import subprocess
import sys
import textwrap
import unittest


class TestSharedLayout(unittest.TestCase):
    def test_window_and_popup_follow_layout_parameters(self):
        code = textwrap.dedent(
            """
            import os
            import shutil
            import tempfile
            from pathlib import Path
            from unittest.mock import patch

            os.environ["QT_QPA_PLATFORM"] = "offscreen"
            os.environ["QML_DISABLE_DISK_CACHE"] = "1"
            from PySide6.QtCore import QPoint, QPointF, Qt, QUrl
            from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterSingletonInstance
            from PySide6.QtQuick import QQuickItem
            from PySide6.QtTest import QTest
            from src.gui.icons import UiIconProvider
            from src.gui.main_window import QmlBridge
            from src.utils.utils_sub_config import resolve_script_path
            from tests.gui.helpers import make_bridge

            with tempfile.TemporaryDirectory() as directory:
                qml_dir = Path(directory) / "qml"
                shutil.copytree(resolve_script_path("src/gui/qml"), qml_dir)
                layout_path = qml_dir / "Layout.js"
                layout = layout_path.read_text(encoding="utf-8")
                for old, new in (
                    ("windowWidth = 1280", "windowWidth = 1120"),
                    ("windowHeight = 720", "windowHeight = 640"),
                    ("windowCornerRadius = 16", "windowCornerRadius = 28"),
                    ("taskCardX = 128", "taskCardX = 176"),
                    ("taskCardY = 392", "taskCardY = 304"),
                    ("popupAnchorGap = 4", "popupAnchorGap = 6"),
                    ("popupEdgeMargin = 8", "popupEdgeMargin = 12"),
                ):
                    assert layout.count(old) == 1, old
                    layout = layout.replace(old, new)
                layout_path.write_text(layout, encoding="utf-8")
                weekly = [{"display_name": "周常", "options": {"values": [
                    {"display_name": f"副本{i}", "physical_name": f"副本{i}"}
                    for i in range(30)
                ]}}]
                with (
                    patch("src.service.app_service.get_daily_map", return_value={}),
                    patch("src.service.app_service.get_weekly_map", return_value=weekly),
                    patch("src.gui.controllers.task_card.get_daily_readback", return_value=[]),
                    patch("src.gui.controllers.task_card.get_weekly_task", return_value=None),
                ):
                    bridge = make_bridge()
                    qmlRegisterSingletonInstance(
                        QmlBridge, "OneDragonHelper", 1, 0, "Bridge", bridge)
                    engine = QQmlApplicationEngine()
                    engine.addImageProvider("uiicon", UiIconProvider())
                    engine.addImageProvider("scripticon", bridge.game_list.icon_provider)
                    engine.load(QUrl.fromLocalFile(str(qml_dir / "main.qml")))
                    assert len(engine.rootObjects()) == 1
                    window = engine.rootObjects()[0]
                    QTest.qWait(600)
                    assert (window.width(), window.height()) == (1120, 640)
                    # 整窗圆角已改由 QML 遮罩承担（QRegion 遮罩是二值区域、必现锯齿），
                    # Layout 里的 windowCornerRadius 须作用到遮罩半径与尺寸上。
                    corner = window.findChild(QQuickItem, "cornerMask")
                    assert window.mask().isEmpty()
                    assert float(corner.property("radius")) == 28
                    assert (corner.width(), corner.height()) == (1120, 640)
                    card = window.findChild(QQuickItem, "cardRoot")
                    assert card.mapToScene(QPointF()) == QPointF(176, 304)
                    catcher = window.findChild(QQuickItem, "popupCatcher")
                    assert catcher.mapToScene(QPointF()) == QPointF(0, 0)
                    assert (catcher.width(), catcher.height()) == (1120, 640)
                    popup = window.findChild(QQuickItem, "weeklyPopup")
                    popup.setProperty("weeklyName", "周常")
                    popup.setProperty("anchorTop", 60)
                    popup.setProperty("anchorBottom", 116)
                    popup.setProperty("visible", True)
                    QTest.qWait(100)
                    # 长列表在上方空间内封顶：距窗口上沿 12，距锚点 6。
                    top = popup.mapToScene(QPointF()).y()
                    assert top == 12, top
                    assert top + popup.height() == 304 + 60 - 6
                    QTest.mouseClick(window, Qt.LeftButton, pos=QPoint(32, 32))
                    assert not popup.isVisible()
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=os.getcwd(),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for error in ("ReferenceError", "TypeError", "Binding loop"):
            self.assertNotIn(error, result.stderr)
