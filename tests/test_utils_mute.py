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

    def test_mute_on_calls_set_true(self):
        with mock.patch("src.utils.utils_mute.set_system_mute") as sm:
            mute_on()
            sm.assert_called_once_with(True)

    def test_mute_off_calls_set_false(self):
        with mock.patch("src.utils.utils_mute.set_system_mute") as sm:
            mute_off()
            sm.assert_called_once_with(False)

    def test_mute_on_swallows_exception(self):
        with mock.patch(
            "src.utils.utils_mute.set_system_mute", side_effect=RuntimeError("boom")
        ):
            # 不应抛出；_run_steps 也会兜底，但 step 内部已自包容。
            mute_on()

    def test_mute_off_swallows_exception(self):
        with mock.patch(
            "src.utils.utils_mute.set_system_mute", side_effect=RuntimeError("boom")
        ):
            mute_off()

    def test_mute_on_logs_success(self):
        """静音成功打 info 日志（exe e2e 靠它断言 mute 真实生效）。"""
        with (
            mock.patch("src.utils.utils_mute.set_system_mute", return_value=True),
            self.assertLogs("src.utils.utils_mute", level="INFO") as logs,
        ):
            mute_on()
        self.assertIn("[mute] 已静音", logs.output[0])

    def test_mute_on_warns_unavailable(self):
        """pycaw 缺失/非 Windows 的静默降级改为 warning 留痕。"""
        with (
            mock.patch("src.utils.utils_mute.set_system_mute", return_value=False),
            self.assertLogs("src.utils.utils_mute", level="WARNING") as logs,
        ):
            mute_on()
        self.assertIn("[mute] 运行前静音未生效", logs.output[0])

    def test_mute_off_logs_success(self):
        with (
            mock.patch("src.utils.utils_mute.set_system_mute", return_value=True),
            self.assertLogs("src.utils.utils_mute", level="INFO") as logs,
        ):
            mute_off()
        self.assertIn("[mute] 已恢复声音", logs.output[0])

    def test_mute_off_warns_unavailable(self):
        with (
            mock.patch("src.utils.utils_mute.set_system_mute", return_value=False),
            self.assertLogs("src.utils.utils_mute", level="WARNING") as logs,
        ):
            mute_off()
        self.assertIn("[mute] 运行后恢复未生效", logs.output[0])
