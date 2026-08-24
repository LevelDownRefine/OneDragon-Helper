"""测试 src/log/notify_mail.py：send_mail 默认关闭、SMTP 接口与正文拼接。"""

import unittest
from unittest import mock

from src.log.notify_mail import _build_body, send_mail


def _result(*, notify=("demo",)) -> dict:
    """最小 parse_logs 产物；notify 为非空列表表示存在报错脚本。

    Args:
        notify: 报错脚本列表；传空元组表示「本次无报错」，用于验证仅失败才发。
    """
    return {"report": "脚本运行状况汇总报告", "entries": [], "notify": list(notify)}


class TestSendMail(unittest.TestCase):
    """send_mail：默认关闭、enabled 闸门、仅失败才发、QQ 收发同号发送。"""

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

    def test_skips_when_no_failures(self):
        """notify 为空（本次无报错）：即便 enabled+凭据齐全也不发。"""
        cfg = {"enabled": True, "email": "123456@qq.com", "password": "authcode"}
        with mock.patch("smtplib.SMTP_SSL") as smtp:
            send_mail(_result(notify=()), smtp_config=cfg)
        smtp.assert_not_called()

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
