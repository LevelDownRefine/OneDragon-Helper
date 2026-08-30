"""测试 src/utils_shutdown.py：关机确认窗与 shutdown 命令编排。

确认窗为进程内 PySide6 弹窗，UI 测试在 offscreen 平台下运行（CI 无显示器）。
"""

import os
import sys
import unittest
from unittest import mock

# 在导入 PySide6 之前设置 offscreen 平台插件（CI 无显示器环境）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QPushButton

from src.utils_shutdown import (
    ShutdownConfirmDialog,
    _confirm_shutdown,
    _run_shutdown_command,
    shutdown_sys,
)

# 模块级 QApplication 单例：widget 需要 GUI 应用，进程退出时随解释器销毁。
if QApplication.instance() is None:
    _APP = QApplication([])


def _button(dialog: QDialog, text: str) -> QPushButton:
    """按文字取弹窗按钮（按钮由 FormDialogBase._make_footer 构造，无公开引用）。"""
    return next(b for b in dialog.findChildren(QPushButton) if b.text() == text)


class TestShutdownSys(unittest.TestCase):
    """shutdown_sys：确认才关、取消不关、非 Windows 跳过。"""

    def test_non_windows_skips(self):
        """非 Windows：不弹窗、不执行 shutdown。"""
        with (
            mock.patch.object(sys, "platform", "linux"),
            mock.patch("src.utils_shutdown.subprocess.run") as run,
            mock.patch("src.utils_shutdown._confirm_shutdown") as confirm,
        ):
            shutdown_sys(45)
        confirm.assert_not_called()
        run.assert_not_called()

    def test_confirmed_shuts_down(self):
        """确认：执行 shutdown /s /f /t 0。"""
        with (
            mock.patch.object(sys, "platform", "win32"),
            mock.patch("src.utils_shutdown._confirm_shutdown", return_value=True),
            mock.patch("src.utils_shutdown.subprocess.run") as run,
        ):
            shutdown_sys(45)
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], ["shutdown", "/s", "/f", "/t", "0"])

    def test_cancelled_no_shutdown(self):
        """取消：不执行 shutdown 并记「已取消关机」。"""
        with (
            mock.patch.object(sys, "platform", "win32"),
            mock.patch("src.utils_shutdown._confirm_shutdown", return_value=False),
            mock.patch("src.utils_shutdown.subprocess.run") as run,
            self.assertLogs("src.utils_shutdown", level="INFO") as logs,
        ):
            shutdown_sys(45)
        run.assert_not_called()
        self.assertIn("已取消关机", "\n".join(logs.output))


class TestRunShutdownCommand(unittest.TestCase):
    """_run_shutdown_command：命令拼装与失败留痕。"""

    def test_command_and_flags(self):
        """命令名 + 参数拼装，且不弹额外控制台窗口。"""
        with mock.patch("src.utils_shutdown.subprocess.run") as run:
            _run_shutdown_command(["/a"])
        self.assertEqual(run.call_args.args[0], ["shutdown", "/a"])
        self.assertIsNotNone(run.call_args.kwargs["creationflags"])

    def test_nonzero_exit_logs_error(self):
        """非 0 退出码记 error（不抛，避免打断 post_run 后续步骤）。"""
        failed = mock.Mock(returncode=1, stderr="拒绝访问")
        with (
            mock.patch("src.utils_shutdown.subprocess.run", return_value=failed),
            self.assertLogs("src.utils_shutdown", level="ERROR") as logs,
        ):
            _run_shutdown_command(["/s"])
        self.assertIn("拒绝访问", "\n".join(logs.output))


class TestConfirmShutdown(unittest.TestCase):
    """_confirm_shutdown：弹窗结果映射与 Qt 初始化失败的降级。"""

    def test_accepted_returns_true(self):
        with mock.patch.object(
            ShutdownConfirmDialog,
            "exec",
            return_value=QDialog.DialogCode.Accepted,
        ):
            self.assertTrue(_confirm_shutdown(30))

    def test_rejected_returns_false(self):
        with mock.patch.object(
            ShutdownConfirmDialog,
            "exec",
            return_value=QDialog.DialogCode.Rejected,
        ):
            self.assertFalse(_confirm_shutdown(30))

    def test_qt_init_failure_returns_false(self):
        """Qt 初始化失败（无桌面）：记诊断并按取消处理，不静默吞掉。

        ``QApplication.instance()`` 返回 None 才会走到创建分支，故 Mock 需让
        ``instance`` 返回 None、构造调用抛 RuntimeError，与真实无桌面环境一致。
        """
        fake_app = mock.Mock()
        fake_app.instance.return_value = None
        fake_app.side_effect = RuntimeError("no display")
        with (
            mock.patch("src.utils_shutdown.QApplication", fake_app),
            self.assertLogs("src.utils_shutdown", level="ERROR") as logs,
        ):
            self.assertFalse(_confirm_shutdown(30))
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
