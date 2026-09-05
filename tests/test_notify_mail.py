"""测试 src/log/notify_mail.py：send_mail 默认关闭、smtplib 发送与 keyring 取密。"""

import unittest
from email.header import decode_header, make_header
from unittest import mock

from src.log.monitor import ScriptLogStatus
from src.log.notify_mail import _build_body, _build_html, send_mail


def _result(*, notify=("demo",), entries=()) -> dict:
    """最小 parse_logs 产物；notify 为非空列表表示存在报错脚本。

    Args:
        notify: 报错脚本列表；传空元组表示「本次全成功」，用于验证仍发汇总邮件。
        entries: 各脚本解析结果（含 display_name / result），供表格与诊断段消费。

    Returns:
        最小 result dict。
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
    """send_mail：默认关闭、enabled 闸门、无论成败均发送、经 smtplib+keyring 发送。"""

    def setUp(self):
        # 冻结 smtplib.SMTP_SSL 与 keyring，避免测试触碰真实网络/系统凭据管理器。
        self.smtp_cls = mock.patch("smtplib.SMTP_SSL").start()
        self.get_pw = mock.patch("keyring.get_password", return_value=None).start()
        self.set_pw = mock.patch("keyring.set_password", return_value=None).start()

    def tearDown(self):
        mock.patch.stopall()

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
        send_mail(_result(), smtp_config=None)
        self.smtp_cls.assert_not_called()

    def test_disabled_when_enabled_false(self):
        """enabled=false：即便 email 齐全也跳过。"""
        send_mail(
            _result(),
            smtp_config={"enabled": False, "email": "a@qq.com"},
        )
        self.smtp_cls.assert_not_called()

    def test_skips_incomplete_config(self):
        """enabled=true 但 email 缺失：跳过（默认关闭的安全兜底）。"""
        send_mail(
            _result(),
            smtp_config={"enabled": True, "email": ""},
        )
        self.smtp_cls.assert_not_called()

    def test_password_missing_skips(self):
        """keyring 与 schedule.yml 均无授权码：跳过发送（不建连）。"""
        send_mail(
            _result(),
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
        _, smtp = self._sent(_result(notify=()), cfg, keyring_password="authcode")
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
            _result(notify=("demo", "arknights")), cfg, keyring_password="authcode"
        )
        smtp.send_message.assert_called_once()
        subject = self._decode_subject(smtp.send_message.call_args.args[0])
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

    def test_password_from_keyring(self):
        """keyring 存有授权码且 schedule.yml 无 password：仍发送（keyring 优先路径）。"""
        cfg = {
            "enabled": True,
            "email": "123456@qq.com",
            "smtp_host": "smtp.qq.com",
            "smtp_port": 465,
        }
        _, smtp = self._sent(_result(), cfg, keyring_password="vaultcode")
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
            _result(notify=("demo", "arknights")), cfg, keyring_password="authcode"
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
        self._sent(_result(), cfg, keyring_password="authcode")
        self.smtp_cls.assert_not_called()

    def test_sends_custom_smtp_host_port(self):
        """smtp_host/smtp_port 覆盖默认 QQ 服务商。"""
        cfg = {
            "enabled": True,
            "email": "u@163.com",
            "smtp_host": "smtp.163.com",
            "smtp_port": 465,
        }
        smtp_cls, _ = self._sent(_result(), cfg, keyring_password="pw")
        self.assertEqual(smtp_cls.call_args.args, ("smtp.163.com", 465))

    def test_skips_when_smtp_port_non_numeric(self):
        """enabled=true 且授权码齐全，但 smtp_port 非数字：运行期校验失败、跳过发送、不抛异常。"""
        cfg = {
            "enabled": True,
            "email": "u@qq.com",
            "smtp_host": "smtp.qq.com",
            "smtp_port": "not-a-number",
        }
        self._sent(_result(), cfg, keyring_password="pw")
        self.smtp_cls.assert_not_called()

    def test_skips_when_smtp_port_nonpositive(self):
        """smtp_port=0 视为非法端口，跳过发送。"""
        cfg = {
            "enabled": True,
            "email": "u@qq.com",
            "smtp_host": "smtp.qq.com",
            "smtp_port": 0,
        }
        self._sent(_result(), cfg, keyring_password="pw")
        self.smtp_cls.assert_not_called()


if __name__ == "__main__":
    unittest.main()
