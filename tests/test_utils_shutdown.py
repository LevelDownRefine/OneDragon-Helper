"""测试 src/utils_shutdown.py：关机确认窗（PySide6）与关机/取消命令。"""

import subprocess
import sys
import unittest
from unittest import mock


class TestShutdownSys(unittest.TestCase):
    """shutdown_sys：非 Windows 跳过，Windows 下按确认结果决定是否关机。"""

    def test_non_windows_skips(self):
        with (
            mock.patch.object(sys, "platform", "linux"),
            mock.patch("src.utils_shutdown.subprocess.run") as mock_run,
        ):
            from src.utils_shutdown import shutdown_sys

            shutdown_sys(60)
            mock_run.assert_not_called()

    def test_windows_confirm_triggers_shutdown(self):
        with (
            mock.patch.object(sys, "platform", "win32"),
            mock.patch("src.utils_shutdown._run_shutdown_confirm", return_value=True),
            mock.patch("src.utils_shutdown.subprocess.run") as mock_run,
        ):
            from src.utils_shutdown import shutdown_sys

            shutdown_sys(60)
            mock_run.assert_called_once_with(
                ["shutdown", "/s", "/f", "/t", "0"],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )

    def test_windows_cancel_skips_shutdown(self):
        with (
            mock.patch.object(sys, "platform", "win32"),
            mock.patch("src.utils_shutdown._run_shutdown_confirm", return_value=False),
            mock.patch("src.utils_shutdown.subprocess.run") as mock_run,
        ):
            from src.utils_shutdown import shutdown_sys

            shutdown_sys(60)
            mock_run.assert_not_called()


class TestCancelShutdownSys(unittest.TestCase):
    """cancel_shutdown_sys：调用 shutdown /a。"""

    def test_calls_shutdown_a(self):
        with mock.patch("src.utils_shutdown.subprocess.run") as mock_run:
            from src.utils_shutdown import cancel_shutdown_sys

            cancel_shutdown_sys()
            mock_run.assert_called_once_with(
                ["shutdown", "/a"],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )


class TestRunShutdownConfirm(unittest.TestCase):
    """_run_shutdown_confirm：PySide6 不可用时降级直接关机。"""

    def test_pyside6_not_available_returns_true(self):
        with (
            mock.patch.dict("sys.modules", {"PySide6": None, "PySide6.QtWidgets": None}),
            mock.patch("src.utils_shutdown.logger") as mock_logger,
        ):
            from src.utils_shutdown import _run_shutdown_confirm

            result = _run_shutdown_confirm(60)
            self.assertTrue(result)
            mock_logger.warning.assert_called_once()


if __name__ == "__main__":
    unittest.main()
