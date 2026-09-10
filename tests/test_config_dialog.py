"""配置弹窗：点选操作后关闭，取消不选择操作。"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton  # noqa: E402

from src.gui.config_dialog import ConfigDialog  # noqa: E402
from src.service.daily_plan import DailyPlanOptions  # noqa: E402
from src.service.schedule import StartupOptions  # noqa: E402

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
        for action in ("settings", "backup", "restore"):
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

    def test_reopens_saved_preferences_and_toggle_preserves_delay(self):
        dialog = ConfigDialog(startup_options=StartupOptions(False, 125))
        self.addCleanup(dialog.close)
        self.assertFalse(dialog.startup_cb.isChecked())
        self.assertFalse(dialog.startup_delay.isEnabled())
        self.assertEqual(dialog.startup_delay.value(), 125)
        dialog.startup_cb.click()
        self.assertTrue(dialog.startup_delay.isEnabled())
        self.assertEqual(dialog.startup_options, StartupOptions(True, 125))

    def test_escape_keeps_pending_seconds_for_save(self):
        edit = self.dialog.startup_delay.lineEdit()
        self.dialog.startup_delay.setKeyboardTracking(False)
        edit.setFocus()
        edit.selectAll()
        QTest.keyClicks(edit, "125")
        QTest.keyClick(edit, Qt.Key_Escape)
        self.assertFalse(self.dialog.isVisible())
        self.assertEqual(self.dialog.startup_options, StartupOptions(True, 125))

    def test_daily_plan_echoes_time_and_suppresses_startup_controls(self):
        dialog = ConfigDialog(daily_plan=DailyPlanOptions(True, "08:30"))
        self.addCleanup(dialog.close)
        self.assertEqual(dialog.daily_plan, DailyPlanOptions(True, "08:30"))
        self.assertTrue(dialog.daily_time.isEnabled())
        self.assertFalse(dialog.startup_cb.isEnabled())
        self.assertFalse(dialog.startup_delay.isEnabled())
        dialog.daily_cb.click()
        self.assertEqual(dialog.daily_plan, DailyPlanOptions(False, "08:30"))
        self.assertFalse(dialog.daily_time.isEnabled())
        self.assertTrue(dialog.startup_cb.isEnabled())
        self.assertTrue(dialog.startup_delay.isEnabled())


if __name__ == "__main__":
    unittest.main()
