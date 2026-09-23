"""测试 src/gui/run_confirm_dialog.RunConfirmDialog：「启动全部」确认弹窗。

验证：回显 RunOptions 初始值（取自 schedule.yml 经 load_run_options）、accept
收集为 RunOptions、取消 run_options 为 None。UI 测试在 offscreen 平台下运行（CI 无显示器）。
"""

import os
import unittest
from dataclasses import asdict, replace

# 在导入 PySide6 之前设置 offscreen 平台插件（CI 无显示器环境）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton, QTimeEdit

from src.gui.dialogs import BG_INPUT, TEXT
from src.gui.run_confirm_dialog import RunConfirmDialog
from src.service.schedule import RunOptions

# 模块级 QApplication 单例：widget 需要 GUI 应用，进程退出时随解释器销毁。
if QApplication.instance() is None:
    _APP = QApplication([])


def _opts(**overrides) -> RunOptions:
    """构造弹窗初始值：空 schedule 的 load_run_options 默认 + 用例覆盖。"""
    base = RunOptions()
    return replace(base, **overrides) if overrides else base


class TestRunConfirmDialog(unittest.TestCase):
    """RunConfirmDialog：回显与勾选项收集。"""

    def test_settings_only_saves_without_a_start_button_or_one_shot_timer(self):
        dlg = RunConfirmDialog(0, _opts(), settings_only=True)
        self.addCleanup(dlg.close)
        self.assertEqual(dlg.windowTitle(), "运行选项")
        self.assertEqual(dlg.findChildren(QTimeEdit), [])
        buttons = {button.text(): button for button in dlg.findChildren(QPushButton)}
        self.assertIn("保存", buttons)
        self.assertNotIn("确认运行", buttons)
        dlg.mute_cb.setChecked(True)
        buttons["保存"].click()
        self.assertTrue(dlg.run_options.mute_enabled)

    def test_echoes_saved_run_options(self):
        fields = ("shutdown", "mute", "unmute", "rerun", "notify", "close_running")
        for field, value in zip(
            fields, (True, True, True, False, True, False), strict=True
        ):
            with self.subTest(field=field):
                options = _opts(**{field + "_enabled": value}, shutdown_delay=45)
                dialog = RunConfirmDialog(3, options)
                self.addCleanup(dialog.close)
                for name in fields:
                    self.assertEqual(
                        getattr(dialog, name + "_cb").isChecked(),
                        getattr(options, name + "_enabled"),
                        name,
                    )
                self.assertEqual(dialog.shutdown_delay_spin.value(), 45)
                self.assertEqual(
                    dialog.shutdown_delay_spin.isEnabled(), options.shutdown_enabled
                )

    def test_accept_collects_selections(self):
        """确认运行：收集复选框与控件值写入 run_options（含静音/重跑/邮件通知）。"""
        dlg = RunConfirmDialog(2, _opts(rerun_enabled=True))
        self.addCleanup(dlg.close)
        self.assertEqual(dlg.smtp_host_edit.text(), "smtp.qq.com")
        self.assertEqual(dlg.smtp_port_edit.text(), "465")
        dlg.shutdown_cb.setChecked(True)
        dlg.shutdown_delay_spin.setValue(120)
        dlg.mute_cb.setChecked(True)
        dlg.unmute_cb.setChecked(True)
        dlg.rerun_cb.setChecked(False)
        dlg.notify_cb.setChecked(True)
        dlg._on_accept()
        self.assertEqual(
            asdict(dlg.run_options),
            {
                "shutdown_enabled": True,
                "shutdown_delay": 120,
                "mute_enabled": True,
                "unmute_enabled": True,
                "close_running_enabled": True,
                "rerun_enabled": False,
                "notify_enabled": True,
                "email": "",
                "auth_code": "",
                # schedule 无 SMTP 配置时弹窗以 QQ 默认预填，accept 随之收集
                "smtp_host": "smtp.qq.com",
                "smtp_port": "465",
            },
        )

    def test_mail_fields_echo_and_collect_edited_credentials_and_server(self):
        dialog = RunConfirmDialog(
            2,
            _opts(
                notify_enabled=True,
                email="123456@qq.com",
                smtp_host="smtp.qq.com",
                smtp_port="465",
            ),
        )
        self.addCleanup(dialog.close)
        self.assertEqual(dialog.email_edit.text(), "123456@qq.com")
        self.assertEqual(dialog.smtp_host_edit.text(), "smtp.qq.com")
        self.assertEqual(dialog.smtp_port_edit.text(), "465")
        for control in (
            dialog.email_edit,
            dialog.auth_edit,
            dialog.smtp_host_edit,
            dialog.smtp_port_edit,
        ):
            self.assertTrue(control.isEnabled())
        dialog.auth_edit.setText("authcode16")
        dialog.smtp_host_edit.setText("smtp.163.com")
        dialog.smtp_port_edit.setText("994")
        dialog._on_accept()
        self.assertEqual(dialog.run_options.email, "123456@qq.com")
        self.assertEqual(dialog.run_options.auth_code, "authcode16")
        self.assertEqual(dialog.run_options.smtp_host, "smtp.163.com")
        self.assertEqual(dialog.run_options.smtp_port, "994")
        self.assertTrue(dialog.run_options.notify_enabled)

    def test_notify_off_disables_email_fields(self):
        """未勾选邮件通知：邮箱/授权码/SMTP 输入框禁用（与定时/关机联动一致）。"""
        dlg = RunConfirmDialog(2, _opts(notify_enabled=False, email="123456@qq.com"))
        self.assertFalse(dlg.email_edit.isEnabled())
        self.assertFalse(dlg.auth_edit.isEnabled())
        self.assertFalse(dlg.smtp_host_edit.isEnabled())
        self.assertFalse(dlg.smtp_port_edit.isEnabled())

    def test_cancel_leaves_run_options_none(self):
        """取消（reject）：run_options 保持 None，不收集。"""
        dlg = RunConfirmDialog(
            2, _opts(shutdown_enabled=True, shutdown_delay=45, mute_enabled=True)
        )
        dlg.reject()
        self.assertIsNone(dlg.run_options)


class TestRunConfirmDialogTheme(unittest.TestCase):
    """邮件/SMTP 输入框套「深底白字」样式。

    弹窗本体 setStyleSheet(background-color) 会向子控件继承深底；若输入框自身不设
    color，文字取默认调色板（浅色系统下为黑色）→ 黑字深底不可读，故必须显式套样式。
    """

    def test_email_fields_styled_dark(self):
        dlg = RunConfirmDialog(1, _opts(notify_enabled=True))
        self.addCleanup(dlg.close)
        for edit in (
            dlg.email_edit,
            dlg.auth_edit,
            dlg.smtp_host_edit,
            dlg.smtp_port_edit,
        ):
            self.assertIn(TEXT, edit.styleSheet())
            self.assertIn(BG_INPUT, edit.styleSheet())


if __name__ == "__main__":
    unittest.main()
