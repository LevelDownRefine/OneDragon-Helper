"""测试 src/log/notify_mail.py：send_mail 默认关闭、SMTP 接口与正文拼接。"""

import unittest
from email import message_from_string
from email.header import decode_header, make_header
from unittest import mock

from src.log.monitor import ScriptLogStatus
from src.log.notify_mail import _build_body, _build_html, send_mail


def _decode_subject(sendmail_args) -> str:
    """从 sendmail 的入参里解出 RFC 2047 编码的主题（中文主题会被 base64 编码）。

    Args:
        sendmail_args: ``server.sendmail.call_args`` 的 args 元组，下标 2 为完整报文。

    Returns:
        解码后的主题字符串。
    """
    raw = message_from_string(sendmail_args[2])["Subject"]
    return str(make_header(decode_header(raw)))


def _result(*, notify=("demo",), entries=()) -> dict:
    """最小 parse_logs 产物；notify 为非空列表表示存在报错脚本。

    Args:
        notify: 报错脚本列表；传空元组表示「本次全成功」，用于验证仍发汇总邮件。
        entries: 各脚本解析结果（含 display_name / result），供表格与诊断段消费。
    """
    return {
        "report": "脚本运行状况汇总报告",
        "entries": list(entries),
        "notify": list(notify),
        "rerun": [],
    }


def _entry(name: str, status: str, *, errors=(), stamina=None) -> dict:
    """构造一条脚本解析结果，字段与 monitor.parse_logs 的 entries 一致。

    Args:
        name: 展示名。
        status: ScriptLogStatus 状态值。
        errors: 报错行列表。
        stamina: 剩余体力；None 表示日志无体力。

    Returns:
        单个 entry dict。
    """
    return {
        "display_name": name,
        "result": {
            "status": status,
            "stamina": stamina,
            "daily_done": status == ScriptLogStatus.SUCCESS,
            "errors": list(errors),
            "log_content": "",
            "log_path": None,
        },
    }


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
        self.assertIn("脚本运行状况汇总报告", _build_body(_result(), ""))

    def test_build_html_uses_real_table(self):
        """HTML 正文用真 <table> 呈现汇总表（不依赖等宽字体，比例字体下仍对齐）。"""
        entries = (_entry("崩铁", ScriptLogStatus.FAILED, errors=("ERROR x",)),)
        html_body = _build_html(_result(entries=entries), "")
        self.assertIn("<table", html_body)
        self.assertIn("<th>每日状态</th>", html_body)
        self.assertIn("<td>崩铁</td>", html_body)
        self.assertIn("<td>失败</td>", html_body)

    def test_build_html_escapes_cells(self):
        """单元格内容经 html.escape，脚本名含标记字符也不会破坏表格结构。"""
        entries = (_entry("<script>x</script>", ScriptLogStatus.SUCCESS),)
        html_body = _build_html(_result(entries=entries), "")
        self.assertNotIn("<script>x</script>", html_body)
        self.assertIn("&lt;script&gt;", html_body)

    def test_build_html_counts_line_without_stale_actions(self):
        """HTML 统计行与表格同源；不再出现已过期的「将重跑 / 将通知」。

        邮件在重跑之后发送，该行语义已失效；且改判据后重跑集合即非成功行、通知集合
        即报错非零行，均与表格本身冗余。
        """
        entries = (
            _entry("崩铁", ScriptLogStatus.FAILED, errors=("ERROR x",)),
            _entry("鸣潮", ScriptLogStatus.SUCCESS, stamina="180"),
        )
        html_body = _build_html(_result(entries=entries), "")
        self.assertIn("总计: 2 个脚本 | 成功: 1 | 失败: 1 | 无日志: 0", html_body)
        self.assertNotIn("将重跑", html_body)
        self.assertNotIn("将通知", html_body)

    def test_sends_multipart_alternative(self):
        """正文为 multipart/alternative：plain 在前、html 在后（后者优先展示）。"""
        cfg = {"enabled": True, "email": "123456@qq.com", "password": "authcode"}
        with mock.patch("smtplib.SMTP_SSL") as smtp_cls:
            send_mail(_result(), smtp_config=cfg)
        server = smtp_cls.return_value.__enter__.return_value
        msg = message_from_string(server.sendmail.call_args[0][2])
        self.assertEqual(msg.get_content_type(), "multipart/alternative")
        self.assertEqual(
            [part.get_content_type() for part in msg.get_payload()],
            ["text/plain", "text/html"],
        )

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
