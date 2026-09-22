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

    def test_action_keeps_form_open_without_saving(self):
        actions = []
        saves = []
        self.dialog.actionRequested.connect(actions.append)
        self.dialog.saveRequested.connect(lambda: saves.append(True))
        for action in ("daily", "settings", "backup", "restore"):
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
                self.assertEqual(actions[-1], action)
                self.assertEqual(saves, [])
                self.assertTrue(self.dialog.isVisible())

    def test_close_leaves_no_selection(self):
        button = next(
            b for b in self.dialog.findChildren(QPushButton) if b.text() == "取消"
        )
        QTest.mouseClick(button, Qt.LeftButton)
        self.assertEqual(self.dialog.result(), QDialog.Rejected)
        self.assertFalse(self.dialog.isVisible())

    def test_escape_leaves_no_selection(self):
        QTest.keyClick(self.dialog, Qt.Key_Escape)
        self.assertEqual(self.dialog.result(), QDialog.Rejected)
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

    def test_save_submits_pending_seconds(self):
        edit = self.dialog.startup_delay.lineEdit()
        self.dialog.startup_delay.setKeyboardTracking(False)
        edit.setFocus()
        edit.selectAll()
        QTest.keyClicks(edit, "125")
        button = next(
            b for b in self.dialog.findChildren(QPushButton) if b.text() == "保存"
        )
        saves = []
        self.dialog.saveRequested.connect(
            lambda: saves.append(self.dialog.startup_options)
        )
        QTest.mouseClick(button, Qt.LeftButton)
        self.assertEqual(saves, [StartupOptions(True, 125)])
        self.assertEqual(self.dialog.startup_options, StartupOptions(True, 125))

    def test_daily_plan_suppresses_startup_controls(self):
        dialog = ConfigDialog(daily_plan=DailyPlanOptions(True, "08:30", ("A",)))
        self.addCleanup(dialog.close)
        self.assertFalse(dialog.startup_cb.isEnabled())
        self.assertFalse(dialog.startup_delay.isEnabled())
        dialog.set_daily_plan_enabled(False)
        self.assertTrue(dialog.startup_cb.isEnabled())
        self.assertTrue(dialog.startup_delay.isEnabled())


if __name__ == "__main__":
    unittest.main()
