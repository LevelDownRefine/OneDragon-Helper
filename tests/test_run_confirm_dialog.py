"""测试 src/gui/run_confirm_dialog.RunConfirmDialog：「启动全部」确认弹窗。

验证：回显 config 当前自动关机/定时配置、accept 收集勾选项、取消 result 为 None。
UI 测试在 offscreen 平台下运行（CI 无显示器）。
"""

import os
import unittest

# 在导入 PySide6 之前设置 offscreen 平台插件（CI 无显示器环境）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.gui.run_confirm_dialog import RunConfirmDialog

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
        """确认运行：收集复选框与控件值并写入 result（含静音/重跑/邮件通知）。"""
        dlg = RunConfirmDialog(
            2,
            shutdown_enabled=False,
            shutdown_delay=0,
            timed_enabled=False,
            timed_target="04:10",
            mute_enabled=False,
            rerun_enabled=True,
            notify_enabled=False,
        )
        dlg.shutdown_cb.setChecked(True)
        dlg.shutdown_delay_spin.setValue(120)
        dlg.timed_cb.setChecked(True)
        dlg.timed_time.setTime(dlg.timed_time.time().__class__(4, 10))
        dlg.mute_cb.setChecked(True)
        dlg.rerun_cb.setChecked(False)
        dlg.notify_cb.setChecked(True)
        dlg._on_accept()
        self.assertEqual(
            dlg.result,
            {
                "shutdown_enabled": True,
                "shutdown_delay": 120,
                "timed_enabled": True,
                "timed_target": "04:10",
                "mute_enabled": True,
                "close_running_enabled": True,
                "rerun_enabled": False,
                "notify_enabled": True,
                "email": "",
                "auth_code": "",
                "smtp_host": "",
                "smtp_port": "",
            },
        )

    def test_echoes_and_collects_email(self):
        """打开弹窗回显邮箱、勾选通知才可编辑邮箱/授权码；accept 收集输入值。"""
        dlg = RunConfirmDialog(
            2,
            shutdown_enabled=False,
            shutdown_delay=0,
            timed_enabled=False,
            timed_target="04:10",
            notify_enabled=True,
            email="123456@qq.com",
        )
        # 预填邮箱回显
        self.assertEqual(dlg.email_edit.text(), "123456@qq.com")
        # 通知已勾选 → 邮箱/授权码可编辑
        self.assertTrue(dlg.email_edit.isEnabled())
        self.assertTrue(dlg.auth_edit.isEnabled())
        dlg.auth_edit.setText("authcode16")
        dlg._on_accept()
        self.assertEqual(
            dlg.result,
            {
                "shutdown_enabled": False,
                "shutdown_delay": 0,
                "timed_enabled": False,
                "timed_target": "04:10",
                "mute_enabled": False,
                "close_running_enabled": True,
                "rerun_enabled": True,
                "notify_enabled": True,
                "email": "123456@qq.com",
                "auth_code": "authcode16",
                "smtp_host": "",
                "smtp_port": "",
            },
        )

    def test_notify_off_disables_email_fields(self):
        """未勾选邮件通知：邮箱/授权码/SMTP 输入框禁用（与定时/关机联动一致）。"""
        dlg = RunConfirmDialog(
            2,
            shutdown_enabled=False,
            shutdown_delay=0,
            timed_enabled=False,
            timed_target="04:10",
            notify_enabled=False,
            email="123456@qq.com",
        )
        self.assertFalse(dlg.email_edit.isEnabled())
        self.assertFalse(dlg.auth_edit.isEnabled())
        self.assertFalse(dlg.smtp_host_edit.isEnabled())
        self.assertFalse(dlg.smtp_port_edit.isEnabled())

    def test_echoes_and_collects_smtp(self):
        """打开弹窗回显 SMTP 主机/端口、accept 收集输入值（与邮箱同处理）。"""
        dlg = RunConfirmDialog(
            2,
            shutdown_enabled=False,
            shutdown_delay=0,
            timed_enabled=False,
            timed_target="04:10",
            notify_enabled=True,
            email="123456@qq.com",
            smtp_host="smtp.qq.com",
            smtp_port="465",
        )
        # 预填 SMTP 配置回显
        self.assertEqual(dlg.smtp_host_edit.text(), "smtp.qq.com")
        self.assertEqual(dlg.smtp_port_edit.text(), "465")
        # 通知已勾选 → SMTP 输入框可编辑
        self.assertTrue(dlg.smtp_host_edit.isEnabled())
        self.assertTrue(dlg.smtp_port_edit.isEnabled())
        # 用户改填其他服务商
        dlg.smtp_host_edit.setText("smtp.163.com")
        dlg.smtp_port_edit.setText("994")
        dlg._on_accept()
        self.assertEqual(
            dlg.result,
            {
                "shutdown_enabled": False,
                "shutdown_delay": 0,
                "timed_enabled": False,
                "timed_target": "04:10",
                "mute_enabled": False,
                "close_running_enabled": True,
                "rerun_enabled": True,
                "notify_enabled": True,
                "email": "123456@qq.com",
                "auth_code": "",
                "smtp_host": "smtp.163.com",
                "smtp_port": "994",
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

    def test_echoes_current_rerun_config(self):
        """打开弹窗时回显 config 当前重跑配置（勾选状态）。"""
        dlg = RunConfirmDialog(
            3,
            shutdown_enabled=False,
            shutdown_delay=0,
            timed_enabled=False,
            timed_target="04:10",
            rerun_enabled=False,
        )
        self.assertFalse(dlg.rerun_cb.isChecked())

    def test_echoes_current_notify_config(self):
        """打开弹窗时回显 config 当前邮件通知配置（勾选状态）。"""
        dlg = RunConfirmDialog(
            3,
            shutdown_enabled=False,
            shutdown_delay=0,
            timed_enabled=False,
            timed_target="04:10",
            notify_enabled=True,
        )
        self.assertTrue(dlg.notify_cb.isChecked())

    def test_echoes_current_close_running_config(self):
        """打开弹窗时回显 config 当前运行前关闭残留进程配置（勾选状态）。"""
        dlg = RunConfirmDialog(
            3,
            shutdown_enabled=False,
            shutdown_delay=0,
            timed_enabled=False,
            timed_target="04:10",
            close_running_enabled=False,
        )
        self.assertFalse(dlg.close_running_cb.isChecked())

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
