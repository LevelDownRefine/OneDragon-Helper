"""配置弹窗：点选操作后关闭，取消不选择操作。"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton  # noqa: E402

from src.gui.config_dialog import ConfigDialog  # noqa: E402

_APP = QApplication.instance() or QApplication([])


class TestConfigDialog(unittest.TestCase):
    def setUp(self):
        self.dialog = ConfigDialog()
        self.dialog.show()
        _APP.processEvents()

    def tearDown(self):
        self.dialog.close()
        self.dialog.deleteLater()

    def test_click_action_label_accepts_and_returns_selection(self):
        for action in ("backup", "restore"):
            with self.subTest(action=action):
                self.dialog.show()
                button = self.dialog.findChild(QPushButton, f"{action}Action")
                self.assertIsNotNone(button)
                label = next(
                    line for line in button.findChildren(QLabel) if line.text()
                )
                # 按钮内的文字也是可点击区域。
                position = label.mapTo(self.dialog, label.rect().center())
                QTest.mouseClick(
                    self.dialog.windowHandle(), Qt.LeftButton, pos=position
                )
                self.assertEqual(self.dialog.result(), QDialog.Accepted)
                self.assertEqual(self.dialog.selected_action, action)
                self.assertFalse(self.dialog.isVisible())

    def test_close_leaves_no_selection(self):
        button = self.dialog.findChild(QPushButton, "closeConfig")
        QTest.mouseClick(button, Qt.LeftButton)
        self.assertEqual(self.dialog.result(), QDialog.Rejected)
        self.assertIsNone(self.dialog.selected_action)
        self.assertFalse(self.dialog.isVisible())

    def test_escape_leaves_no_selection(self):
        QTest.keyClick(self.dialog, Qt.Key_Escape)
        self.assertEqual(self.dialog.result(), QDialog.Rejected)
        self.assertIsNone(self.dialog.selected_action)
        self.assertFalse(self.dialog.isVisible())


if __name__ == "__main__":
    unittest.main()
