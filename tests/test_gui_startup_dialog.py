"""测试 src/gui/startup_dialog.py：启动确认窗与 Qt 失败降级。

启动确认窗与关机窗共用 ``CountdownConfirmDialogBase``（文案不同），
此处钉死子类的打开动作文案 / 倒计时模板与结果映射。
"""

import os
import unittest
from types import SimpleNamespace
from unittest import mock

# 在导入 PySide6 之前设置 offscreen 平台插件（CI 无显示器环境）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QPushButton

from src.gui.startup_dialog import StartupConfirmDialog, confirm_startup
from src.service.schedule import StartupOptions

# 模块级 QApplication 单例：widget 需要 GUI 应用，进程退出时随解释器销毁。
if QApplication.instance() is None:
    _APP = QApplication([])


def _button(dialog: QDialog, text: str) -> QPushButton:
    """按文字取弹窗按钮（按钮由 FormDialogBase._make_footer 构造，无公开引用）。"""
    return next(b for b in dialog.findChildren(QPushButton) if b.text() == text)


class TestConfirmStartup(unittest.TestCase):
    """confirm_startup：弹窗结果映射与 Qt 初始化失败的降级。"""

    def test_accepted_returns_true(self):
        with mock.patch.object(
            StartupConfirmDialog,
            "exec",
            return_value=QDialog.DialogCode.Accepted,
        ):
            self.assertTrue(confirm_startup(30))

    def test_rejected_returns_false(self):
        with mock.patch.object(
            StartupConfirmDialog,
            "exec",
            return_value=QDialog.DialogCode.Rejected,
        ):
            self.assertFalse(confirm_startup(30))

    def test_qt_init_failure_returns_false(self):
        """Qt 初始化失败（无桌面）：记诊断并按取消处理，不静默吞掉。"""
        fake_app = mock.Mock()
        fake_app.instance.return_value = None
        fake_app.side_effect = RuntimeError("no display")
        with (
            mock.patch("src.gui.startup_dialog.QApplication", fake_app),
            self.assertLogs("src.gui.startup_dialog", level="ERROR") as logs,
        ):
            self.assertFalse(confirm_startup(30))
        self.assertIn("RuntimeError", "\n".join(logs.output))


class TestStartupConfirmDialog(unittest.TestCase):
    """StartupConfirmDialog：倒计时文案 / 归零接受 / 按钮与定时器生命周期。"""

    def test_initial_label_shows_countdown(self):
        dlg = StartupConfirmDialog(45)
        self.assertEqual(dlg._label.text(), "将在 45 秒后按上次配置启动全部脚本")

    def test_tick_decrements(self):
        dlg = StartupConfirmDialog(45)
        dlg._tick()
        self.assertEqual(dlg._remain, 44)
        self.assertEqual(dlg._label.text(), "将在 44 秒后按上次配置启动全部脚本")

    def test_tick_to_zero_accepts(self):
        """倒计时归零即接受（启动），并停表。"""
        dlg = StartupConfirmDialog(2)
        dlg.show()
        dlg._tick()
        self.assertEqual(dlg.result(), QDialog.DialogCode.Rejected)  # 未归零：尚未接受
        dlg._tick()
        self.assertEqual(dlg.result(), QDialog.DialogCode.Accepted)
        self.assertFalse(dlg._timer.isActive())
        dlg.close()

    def test_confirm_button_accepts(self):
        dlg = StartupConfirmDialog(45)
        _button(dlg, "立即启动").click()
        self.assertEqual(dlg.result(), QDialog.DialogCode.Accepted)

    def test_cancel_button_rejects(self):
        dlg = StartupConfirmDialog(45)
        _button(dlg, "取消").click()
        self.assertEqual(dlg.result(), QDialog.DialogCode.Rejected)

    def test_timer_starts_on_show_and_stops_on_hide(self):
        """显示才起倒计时（模态 exec 前不流逝），关闭即停表。"""
        dlg = StartupConfirmDialog(45)
        self.assertFalse(dlg._timer.isActive())
        dlg.show()
        self.assertTrue(dlg._timer.isActive())
        dlg.close()
        self.assertFalse(dlg._timer.isActive())


class TestAutoLaunchPreference(unittest.TestCase):
    def _bridge(self, options):
        bridge = SimpleNamespace(
            game_list=SimpleNamespace(enabled=[True]),
            app_service=mock.Mock(),
            launch=mock.Mock(),
            toastRequested=mock.Mock(),
        )
        bridge.app_service.load_startup_options.return_value = options
        return bridge

    @mock.patch("src.gui.startup_dialog.confirm_startup")
    def test_disabled_never_prompts_or_launches(self, confirm):
        from src.gui.main_window import QmlBridge

        bridge = self._bridge(StartupOptions(False, 45))
        QmlBridge.maybe_auto_launch(bridge)
        confirm.assert_not_called()
        bridge.launch.launchAll.assert_not_called()

    @mock.patch("src.gui.startup_dialog.confirm_startup")
    def test_no_enabled_scripts_never_prompts(self, confirm):
        from src.gui.main_window import QmlBridge

        bridge = self._bridge(StartupOptions())
        bridge.game_list.enabled = [False]
        QmlBridge.maybe_auto_launch(bridge)
        confirm.assert_not_called()
        bridge.launch.launchAll.assert_not_called()

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


if __name__ == "__main__":
    unittest.main()
