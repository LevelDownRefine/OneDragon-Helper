"""测试 src/python_script/wait_until_0410.py（仅标准库，无 PySide6 依赖）。

核心逻辑不依赖真实时钟：用 mock 控制 datetime.now / time.sleep，
验证 next_trigger 的计算与 wait_until_target 的轮询/退出，不真睡眠、不卡死。

注意：datetime.datetime 是不可变内置类型，无法 patch.object 其 now 属性；
故改为替换 datetime 模块上的 datetime 类（模块属性可变），用 MagicMock 提供可控 now()。
"""

import unittest
from datetime import datetime
from unittest.mock import MagicMock, call, patch

from src.python_script import wait_until_0410 as w


def _fake_datetime_class(now_value=None, now_side_effect=None) -> MagicMock:
    """返回一个顶替 datetime.datetime 的 MagicMock，提供可控的 now()。"""
    cls = MagicMock()
    if now_side_effect is not None:
        cls.now.side_effect = now_side_effect
    else:
        cls.now.return_value = now_value
    return cls


class TestNextTrigger(unittest.TestCase):
    def test_next_trigger_today_when_before_0410(self):
        fake_now = datetime(2026, 7, 27, 2, 0, 0)
        with patch.object(w.datetime, "datetime", _fake_datetime_class(fake_now)):
            t = w.next_trigger()
        self.assertEqual((t.hour, t.minute, t.second), (4, 10, 0))
        self.assertEqual(t.date(), fake_now.date())  # 今天
        self.assertGreater(t, fake_now)

    def test_next_trigger_tomorrow_when_after_0410(self):
        fake_now = datetime(2026, 7, 27, 5, 0, 0)
        with patch.object(w.datetime, "datetime", _fake_datetime_class(fake_now)):
            t = w.next_trigger()
        self.assertEqual((t.hour, t.minute, t.second), (4, 10, 0))
        self.assertEqual(t.date(), datetime(2026, 7, 28).date())  # 明天
        self.assertGreater(t, fake_now)


class TestWaitUntilTarget(unittest.TestCase):
    def test_returns_immediately_when_target_already_passed(self):
        target = datetime(2026, 7, 27, 4, 10, 0)
        now = datetime(2026, 7, 27, 5, 0, 0)
        with (
            patch.object(w, "next_trigger", return_value=target),
            patch.object(w.datetime, "datetime", _fake_datetime_class(now)),
            patch.object(w.time, "sleep") as m_sleep,
        ):
            w.wait_until_target()
        m_sleep.assert_not_called()

    def test_polls_every_30s_until_reached(self):
        target = datetime(2026, 7, 27, 4, 10, 0)
        now_seq = [
            datetime(2026, 7, 27, 4, 9, 0),  # < target -> sleep
            datetime(2026, 7, 27, 4, 9, 30),  # < target -> sleep
            datetime(2026, 7, 27, 4, 9, 50),  # < target -> sleep
            datetime(2026, 7, 27, 4, 10, 0),  # == target -> 退出
        ]
        with (
            patch.object(w, "next_trigger", return_value=target),
            patch.object(
                w.datetime, "datetime", _fake_datetime_class(now_side_effect=now_seq)
            ),
            patch.object(w.time, "sleep") as m_sleep,
        ):
            w.wait_until_target()
        self.assertEqual(m_sleep.call_count, 3)
        m_sleep.assert_has_calls([call(30)] * 3)


if __name__ == "__main__":
    unittest.main()
