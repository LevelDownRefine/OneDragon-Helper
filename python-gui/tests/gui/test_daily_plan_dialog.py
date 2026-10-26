"""每日计划的真实表单通过 CLI 保存，失败保留输入，成功回执才关闭。"""

import unittest
from dataclasses import asdict
from unittest.mock import Mock, patch

from PySide6.QtCore import Qt, QTime
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton

from gui.controllers.cli_daily_plan import CliDailyPlanController
from gui.daily_plan_dialog import DailyPlanDialog
from src.service.daily_plan import DailyPlanOptions, DailyTaskState
from src.service.schedule import RunOptions
from tests.gui.helpers import get_app
from tests.gui.rpc_test_support import RpcHarness


class TestDailyPlanDialog(unittest.TestCase):
    def setUp(self):
        get_app()
        self.plan = DailyPlanOptions(True, "08:30")
        self.state = DailyTaskState(True, True, "08:30")
        self.rpc = RpcHarness()
        self.toast = Mock()
        self.controller = CliDailyPlanController(self.rpc.session, self.toast)
        self.addCleanup(self.rpc.session.detach)

    def _run(self, action):
        dialog = DailyPlanDialog(self.plan, self.state)
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.close)
        with (
            patch(
                "gui.controllers.cli_daily_plan.DailyPlanDialog", return_value=dialog
            ),
            patch.object(dialog, "exec", side_effect=lambda: action(dialog)),
        ):
            self.controller.edit()
            self.assertEqual(self.rpc.requests[-1], ("plan.view", {}))
            self.rpc.reply(
                {
                    "plan": asdict(self.plan),
                    "state": asdict(self.state),
                    "state_error": None,
                    "supported": True,
                    "shutdown_supported": True,
                }
            )
        return dialog

    @staticmethod
    def _save_button(dialog):
        return next(
            button
            for button in dialog.findChildren(QPushButton)
            if button.text() == "保存"
        )

    def test_system_task_state_is_read_back_into_the_form(self):
        for state, expected in (
            (DailyTaskState(), "系统任务：未注册"),
            (DailyTaskState(True, False, "08:30"), "系统任务：已禁用，每天 08:30"),
            (DailyTaskState(True, True, "08:30"), "系统任务：已启用，每天 08:30"),
            (DailyTaskState(True, True, ""), "系统任务：已启用"),
        ):
            with self.subTest(state=state):
                self.state = state
                dialog = self._run(lambda _dialog: None)
                self.assertEqual(dialog.state_label.text(), expected)

    def test_edit_and_save_updates_only_after_ack(self):
        def save(dialog):
            dialog.show()
            dialog.time_edit.setTime(QTime(9, 45))
            self._save_button(dialog).click()
            self.assertTrue(dialog.isVisible())
            self.assertTrue(self.rpc.session.busy)

        dialog = self._run(save)
        updated = DailyPlanOptions(True, "09:45")
        self.assertEqual(
            self.rpc.requests[-1], ("plan.save", {"plan": asdict(updated)})
        )
        self.rpc.reply(None)
        self.assertEqual(self.controller.plan, updated)
        self.assertFalse(dialog.isVisible())
        self.toast.assert_called_once_with("每日计划已保存")

    def test_cancel_escape_and_close_do_not_save(self):
        for action in ("cancel", "escape", "close"):
            with self.subTest(action=action):

                def cancel(dialog, chosen=action):
                    dialog.show()
                    dialog.time_edit.setTime(QTime(12, 0))
                    if chosen == "cancel":
                        next(
                            button
                            for button in dialog.findChildren(QPushButton)
                            if button.text() == "取消"
                        ).click()
                    elif chosen == "escape":
                        QTest.keyClick(dialog, Qt.Key_Escape)
                    else:
                        dialog.close()

                self._run(cancel)
                self.assertTrue(
                    all(method == "plan.view" for method, _ in self.rpc.requests)
                )
                self.toast.assert_not_called()

    def test_save_failure_preserves_input_and_allows_retry(self):
        def save(dialog):
            dialog.show()
            dialog.time_edit.setTime(QTime(9, 45))
            button = self._save_button(dialog)
            button.click()
            self.rpc.fail("denied")
            self.assertTrue(dialog.isVisible())
            self.assertIn("denied", dialog.error_label.text())
            self.assertEqual(dialog.daily_plan.target_time, "09:45")
            self.toast.assert_not_called()
            button.click()
            self.rpc.reply(None)
            self.assertFalse(dialog.isVisible())

        self._run(save)
        self.assertEqual(
            [method for method, _ in self.rpc.requests],
            ["plan.view", "plan.save", "plan.save"],
        )

    def test_run_options_are_edited_and_saved(self):
        def save(dialog):
            dialog.editor.mute_cb.setChecked(True)
            dialog.editor.shutdown_cb.setChecked(True)
            dialog.editor.shutdown_delay_spin.setValue(60)
            dialog.editor.notify_cb.setChecked(True)
            dialog.editor.email_edit.setText("a@example.com")
            self._save_button(dialog).click()

        self._run(save)
        submitted = self.rpc.requests[-1][1]["plan"]
        self.assertEqual(
            submitted["run_options"],
            asdict(
                RunOptions(
                    mute_enabled=True,
                    shutdown_enabled=True,
                    shutdown_delay=60,
                    notify_enabled=True,
                    email="a@example.com",
                    smtp_host="smtp.qq.com",
                    smtp_port="465",
                )
            ),
        )
        self.rpc.reply(None)

    def test_pause_and_resume_preserve_time(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled):

                def save(dialog, checked=enabled):
                    dialog.enabled_cb.setChecked(checked)
                    self._save_button(dialog).click()

                self._run(save)
                self.plan = DailyPlanOptions(enabled, "08:30")
                self.assertEqual(
                    self.rpc.requests[-1], ("plan.save", {"plan": asdict(self.plan)})
                )
                self.rpc.reply(None)
                self.assertEqual(self.controller.plan, self.plan)
