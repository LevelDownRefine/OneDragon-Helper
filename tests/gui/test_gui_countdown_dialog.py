"""启动/关机确认共用倒计时契约；自动启动仍受用户设置约束。"""

import unittest
from types import SimpleNamespace
from unittest import mock

from PySide6.QtWidgets import QDialog, QPushButton

from src.gui.shutdown_dialog import ShutdownConfirmDialog, confirm_shutdown
from src.gui.startup_dialog import StartupConfirmDialog, confirm_startup
from src.service.daily_plan import DailyPlanOptions
from src.service.schedule import StartupOptions
from tests.gui.helpers import get_app

DIALOGS = (
    (
        "startup",
        StartupConfirmDialog,
        confirm_startup,
        "将在 {} 秒后按上次配置启动全部脚本",
        "立即启动",
    ),
    (
        "shutdown",
        ShutdownConfirmDialog,
        confirm_shutdown,
        "系统将在 {} 秒后关机",
        "立即关机",
    ),
)


class TestCountdownDialogs(unittest.TestCase):
    def setUp(self):
        self.app = get_app()

    def test_confirmation_maps_dialog_result(self):
        for name, dialog_type, confirm, _text, _button in DIALOGS:
            for code, expected in ((QDialog.Accepted, True), (QDialog.Rejected, False)):
                with (
                    self.subTest(dialog=name, result=code),
                    mock.patch.object(dialog_type, "exec", return_value=code),
                ):
                    self.assertIs(confirm(30), expected)

    def test_qt_initialization_failure_logs_and_cancels(self):
        for name, _dialog_type, confirm, _text, _button in DIALOGS:
            fake_app = mock.Mock()
            fake_app.instance.return_value = None
            fake_app.side_effect = RuntimeError("no display")
            with (
                self.subTest(dialog=name),
                mock.patch(f"src.gui.{name}_dialog.QApplication", fake_app),
                self.assertLogs(f"src.gui.{name}_dialog", level="ERROR") as logs,
            ):
                self.assertFalse(confirm(30))
            self.assertIn("RuntimeError", "\n".join(logs.output))

    def test_countdown_starts_on_show_and_accepts_only_at_zero(self):
        for name, dialog_type, _confirm, text, _button in DIALOGS:
            with self.subTest(dialog=name):
                dialog = dialog_type(2)
                self.addCleanup(dialog.close)
                self.assertEqual(dialog._label.text(), text.format(2))
                self.assertFalse(dialog._timer.isActive())
                dialog.show()
                self.assertTrue(dialog._timer.isActive())
                dialog._tick()
                self.assertEqual(dialog._remain, 1)
                self.assertEqual(dialog._label.text(), text.format(1))
                self.assertEqual(dialog.result(), QDialog.Rejected)
                dialog._tick()
                self.assertEqual(dialog.result(), QDialog.Accepted)
                self.assertFalse(dialog._timer.isActive())
                self.assertFalse(dialog.isVisible())

    def test_buttons_and_window_close_stop_countdown(self):
        for name, dialog_type, _confirm, _text, accept_button in DIALOGS:
            for button, expected in (
                (accept_button, QDialog.Accepted),
                ("取消", QDialog.Rejected),
                (None, QDialog.Rejected),
            ):
                with self.subTest(dialog=name, button=button):
                    dialog = dialog_type(45)
                    self.addCleanup(dialog.close)
                    dialog.show()
                    if button is None:
                        dialog.close()
                    else:
                        next(
                            b
                            for b in dialog.findChildren(QPushButton)
                            if b.text() == button
                        ).click()
                    self.assertEqual(dialog.result(), expected)
                    self.assertFalse(dialog._timer.isActive())
                    self.assertFalse(dialog.isVisible())


class TestAutoLaunchPreference(unittest.TestCase):
    def test_ineligible_startup_never_prompts_or_launches(self):
        from src.gui.main_window import QmlBridge

        for name, options, planned, enabled in (
            ("daily_plan", StartupOptions(), True, True),
            ("disabled", StartupOptions(False, 45), False, True),
            ("empty_selection", StartupOptions(), False, False),
        ):
            with (
                self.subTest(name=name),
                mock.patch("src.gui.startup_dialog.confirm_startup") as confirm,
            ):
                bridge = self._bridge(options)
                bridge.app_service.load_daily_plan.return_value = DailyPlanOptions(
                    planned
                )
                bridge.game_list.enabled = [enabled]
                QmlBridge.maybe_auto_launch(bridge)
                confirm.assert_not_called()
                bridge.launch.launchAll.assert_not_called()

    def _bridge(self, options):
        bridge = SimpleNamespace(
            _cli_client=None,
            game_list=SimpleNamespace(enabled=[True]),
            app_service=mock.Mock(),
            launch=mock.Mock(),
            toastRequested=mock.Mock(),
        )
        bridge.app_service.load_startup_options.return_value = options
        bridge.app_service.load_daily_plan.return_value = DailyPlanOptions()
        return bridge

    @mock.patch("src.gui.startup_dialog.confirm_startup")
    def test_configured_delay_and_confirmation_control_launch(self, confirm):
        from src.gui.main_window import QmlBridge

        for accepted in (False, True):
            with self.subTest(accepted=accepted):
                bridge = self._bridge(StartupOptions(True, 125))
                confirm.reset_mock()
                confirm.return_value = accepted
                QmlBridge.maybe_auto_launch(bridge)
                confirm.assert_called_once_with(125)
                if accepted:
                    bridge.launch.launchAll.assert_called_once_with(confirm=False)
                else:
                    bridge.launch.launchAll.assert_not_called()

    @mock.patch("src.gui.startup_dialog.confirm_startup")
    def test_read_failure_cancels_startup_and_informs_user(self, confirm):
        from src.gui.main_window import QmlBridge

        bridge = self._bridge(StartupOptions())
        bridge.app_service.load_startup_options.side_effect = OSError("locked")
        with self.assertLogs("src.gui.main_window", level="ERROR"):
            QmlBridge.maybe_auto_launch(bridge)
        confirm.assert_not_called()
        bridge.launch.launchAll.assert_not_called()
        self.assertIn("已取消自动启动", bridge.toastRequested.emit.call_args.args[0])
