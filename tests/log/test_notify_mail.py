"""测试 src/log/notify_mail.py：send_mail 的开关闸门、smtplib 发送与 keyring 取密。

正文渲染（HTML）归 src/log/build_html.py，其测试见 test_build_html.py。
"""

import unittest
from email.header import decode_header, make_header
from unittest import mock

from src.log.notify_mail import _build_body, send_mail
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

    def test_disabled_when_no_config(self):
        """smtp_config=None（默认）时直接跳过，不建连。"""
        send_mail(make_result(), smtp_config=None)
        self.smtp_cls.assert_not_called()

    def test_disabled_when_enabled_false(self):
        """enabled=false：即便 email 齐全也跳过。"""
        send_mail(
            make_result(),
            smtp_config={"enabled": False, "email": "a@qq.com"},
        )
        self.smtp_cls.assert_not_called()

    def test_skips_incomplete_config(self):
        """enabled=true 但 email 缺失：跳过（默认关闭的安全兜底）。"""
        send_mail(
            make_result(),
            smtp_config={"enabled": True, "email": ""},
        )
        self.smtp_cls.assert_not_called()

    def test_password_missing_skips(self):
        """keyring 与 schedule.yml 均无授权码：跳过发送（不建连）。"""
        send_mail(
            make_result(),
            smtp_config={"enabled": True, "email": "123456@qq.com"},
        )
        self.smtp_cls.assert_not_called()

    def test_sends_summary_on_success(self):
        """notify 为空（本次全成功）：仍发送汇总邮件，主题为『脚本运行汇总』。"""
        cfg = {
            "enabled": True,
            "email": "123456@qq.com",
            "smtp_host": "smtp.qq.com",
            "smtp_port": 465,
        }
        _, smtp = self._sent(make_result(notify=()), cfg, keyring_password="authcode")
        smtp.send_message.assert_called_once()
        subject = self._decode_subject(smtp.send_message.call_args.args[0])
        self.assertIn("[OneDragon-Helper] 脚本运行汇总", subject)
        self.assertNotIn("报错", subject)

    def test_sends_with_failure_subject(self):
        """有报错：主题标注『脚本运行报错:<脚本名>』，且仍发送。"""
        cfg = {
            "enabled": True,
            "email": "123456@qq.com",
            "smtp_host": "smtp.qq.com",
            "smtp_port": 465,
        }
        _, smtp = self._sent(
            make_result(notify=("demo", "arknights")), cfg, keyring_password="authcode"
        )
        smtp.send_message.assert_called_once()
        subject = self._decode_subject(smtp.send_message.call_args.args[0])
        self.assertIn("脚本运行报错: demo、arknights", subject)

    def test_build_body_includes_report(self):
        """_build_body 拼接汇总表（空 entries 时无诊断段）。"""
        self.assertIn("脚本运行状况汇总报告", _build_body(make_result(), ""))

    def test_password_from_keyring(self):
        """keyring 存有授权码且 schedule.yml 无 password：仍发送（keyring 优先路径）。"""
        cfg = {
            "enabled": True,
            "email": "123456@qq.com",
            "smtp_host": "smtp.qq.com",
            "smtp_port": 465,
        }
        _, smtp = self._sent(make_result(), cfg, keyring_password="vaultcode")
        smtp.send_message.assert_called_once()
        smtp.login.assert_called_once_with("123456@qq.com", "vaultcode")

    def test_sends_via_smtplib_qq_from_config(self):
        """enabled=true + 授权码（系统凭据管理器）+ 配置显式 QQ：经 smtplib 以 smtp.qq.com:465 隐式 SSL 发送，收发同号。"""
        cfg = {
            "enabled": True,
            "email": "123456@qq.com",
            "smtp_host": "smtp.qq.com",
            "smtp_port": 465,
        }
        smtp_cls, smtp = self._sent(
            make_result(notify=("demo", "arknights")), cfg, keyring_password="authcode"
        )
        smtp_cls.assert_called_once()
        # 位置参数 (host, port)；隐式 SSL 端口 465
        self.assertEqual(smtp_cls.call_args.args, ("smtp.qq.com", 465))
        self.assertIn("timeout", smtp_cls.call_args.kwargs)
        self.assertIn("context", smtp_cls.call_args.kwargs)  # create_default_context
        # 收发同号：自己发给自己
        smtp.login.assert_called_once_with("123456@qq.com", "authcode")
        smtp.send_message.assert_called_once()
        msg = smtp.send_message.call_args.args[0]
        self.assertEqual(msg["From"], "123456@qq.com")
        self.assertEqual(msg["To"], "123456@qq.com")
        # 正文为 multipart/alternative：plain 在前、html 在后
        self.assertEqual(msg.get_content_type(), "multipart/alternative")
        parts = msg.get_payload()
        self.assertEqual(len(parts), 2)
        # 中文正文经 base64 传输编码，get_payload(decode=True) 还原为原始字节
        plain = parts[0].get_payload(decode=True).decode("utf-8")
        html = parts[1].get_payload(decode=True).decode("utf-8")
        self.assertIn("脚本运行状况汇总报告", plain)
        self.assertIn("<table", html)

    def test_skips_when_smtp_not_configured(self):
        """enabled=true 且授权码齐全，但 smtp_host/smtp_port 缺失：配置不全、跳过发送。"""
        cfg = {"enabled": True, "email": "123456@qq.com"}
        self._sent(make_result(), cfg, keyring_password="authcode")
        self.smtp_cls.assert_not_called()

    def test_sends_custom_smtp_host_port(self):
        """smtp_host/smtp_port 覆盖默认 QQ 服务商。"""
        cfg = {
            "enabled": True,
            "email": "u@163.com",
            "smtp_host": "smtp.163.com",
            "smtp_port": 465,
        }
        smtp_cls, _ = self._sent(make_result(), cfg, keyring_password="pw")
        self.assertEqual(smtp_cls.call_args.args, ("smtp.163.com", 465))

    def test_skips_when_smtp_port_non_numeric(self):
        """enabled=true 且授权码齐全，但 smtp_port 非数字：运行期校验失败、跳过发送、不抛异常。"""
        cfg = {
            "enabled": True,
            "email": "u@qq.com",
            "smtp_host": "smtp.qq.com",
            "smtp_port": "not-a-number",
        }
        self._sent(make_result(), cfg, keyring_password="pw")
        self.smtp_cls.assert_not_called()

    def test_skips_when_smtp_port_nonpositive(self):
        """smtp_port=0 视为非法端口，跳过发送。"""
        cfg = {
            "enabled": True,
            "email": "u@qq.com",
            "smtp_host": "smtp.qq.com",
            "smtp_port": 0,
        }
        self._sent(make_result(), cfg, keyring_password="pw")
        self.smtp_cls.assert_not_called()


if __name__ == "__main__":
    unittest.main()
