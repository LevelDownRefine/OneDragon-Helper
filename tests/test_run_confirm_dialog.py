"""测试 src/gui/dialogs.RunConfirmDialog：「启动全部」确认弹窗。

验证：回显 config 当前自动关机/定时配置、accept 收集勾选项、取消 result 为 None。
UI 测试在 offscreen 平台下运行（CI 无显示器）。
"""

import os
import unittest

# 在导入 PySide6 之前设置 offscreen 平台插件（CI 无显示器环境）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.gui.dialogs import RunConfirmDialog

# 模块级 QApplication 单例：widget 需要 GUI 应用，进程退出时随解释器销毁。
if QApplication.instance() is None:
    _APP = QApplication([])


class TestRunConfirmDialog(unittest.TestCase):
    """RunConfirmDialog：回显与勾选项收集。"""

    def test_echoes_current_shutdown_config(self):
        """打开弹窗时回显 config 当前自动关机配置（复选框/延迟）。"""
        dlg = RunConfirmDialog(
            3,
            shutdown_enabled=True,
            shutdown_delay=45,
            timed_enabled=False,
            timed_target="04:10",
        )
        self.assertTrue(dlg.shutdown_cb.isChecked())
        self.assertEqual(dlg.shutdown_delay_spin.value(), 45)
        self.assertTrue(dlg.shutdown_delay_spin.isEnabled())

    def test_echoes_current_timed_config(self):
        """打开弹窗时回显 config 当前定时计划配置（复选框/目标时刻）。"""
        dlg = RunConfirmDialog(
            3,
            shutdown_enabled=False,
            shutdown_delay=0,
            timed_enabled=True,
            timed_target="08:30",
        )
        self.assertTrue(dlg.timed_cb.isChecked())
        self.assertEqual(dlg.timed_time.time().hour(), 8)
        self.assertEqual(dlg.timed_time.time().minute(), 30)
        self.assertTrue(dlg.timed_time.isEnabled())

    def test_disabled_timed_field_unchecked_by_default_when_empty(self):
        """定时未启用且目标时刻空：复选框不勾选、时间框禁用。"""
        dlg = RunConfirmDialog(
            1,
            shutdown_enabled=False,
            shutdown_delay=0,
            timed_enabled=False,
            timed_target="",
        )
        self.assertFalse(dlg.timed_cb.isChecked())
        self.assertFalse(dlg.timed_time.isEnabled())

    def test_accept_collects_selections(self):
        """确认运行：收集复选框与控件值并写入 result（含静音选项）。"""
        dlg = RunConfirmDialog(
            2,
            shutdown_enabled=False,
            shutdown_delay=0,
            timed_enabled=False,
            timed_target="04:10",
            mute_enabled=False,
        )
        dlg.shutdown_cb.setChecked(True)
        dlg.shutdown_delay_spin.setValue(120)
        dlg.timed_cb.setChecked(True)
        dlg.timed_time.setTime(dlg.timed_time.time().__class__(4, 10))
        dlg.mute_cb.setChecked(True)
        dlg._on_accept()
        self.assertEqual(
            dlg.result,
            {
                "shutdown_enabled": True,
                "shutdown_delay": 120,
                "timed_enabled": True,
                "timed_target": "04:10",
                "mute_enabled": True,
            },
        )

    def test_echoes_current_mute_config(self):
        """打开弹窗时回显 config 当前静音配置（勾选状态）。"""
        dlg = RunConfirmDialog(
            3,
            shutdown_enabled=False,
            shutdown_delay=0,
            timed_enabled=False,
            timed_target="04:10",
            mute_enabled=True,
        )
        self.assertTrue(dlg.mute_cb.isChecked())

    def test_cancel_leaves_result_none(self):
        """取消（reject）：result 保持 None，不收集。"""
        dlg = RunConfirmDialog(
            2,
            shutdown_enabled=True,
            shutdown_delay=45,
            timed_enabled=True,
            timed_target="08:00",
            mute_enabled=True,
        )
        dlg.reject()
        self.assertIsNone(dlg.result)


if __name__ == "__main__":
    unittest.main()
