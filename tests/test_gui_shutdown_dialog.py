"""测试 src/gui/shutdown_dialog.py：关机确认窗与 Qt 失败降级。

确认窗为进程内 PySide6 弹窗，UI 测试在 offscreen 平台下运行（CI 无显示器）。
GUI 实现自 ``src.utils_shutdown`` 归位而来（纯逻辑测试见 test_utils_shutdown.py）。
"""

import os
import unittest
from unittest import mock

# 在导入 PySide6 之前设置 offscreen 平台插件（CI 无显示器环境）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QPushButton

from src.gui.shutdown_dialog import ShutdownConfirmDialog, confirm_shutdown

# 模块级 QApplication 单例：widget 需要 GUI 应用，进程退出时随解释器销毁。
if QApplication.instance() is None:
    _APP = QApplication([])


def _button(dialog: QDialog, text: str) -> QPushButton:
    """按文字取弹窗按钮（按钮由 FormDialogBase._make_footer 构造，无公开引用）。"""
    return next(b for b in dialog.findChildren(QPushButton) if b.text() == text)


class TestConfirmShutdown(unittest.TestCase):
    """confirm_shutdown：弹窗结果映射与 Qt 初始化失败的降级。"""

    def test_accepted_returns_true(self):
        with mock.patch.object(
            ShutdownConfirmDialog,
            "exec",
            return_value=QDialog.DialogCode.Accepted,
        ):
            self.assertTrue(confirm_shutdown(30))

    def test_rejected_returns_false(self):
        with mock.patch.object(
            ShutdownConfirmDialog,
            "exec",
            return_value=QDialog.DialogCode.Rejected,
        ):
            self.assertFalse(confirm_shutdown(30))

    def test_qt_init_failure_returns_false(self):
        """Qt 初始化失败（无桌面）：记诊断并按取消处理，不静默吞掉。

        ``QApplication.instance()`` 返回 None 才会走到创建分支，故 Mock 需让
        ``instance`` 返回 None、构造调用抛 RuntimeError，与真实无桌面环境一致。
        """
        fake_app = mock.Mock()
        fake_app.instance.return_value = None
        fake_app.side_effect = RuntimeError("no display")
        with (
            mock.patch("src.gui.shutdown_dialog.QApplication", fake_app),
            self.assertLogs("src.gui.shutdown_dialog", level="ERROR") as logs,
        ):
            self.assertFalse(confirm_shutdown(30))
        self.assertIn("RuntimeError", "\n".join(logs.output))


class TestShutdownConfirmDialog(unittest.TestCase):
    """ShutdownConfirmDialog：倒计时文案 / 归零接受 / 按钮与定时器生命周期。"""

    def test_initial_label_shows_countdown(self):
        dlg = ShutdownConfirmDialog(45)
        self.assertEqual(dlg._label.text(), "系统将在 45 秒后关机")

    def test_tick_decrements(self):
        dlg = ShutdownConfirmDialog(45)
        dlg._tick()
        self.assertEqual(dlg._remain, 44)
        self.assertEqual(dlg._label.text(), "系统将在 44 秒后关机")

    def test_tick_to_zero_accepts(self):
        """倒计时归零即接受（关机），并停表。"""
        dlg = ShutdownConfirmDialog(2)
        dlg.show()
        dlg._tick()
        self.assertEqual(dlg.result(), QDialog.DialogCode.Rejected)  # 未归零：尚未接受
        dlg._tick()
        self.assertEqual(dlg.result(), QDialog.DialogCode.Accepted)
        self.assertFalse(dlg._timer.isActive())
        dlg.close()

    def test_confirm_button_accepts(self):
        dlg = ShutdownConfirmDialog(45)
        _button(dlg, "立即关机").click()
        self.assertEqual(dlg.result(), QDialog.DialogCode.Accepted)

    def test_cancel_button_rejects(self):
        dlg = ShutdownConfirmDialog(45)
        _button(dlg, "取消").click()
        self.assertEqual(dlg.result(), QDialog.DialogCode.Rejected)

    def test_timer_starts_on_show_and_stops_on_hide(self):
        """显示才起倒计时（模态 exec 前不流逝），关闭即停表。"""
        dlg = ShutdownConfirmDialog(45)
        self.assertFalse(dlg._timer.isActive())
        dlg.show()
        self.assertTrue(dlg._timer.isActive())
        dlg.close()
        self.assertFalse(dlg._timer.isActive())


if __name__ == "__main__":
    unittest.main()
