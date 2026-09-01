"""测试 src/utils_shutdown.py：关机命令编排与确认分支（纯逻辑，不加载 Qt）。

确认窗的 GUI 实现位于 ``src/gui/shutdown_dialog.py``，其测试见
``test_gui_shutdown_dialog.py``；本文件只测「确认后执行 shutdown」的编排逻辑。
"""

import sys
import unittest
from unittest import mock

from src.utils_shutdown import _run_shutdown_command, shutdown_sys


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


if __name__ == "__main__":
    unittest.main()
