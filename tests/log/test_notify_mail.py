"""测试 src/log/notify_mail.py：send_mail 的开关闸门、smtplib 发送与 keyring 取密。

正文渲染（HTML）归 src/log/build_html.py，其测试见 test_build_html.py。
"""

import unittest
from email.header import decode_header, make_header
from unittest import mock

from src.log.notify_mail import send_mail
from tests.log.helpers import make_result


class TestSendMail(unittest.TestCase):
    """send_mail：默认关闭、enabled 闸门、无论成败均发送、经 smtplib+keyring 发送。"""

    def setUp(self):
        # 冻结 smtplib.SMTP_SSL 与 keyring，避免测试触碰真实网络/系统凭据管理器。
        self._smtp_patch = mock.patch("smtplib.SMTP_SSL")
        self._get_pw_patch = mock.patch("keyring.get_password", return_value=None)
        self._set_pw_patch = mock.patch("keyring.set_password", return_value=None)
        self.smtp_cls = self._smtp_patch.start()
        self.get_pw = self._get_pw_patch.start()
        self.set_pw = self._set_pw_patch.start()
        self.addCleanup(self._smtp_patch.stop)
        self.addCleanup(self._get_pw_patch.stop)
        self.addCleanup(self._set_pw_patch.stop)

    def _sent(self, result, smtp_config, *, keyring_password=None):
        """触发 send_mail 并返回 (SMTP 类 mock, smtp 实例 mock)。

        Args:
            result: parse_logs 产物。
            smtp_config: schedule.yml 的 notify 段。
            keyring_password: 非 None 时让 keyring.get_password 返回该授权码（优先路径）。
        """
        if keyring_password is not None:
            self.get_pw.return_value = keyring_password
        send_mail(result, smtp_config=smtp_config)
        smtp = self.smtp_cls.return_value.__enter__.return_value
        return self.smtp_cls, smtp

    @staticmethod
    def _decode_subject(msg) -> str:
        """把 MIMEText 的 RFC2047 编码主题还原为明文，便于断言。"""
        return str(make_header(decode_header(msg["Subject"])))

    def test_disabled_or_incomplete_mail_configuration_never_connects(self):
        complete = {
            "enabled": True,
            "email": "123456@qq.com",
            "smtp_host": "smtp.qq.com",
            "smtp_port": 465,
        }
        for name, cfg, password in (
            ("no_config", None, None),
            ("disabled", {**complete, "enabled": False}, "pw"),
            ("missing_email", {**complete, "email": ""}, "pw"),
            ("missing_password", complete, None),
            ("missing_server", {"enabled": True, "email": "123456@qq.com"}, "pw"),
            ("invalid_port", {**complete, "smtp_port": "not-a-number"}, "pw"),
            ("zero_port", {**complete, "smtp_port": 0}, "pw"),
        ):
            with self.subTest(name=name):
                self.smtp_cls.reset_mock()
                self.get_pw.return_value = password
                send_mail(make_result(), smtp_config=cfg)
                self.smtp_cls.assert_not_called()

    def test_smtp_delivery_preserves_credentials_subject_and_both_body_formats(self):
        for email, host in (
            ("123456@qq.com", "smtp.qq.com"),
            ("u@163.com", "smtp.163.com"),
        ):
            for notify, subject in (
                ((), "[OneDragon-Helper] 脚本运行汇总"),
                (("demo", "arknights"), "脚本运行报错: demo、arknights"),
            ):
                with self.subTest(host=host, notify=notify):
                    self.smtp_cls.reset_mock()
                    cfg = {
                        "enabled": True,
                        "email": email,
                        "smtp_host": host,
                        "smtp_port": 465,
                    }
                    smtp_cls, smtp = self._sent(
                        make_result(notify=notify), cfg, keyring_password="authcode"
                    )
                    smtp_cls.assert_called_once()
                    self.assertEqual(smtp_cls.call_args.args, (host, 465))
                    self.assertIn("timeout", smtp_cls.call_args.kwargs)
                    self.assertIn("context", smtp_cls.call_args.kwargs)
                    smtp.login.assert_called_once_with(email, "authcode")
                    smtp.send_message.assert_called_once()
                    msg = smtp.send_message.call_args.args[0]
                    self.assertIn(subject, self._decode_subject(msg))
                    if not notify:
                        self.assertNotIn("报错", self._decode_subject(msg))
                    self.assertEqual((msg["From"], msg["To"]), (email, email))
                    self.assertEqual(msg.get_content_type(), "multipart/alternative")
                    parts = msg.get_payload()
                    self.assertEqual(len(parts), 2)
                    self.assertIn(
                        "脚本运行状况汇总报告",
                        parts[0].get_payload(decode=True).decode("utf-8"),
                    )
                    self.assertIn(
                        "<table", parts[1].get_payload(decode=True).decode("utf-8")
                    )


if __name__ == "__main__":
    unittest.main()
