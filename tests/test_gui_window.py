"""测试 src/gui/controllers/window.py：悬浮条窗口控制的判空守卫。

focusWindow() 在窗口未获焦点/早期可返回 None，直接链式调用会 AttributeError。
"""

import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QWindow
from PySide6.QtWidgets import QApplication

from src.gui.controllers.window import WindowController

_app = QApplication.instance() or QApplication([])


class TestWindowController(unittest.TestCase):
    def test_rounded_window_mask_tracks_resize(self):
        window = QWindow()
        window.resize(1280, 720)
        ctrl = WindowController()
        ctrl.roundWindow(window, 16)

        for width, height in ((1280, 720), (960, 600)):
            with self.subTest(size=(width, height)):
                window.resize(width, height)
                mask = window.mask()
                self.assertEqual(mask.boundingRect(), QRect(0, 0, width, height))
                for x, y in (
                    (0, 0),
                    (width - 1, 0),
                    (0, height - 1),
                    (width - 1, height - 1),
                ):
                    self.assertFalse(mask.contains(QPoint(x, y)))
                self.assertTrue(mask.contains(QPoint(16, 0)))
                self.assertTrue(mask.contains(QPoint(0, 16)))
                self.assertTrue(mask.contains(QPoint(width // 2, height // 2)))

    def test_minimize_with_no_focused_window_does_not_raise(self):
        """focusWindow() 返回 None：判空后直接返回，不 AttributeError。"""
        ctrl = WindowController()
        app = MagicMock()
        app.focusWindow.return_value = None
        with patch("PySide6.QtWidgets.QApplication.instance", return_value=app):
            ctrl.minimize()  # 不应抛出
        app.focusWindow.assert_called_once()


if __name__ == "__main__":
    unittest.main()
