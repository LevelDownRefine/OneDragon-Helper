"""每日计划：真实表单保存、取消、错误保留与暂停恢复。"""

import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QTime  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from src.gui.controllers.daily_plan import DailyPlanController  # noqa: E402
from src.gui.daily_plan_dialog import DailyPlanDialog  # noqa: E402
from src.service.daily_plan import DailyPlanOptions, DailyTaskState  # noqa: E402

_APP = QApplication.instance() or QApplication([])


class TestDailyPlanDialog(unittest.TestCase):
    def setUp(self):
        self.plan = DailyPlanOptions(True, "08:30")
        self.service = Mock()
        self.service.load_daily_plan.return_value = self.plan
        self.service.read_daily_task_state.return_value = DailyTaskState(
            True, True, "08:30"
        )
        self.toast = Mock()
        self.controller = DailyPlanController(self.service, self.toast)

    def _run(self, action):
        dialog = DailyPlanDialog(
            self.plan,
            self.service.read_daily_task_state(),
        )
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.close)
        with (
            patch(
                "src.gui.controllers.daily_plan.DailyPlanDialog", return_value=dialog
            ),
            patch.object(dialog, "exec", side_effect=lambda: action(dialog)),
        ):
            self.controller.edit()
        return dialog

    def test_system_task_state_is_read_back_into_the_form(self):
        for state, expected in (
            (DailyTaskState(), "系统任务：未注册"),
            (DailyTaskState(True, False, "08:30"), "系统任务：已禁用，每天 08:30"),
            (DailyTaskState(True, True, "08:30"), "系统任务：已启用，每天 08:30"),
            (DailyTaskState(True, True, ""), "系统任务：已启用"),
        ):
            with self.subTest(state=state):
                self.service.read_daily_task_state.return_value = state
                dialog = self._run(lambda _dialog: None)
                self.assertEqual(dialog.state_label.text(), expected)
        self.service.read_daily_task_state.assert_called()

    def test_edit_and_save_updates_time_and_enabled(self):
        updated = DailyPlanOptions(True, "09:45")
        self.service.apply_daily_plan.side_effect = lambda value: setattr(
            self.service.load_daily_plan, "return_value", value
        )

        def save(dialog):
            self.assertEqual(dialog.daily_plan, self.plan)
            dialog.enabled_cb.setChecked(True)
            dialog.time_edit.setTime(QTime(9, 45))
            next(
                b for b in dialog.findChildren(QPushButton) if b.text() == "保存"
            ).click()

        self._run(save)
        self.service.apply_daily_plan.assert_called_once_with(updated)
        self.assertEqual(self.controller.plan, updated)

    def test_cancel_escape_and_close_do_not_save(self):
        for action in ("cancel", "escape", "close"):
            with self.subTest(action=action):

                def cancel(dialog, chosen=action):
                    dialog.show()
                    dialog.time_edit.setTime(QTime(12, 0))
                    if chosen == "cancel":
                        next(
                            b
                            for b in dialog.findChildren(QPushButton)
                            if b.text() == "取消"
                        ).click()
                    elif chosen == "escape":
                        QTest.keyClick(dialog, Qt.Key_Escape)
                    else:
                        dialog.close()

                self._run(cancel)
                self.service.apply_daily_plan.assert_not_called()
                self.toast.assert_not_called()

    def test_save_failure_preserves_input_and_allows_retry(self):
        self.service.apply_daily_plan.side_effect = [OSError("denied"), None]

        def save(dialog):
            dialog.show()
            dialog.time_edit.setTime(QTime(9, 45))
            button = next(
                b for b in dialog.findChildren(QPushButton) if b.text() == "保存"
            )
            with self.assertLogs("src.gui.controllers.daily_plan", level="ERROR"):
                button.click()
            self.assertTrue(dialog.isVisible())
            self.assertIn("denied", dialog.error_label.text())
            self.assertEqual(dialog.daily_plan.target_time, "09:45")
            self.toast.assert_not_called()
            button.click()
            self.assertFalse(dialog.isVisible())

        self._run(save)
        self.assertEqual(self.service.apply_daily_plan.call_count, 2)

    def test_pause_and_resume_preserve_time(self):
        self.service.apply_daily_plan.side_effect = lambda value: setattr(
            self.service.load_daily_plan, "return_value", value
        )
        for enabled in (False, True):
            with self.subTest(enabled=enabled):

                def save(dialog, checked=enabled):
                    dialog.enabled_cb.setChecked(checked)
                    next(
                        b
                        for b in dialog.findChildren(QPushButton)
                        if b.text() == "保存"
                    ).click()

                self._run(save)
                self.plan = DailyPlanOptions(enabled, "08:30")
                self.assertEqual(self.service.load_daily_plan(), self.plan)
                self.assertEqual(self.controller.plan, self.plan)
