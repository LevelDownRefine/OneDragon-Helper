"""测试 src/log/notify_mail.py：send_mail 默认关闭、SMTP 接口与正文拼接。"""

import unittest
from email import message_from_string
from email.header import decode_header, make_header
from unittest import mock

from src.log.notify_mail import _build_body, send_mail


def _decode_subject(sendmail_args) -> str:
    """从 sendmail 的入参里解出 RFC 2047 编码的主题（中文主题会被 base64 编码）。

    Args:
        sendmail_args: ``server.sendmail.call_args`` 的 args 元组，下标 2 为完整报文。

    Returns:
        解码后的主题字符串。
    """
    raw = message_from_string(sendmail_args[2])["Subject"]
    return str(make_header(decode_header(raw)))


def _result(*, notify=("demo",)) -> dict:
    """最小 parse_logs 产物；notify 为非空列表表示存在报错脚本。

    Args:
        notify: 报错脚本列表；传空元组表示「本次全成功」，用于验证仍发汇总邮件。
    """
    return {"report": "脚本运行状况汇总报告", "entries": [], "notify": list(notify)}


class TestSendMail(unittest.TestCase):
    """send_mail：默认关闭、enabled 闸门、无论成败均发送、QQ 收发同号发送。"""

    def test_disabled_when_no_config(self):
        """smtp_config=None（默认）时直接跳过，不发信。"""
        with mock.patch("smtplib.SMTP_SSL") as smtp:
            send_mail(_result(), smtp_config=None)
        smtp.assert_not_called()

    def test_disabled_when_enabled_false(self):
        """enabled=false：即便 email/password 齐全也跳过。"""
        with mock.patch("smtplib.SMTP_SSL") as smtp:
            send_mail(
                _result(),
                smtp_config={"enabled": False, "email": "a@qq.com", "password": "pw"},
            )
        smtp.assert_not_called()

    def test_skips_incomplete_config(self):
        """enabled=true 但 email/password 缺失：跳过（默认关闭的安全兜底）。"""
        with mock.patch("smtplib.SMTP_SSL") as smtp:
            send_mail(
                _result(),
                smtp_config={"enabled": True, "email": "", "password": ""},
            )
        smtp.assert_not_called()

    def test_sends_summary_on_success(self):
        """notify 为空（本次全成功）：仍发送汇总邮件，主题为『脚本运行汇总』。"""
        cfg = {"enabled": True, "email": "123456@qq.com", "password": "authcode"}
        with mock.patch("smtplib.SMTP_SSL") as smtp_cls:
            send_mail(_result(notify=()), smtp_config=cfg)
        smtp_cls.assert_called_once()
        server = smtp_cls.return_value.__enter__.return_value
        args, _ = server.sendmail.call_args
        # 全成功时主题为汇总（不含报错字样）
        subject = _decode_subject(args)
        self.assertIn("[OneDragon-Helper] 脚本运行汇总", subject)
        self.assertNotIn("报错", subject)

    def test_sends_with_failure_subject(self):
        """有报错：主题标注『脚本运行报错:<脚本名>』，且仍发送。"""
        cfg = {"enabled": True, "email": "123456@qq.com", "password": "authcode"}
        with mock.patch("smtplib.SMTP_SSL") as smtp_cls:
            send_mail(_result(notify=("demo", "arknights")), smtp_config=cfg)
        smtp_cls.assert_called_once()
        server = smtp_cls.return_value.__enter__.return_value
        args, _ = server.sendmail.call_args
        subject = _decode_subject(args)
        self.assertIn("脚本运行报错: demo、arknights", subject)

    def test_build_body_includes_report(self):
        """_build_body 拼接汇总表（空 entries 时无诊断段）。"""
        self.assertIn("脚本运行状况汇总报告", _build_body(_result()))

    def test_sends_qq_default(self):
        """enabled=true + email/password + 有失败：经 QQ SMTP_SSL 发送，收发同号。"""
        cfg = {"enabled": True, "email": "123456@qq.com", "password": "authcode"}
        with mock.patch("smtplib.SMTP_SSL") as smtp_cls:
            send_mail(_result(notify=("demo", "arknights")), smtp_config=cfg)
        smtp_cls.assert_called_once_with("smtp.qq.com", 465, timeout=10)
        server = smtp_cls.return_value.__enter__.return_value
        server.login.assert_called_once_with("123456@qq.com", "authcode")
        server.sendmail.assert_called_once()
        # 收发同号：自己发给自己
        args, _ = server.sendmail.call_args
        self.assertEqual(args[0], "123456@qq.com")
        self.assertEqual(args[1], ["123456@qq.com"])


if __name__ == "__main__":
    unittest.main()
