"""测试 src/utils_shutdown.py：关机命令编排与确认分支（纯逻辑，不加载 Qt）。

确认窗由前端注册；本文件只测确认协议与「确认后执行 shutdown」的编排逻辑。
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.utils import utils_shutdown
from src.utils.utils_shutdown import _run_shutdown_command, shutdown_sys


class RustShutdownTests(unittest.TestCase):
    def test_explicit_frontend_accepts_only_confirmation_code(self):
        with tempfile.TemporaryDirectory() as temporary:
            frontend = Path(temporary) / "前端 gui.exe"
            frontend.touch()
            with (
                mock.patch.object(sys, "platform", "win32"),
                mock.patch.dict(
                    os.environ, {utils_shutdown.SHUTDOWN_UI_ENV: str(frontend)}
                ),
            ):
                for code in (42, 0, 2, -1):
                    with (
                        self.subTest(code=code),
                        mock.patch.object(
                            utils_shutdown.subprocess,
                            "run",
                            return_value=mock.Mock(returncode=code),
                        ) as run,
                    ):
                        self.assertEqual(
                            utils_shutdown._confirm_shutdown(45), code == 42
                        )
                        self.assertEqual(
                            run.call_args.args[0],
                            [str(frontend), "--shutdown-confirm", "45"],
                        )
                        self.assertEqual(run.call_args.kwargs["timeout"], 165)

    def test_missing_timeout_and_start_failure_cancel_without_qt_fallback(self):
        with (
            mock.patch.dict(
                os.environ, {utils_shutdown.SHUTDOWN_UI_ENV: "missing.exe"}
            ),
            mock.patch.object(utils_shutdown.subprocess, "run") as run,
        ):
            self.assertFalse(utils_shutdown._confirm_shutdown(45))
            run.assert_not_called()
        for error in (OSError("cannot start"), subprocess.TimeoutExpired("test", 1)):
            with (
                self.subTest(error=type(error).__name__),
                mock.patch.dict(os.environ, {utils_shutdown.SHUTDOWN_UI_ENV: "fake"}),
                mock.patch.object(
                    utils_shutdown, "shutdown_ui_supported", return_value=True
                ),
                mock.patch.object(utils_shutdown.subprocess, "run", side_effect=error),
                self.assertLogs("src.utils.utils_shutdown", level="ERROR") as logs,
            ):
                self.assertFalse(utils_shutdown._confirm_shutdown(45))
            self.assertIn(type(error).__name__, " ".join(logs.output))

    def test_registered_python_frontend_handles_confirmation(self):
        confirm = mock.Mock(return_value=True)
        self.addCleanup(utils_shutdown.set_shutdown_confirmation, None)
        utils_shutdown.set_shutdown_confirmation(confirm)
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertTrue(utils_shutdown._confirm_shutdown(45))
        confirm.assert_called_once_with(45)

    def test_missing_python_frontend_cancels(self):
        self.addCleanup(utils_shutdown.set_shutdown_confirmation, None)
        utils_shutdown.set_shutdown_confirmation(None)
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            self.assertLogs("src.utils.utils_shutdown", level="ERROR") as logs,
        ):
            self.assertFalse(utils_shutdown._confirm_shutdown(45))
        self.assertIn("未注册关机确认前端", "\n".join(logs.output))


class TestShutdownSys(unittest.TestCase):
    """shutdown_sys：确认才关、取消不关、非 Windows 跳过。"""

    def test_non_windows_skips(self):
        """非 Windows：不弹窗、不执行 shutdown。"""
        with (
            mock.patch.object(sys, "platform", "linux"),
            mock.patch("src.utils.utils_shutdown.subprocess.run") as run,
            mock.patch("src.utils.utils_shutdown._confirm_shutdown") as confirm,
        ):
            shutdown_sys(45)
        confirm.assert_not_called()
        run.assert_not_called()

    def test_confirmed_shuts_down(self):
        """确认：执行 shutdown /s /f /t 0。"""
        with (
            mock.patch.object(sys, "platform", "win32"),
            mock.patch("src.utils.utils_shutdown._confirm_shutdown", return_value=True),
            mock.patch("src.utils.utils_shutdown.subprocess.run") as run,
        ):
            shutdown_sys(45)
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], ["shutdown", "/s", "/f", "/t", "0"])

    def test_cancelled_no_shutdown(self):
        """取消：不执行 shutdown 并记「已取消关机」。"""
        with (
            mock.patch.object(sys, "platform", "win32"),
            mock.patch(
                "src.utils.utils_shutdown._confirm_shutdown", return_value=False
            ),
            mock.patch("src.utils.utils_shutdown.subprocess.run") as run,
            self.assertLogs("src.utils.utils_shutdown", level="INFO") as logs,
        ):
            shutdown_sys(45)
        run.assert_not_called()
        self.assertIn("已取消关机", "\n".join(logs.output))


class TestRunShutdownCommand(unittest.TestCase):
    """_run_shutdown_command：命令拼装与失败留痕。"""

    def test_command_and_flags(self):
        """命令名 + 参数拼装，且不弹额外控制台窗口。"""
        with mock.patch("src.utils.utils_shutdown.subprocess.run") as run:
            _run_shutdown_command(["/a"])
        self.assertEqual(run.call_args.args[0], ["shutdown", "/a"])
        self.assertIsNotNone(run.call_args.kwargs["creationflags"])

    def test_nonzero_exit_logs_error(self):
        """非 0 退出码记 error（不抛，避免打断 post_run 后续步骤）。"""
        failed = mock.Mock(returncode=1, stderr="拒绝访问")
        with (
            mock.patch("src.utils.utils_shutdown.subprocess.run", return_value=failed),
            self.assertLogs("src.utils.utils_shutdown", level="ERROR") as logs,
        ):
            _run_shutdown_command(["/s"])
        self.assertIn("拒绝访问", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
