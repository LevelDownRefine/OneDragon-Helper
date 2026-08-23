"""测试 src/log/notify_mail.py：send_mail 默认关闭、SMTP 接口与正文拼接。"""

import unittest
from unittest import mock

from src.log.notify_mail import _build_body, send_mail


def _result() -> dict:
    """最小 parse_logs 产物：空 entries 使正文仅含汇总表。"""
    return {"report": "脚本运行状况汇总报告", "entries": [], "notify": []}


class TestSendMail(unittest.TestCase):
    """send_mail：默认关闭、配置不完整跳过、SSL/明文 SMTP 发送且正文含汇总。"""

    def test_disabled_when_no_config(self):
        """smtp_config=None（默认）时直接跳过，不发信。"""
        with mock.patch("smtplib.SMTP_SSL") as smtp:
            send_mail(_result(), smtp_config=None)
        smtp.assert_not_called()

    def test_skips_incomplete_config(self):
        """缺少 smtp_host / to / from_ 中任意项时跳过（默认关闭的安全兜底）。"""
        with mock.patch("smtplib.SMTP_SSL") as smtp:
            send_mail(_result(), smtp_config={"smtp_host": "h"})  # 缺 to/from
        smtp.assert_not_called()

    def test_build_body_includes_report(self):
        """_build_body 拼接汇总表（空 entries 时无诊断段）。"""
        self.assertIn("脚本运行状况汇总报告", _build_body(_result()))

    def test_sends_via_ssl(self):
        """完整配置 + use_ssl 默认 True：经 SMTP_SSL 发送。"""
        cfg = {
            "smtp_host": "smtp.example.com",
            "smtp_port": 465,
            "to": "a@b.com",
            "from_": "me@b.com",
            "subject": "运行汇总",
        }
        with mock.patch("smtplib.SMTP_SSL") as smtp_cls:
            send_mail(_result(), smtp_config=cfg)
        smtp_cls.assert_called_once_with("smtp.example.com", 465, timeout=10)
        server = smtp_cls.return_value.__enter__.return_value
        server.sendmail.assert_called_once()

    def test_sends_via_plain_smtp(self):
        """use_ssl=False：经明文 smtplib.SMTP 发送。"""
        cfg = {
            "smtp_host": "h",
            "smtp_port": 25,
            "to": "a@b.com",
            "from_": "me@b.com",
            "use_ssl": False,
        }
        with mock.patch("smtplib.SMTP") as smtp_cls:
            send_mail(_result(), smtp_config=cfg)
        smtp_cls.assert_called_once_with("h", 25, timeout=10)


if __name__ == "__main__":
    unittest.main()
