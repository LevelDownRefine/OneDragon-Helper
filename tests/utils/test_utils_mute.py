"""测试 src/utils_mute.py：运行中系统静音执行（config 读写见 test_utils_runner）。"""

import sys
import unittest
from unittest import mock

from src.utils.utils_mute import (
    mute_off,
    mute_on,
    set_system_mute,
)


class TestSetSystemMute(unittest.TestCase):
    """set_system_mute：非 Windows / pycaw 缺失时安全降级（不影响链运行）。"""

    def test_non_windows_returns_false(self):
        with mock.patch.object(sys, "platform", "linux"):
            self.assertFalse(set_system_mute(True))

    def test_windows_without_pycaw_returns_false(self):
        with (
            mock.patch.object(sys, "platform", "win32"),
            mock.patch.dict("sys.modules", {"pycaw": None, "pycaw.pycaw": None}),
        ):
            self.assertFalse(set_system_mute(True))

    def test_windows_success_returns_true(self):
        fake_interface = mock.Mock()
        fake_pycaw = mock.Mock()
        fake_pycaw.AudioUtilities.GetSpeakers.return_value = mock.Mock()
        fake_pycaw.IAudioEndpointVolume._iid_ = "iid"
        with (
            mock.patch.object(sys, "platform", "win32"),
            mock.patch.dict(
                "sys.modules", {"pycaw": mock.Mock(), "pycaw.pycaw": fake_pycaw}
            ),
            mock.patch("ctypes.cast", return_value=fake_interface),
            mock.patch("ctypes.POINTER", side_effect=lambda t: t),
        ):
            self.assertTrue(set_system_mute(True))
            fake_interface.SetMute.assert_called_once_with(True, None)


class TestMuteOnOff(unittest.TestCase):
    """mute_on / mute_off：pre_run/post_run step 封装，异常不向上抛。"""

    def test_result_is_logged_for_both_actions(self):
        actions = (
            (mute_on, True, "[mute] 已静音", "[mute] 运行前静音未生效"),
            (mute_off, False, "[mute] 已恢复声音", "[mute] 运行后恢复未生效"),
        )
        for action, muted, success_message, failure_message in actions:
            for success, level, message in (
                (True, "INFO", success_message),
                (False, "WARNING", failure_message),
            ):
                with self.subTest(action=action.__name__, success=success):
                    with (
                        mock.patch(
                            "src.utils.utils_mute.set_system_mute", return_value=success
                        ) as set_mute,
                        self.assertLogs("src.utils.utils_mute", level=level) as logs,
                    ):
                        action()
                    set_mute.assert_called_once_with(muted)
                    self.assertEqual(len(logs.records), 1)
                    self.assertEqual(logs.records[0].levelname, level)
                    self.assertIn(message, logs.records[0].getMessage())

    def test_errors_are_logged_without_interrupting_the_chain(self):
        for action, muted, message in (
            (mute_on, True, "[mute] 运行前静音失败"),
            (mute_off, False, "[mute] 运行后恢复声音失败"),
        ):
            with self.subTest(action=action.__name__):
                with (
                    mock.patch(
                        "src.utils.utils_mute.set_system_mute",
                        side_effect=RuntimeError("boom"),
                    ) as set_mute,
                    self.assertLogs("src.utils.utils_mute", level="ERROR") as logs,
                ):
                    action()
                set_mute.assert_called_once_with(muted)
                self.assertEqual(len(logs.records), 1)
                self.assertEqual(logs.records[0].getMessage(), message)
                self.assertIs(logs.records[0].exc_info[0], RuntimeError)
                self.assertIn("RuntimeError: boom", logs.output[0])
