"""测试失败邮件通知脚本（mock SMTP 与 collect_log，不真正发信）。"""

import email.message
import os
import sys
import tempfile
import unittest
from unittest import mock

import yaml

# scripts/ 位于项目根（非 src/ 下），追加 scripts/ 到 sys.path 以便扁平导入。
sys.path.append(
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
)

import collect_log
import notify_mail


class TestLoadMailConfig(unittest.TestCase):
    """测试 SMTP 配置读取：缺失 / 字段不全 / 完整三种情况。"""

    def _write_mail_config(self, tmp: str, data: dict) -> None:
        cfg_dir = os.path.join(tmp, "config")
        os.makedirs(cfg_dir, exist_ok=True)
        with open(os.path.join(cfg_dir, "notify_mail.yml"), "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f)

    def test_load_mail_config_missing_file_returns_none(self):
        """notify_mail.yml 不存在时返回 None（仅告警，不抛异常）。"""
        tmp = tempfile.mkdtemp()
        orig = collect_log._get_root_dir
        collect_log._get_root_dir = lambda: tmp  # type: ignore[assignment]
        try:
            self.assertIsNone(notify_mail._load_mail_config())
        finally:
            collect_log._get_root_dir = orig

    def test_load_mail_config_missing_fields_returns_none(self):
        """缺 email 或缺 password 时返回 None（用户可能未填）。"""
        for data in ({"email": "a@qq.com"}, {"password": "code"}, {}):
            tmp = tempfile.mkdtemp()
            self._write_mail_config(tmp, data)
            orig = collect_log._get_root_dir
            collect_log._get_root_dir = lambda t=tmp: t  # type: ignore[assignment]
            try:
                self.assertIsNone(notify_mail._load_mail_config())
            finally:
                collect_log._get_root_dir = orig

    def test_load_mail_config_ok(self):
        """email/password 齐全时返回配置 dict。"""
        tmp = tempfile.mkdtemp()
        self._write_mail_config(tmp, {"email": "a@qq.com", "password": "secret"})
        orig = collect_log._get_root_dir
        collect_log._get_root_dir = lambda: tmp  # type: ignore[assignment]
        try:
            config = notify_mail._load_mail_config()
        finally:
            collect_log._get_root_dir = orig
        self.assertEqual(config, {"email": "a@qq.com", "password": "secret"})


class TestBuildSubjectBody(unittest.TestCase):
    """测试邮件标题与正文构造。"""

    def test_build_subject_lists_failures(self):
        subject = notify_mail._build_subject(["崩铁", "原神"])
        self.assertIn("崩铁", subject)
        self.assertIn("原神", subject)

    def test_build_body_includes_report_and_diagnostic(self):
        """邮件正文应含运行日期、整表汇总表格，以及复用的诊断文本。"""
        body = notify_mail._build_body("脚本运行状况汇总表格", "各脚本报错明细\n...")
        self.assertIn("运行日期", body)
        self.assertIn("脚本运行状况汇总表格", body)
        self.assertIn("各脚本报错明细", body)

    def test_build_body_empty_diagnostic_shows_no_error_note(self):
        """无诊断文本（无报错脚本）时正文给出「本次无脚本报错」提示。"""
        body = notify_mail._build_body("脚本运行状况汇总表格", "")
        self.assertIn("本次无脚本报错", body)


class TestDiagnosticSections(unittest.TestCase):
    """测试诊断文本生成：复用 collect_log._format_diagnostic_sections（报错信息在前、日志尾部在后）。"""

    def _entry(self, display_name, status, errors, log_content="", log_path="D:/x.log"):
        return {
            "script_name": display_name,
            "display_name": display_name,
            "result": {
                "status": status,
                "log_path": log_path,
                "log_content": log_content,
                "errors": errors,
            },
        }

    def test_diagnostic_sections_two_sections_in_order(self):
        """报错信息（各脚本报错）整体位于日志尾部之前；两段均含报错脚本。"""
        entries = [
            self._entry("崩铁", "Failed", ["ERROR: boom"], "tail-A"),
            self._entry("原神", "Success", ["WARNING: 未领取"], "tail-B"),
            self._entry("鸣潮", "Success", [], "tail-C"),  # 无报错，不出现
        ]
        text = collect_log._format_diagnostic_sections(entries)
        self.assertIn("各脚本报错明细", text)
        self.assertIn("各脚本日志尾部", text)
        self.assertIn("ERROR: boom", text)
        self.assertIn("WARNING: 未领取", text)
        # 日志尾部仅 FAILED：崩铁(Failed) 的尾部出现，原神(Success+报错→WARN) 不出现。
        self.assertIn("tail-A", text)
        self.assertNotIn("tail-B", text)
        self.assertNotIn("tail-C", text)  # 无报错脚本不进入诊断
        self.assertLess(text.index("各脚本报错明细"), text.index("各脚本日志尾部"))

    def test_diagnostic_sections_collapses_repeated_lines(self):
        """传入 collapse_fn 时，日志尾部连续重复行被折叠。"""
        entries = [
            self._entry(
                "崩铁", "Failed", ["ERROR: boom"],
                "FeatureSet:load\nFeatureSet:load\nFeatureSet:load\nERROR: boom",
            )
        ]
        text = collect_log._format_diagnostic_sections(
            entries, collapse_fn=notify_mail._collapse_repeated_lines
        )
        self.assertIn("FeatureSet:load（重复 3 次）", text)
        self.assertIn("ERROR: boom", text)

    def test_diagnostic_sections_empty_when_no_errors(self):
        """无任何报错脚本时返回空字符串，邮件/控制台均不输出诊断段。"""
        entries = [self._entry("鸣潮", "Success", []), self._entry("原神", "NoLog", [])]
        self.assertEqual(collect_log._format_diagnostic_sections(entries), "")

    def test_warn_only_gets_error_detail_not_tail(self):
        """WARN（成功但有报错）脚本进入报错明细，但日志尾部段整体不出现（仅 FAILED 才有）。"""
        entries = [self._entry("原神", "Success", ["WARNING: 未领取"], "tail-only")]
        text = collect_log._format_diagnostic_sections(entries)
        self.assertIn("各脚本报错明细", text)
        self.assertIn("WARNING: 未领取", text)
        self.assertNotIn("各脚本日志尾部", text)
        self.assertNotIn("tail-only", text)

    def test_failed_without_errors_gets_tail_only(self):
        """FAILED 但无显式报错行的脚本仍进入日志尾部（辅助排查），报错明细段不出现。"""
        entries = [self._entry("崩铁", "Failed", [], "tail-failed")]
        text = collect_log._format_diagnostic_sections(entries)
        self.assertIn("各脚本日志尾部", text)
        self.assertIn("tail-failed", text)
        self.assertNotIn("各脚本报错明细", text)


class TestCollapseRepeatedLines(unittest.TestCase):
    """测试连续重复行折叠。"""

    def test_collapse_consecutive_duplicates(self):
        self.assertEqual(
            notify_mail._collapse_repeated_lines("a\na\na\nb"),
            "a（重复 3 次）\nb",
        )

    def test_keep_non_consecutive_duplicates(self):
        """非连续重复行不折叠（保真）。"""
        self.assertEqual(
            notify_mail._collapse_repeated_lines("a\nb\na"),
            "a\nb\na",
        )

    def test_single_line_unchanged(self):
        self.assertEqual(notify_mail._collapse_repeated_lines("a"), "a")

    def test_empty_text_unchanged(self):
        self.assertEqual(notify_mail._collapse_repeated_lines(""), "")


class TestSendMail(unittest.TestCase):
    """测试 SMTP 发送：成功与失败分支（mock smtplib）。"""

    def test_send_mail_success(self):
        server = mock.MagicMock()
        with mock.patch.object(notify_mail.smtplib, "SMTP_SSL", return_value=server):
            ok = notify_mail._send_mail("a@qq.com", "code", "主题", "正文")
        self.assertTrue(ok)
        server.login.assert_called_once_with("a@qq.com", "code")
        server.sendmail.assert_called_once()
        server.close.assert_called_once()

    def test_send_mail_passes_timeout_and_message(self):
        """SMTP_SSL 应带 timeout 调用，且发出的邮件内容含标题与正文（可解码）。"""
        server = mock.MagicMock()
        with mock.patch.object(
            notify_mail.smtplib, "SMTP_SSL", return_value=server
        ) as cls:
            ok = notify_mail._send_mail("a@qq.com", "code", "失败通知", "正文内容")
        self.assertTrue(ok)

        self.assertEqual(
            cls.call_args.kwargs["timeout"], notify_mail._SMTP_TIMEOUT_SECONDS
        )
        # sendmail(from_addr, to_addr, bytes)：收发同号
        self.assertEqual(server.sendmail.call_args.args[0], "a@qq.com")
        self.assertEqual(server.sendmail.call_args.args[1], "a@qq.com")

        raw = server.sendmail.call_args.args[2]
        msg = email.message_from_bytes(raw)
        subject_parts = email.header.decode_header(msg["Subject"])
        decoded_subject = "".join(
            part.decode(charset or "utf-8") if isinstance(part, bytes) else part
            for part, charset in subject_parts
        )
        self.assertEqual(decoded_subject, "失败通知")
        self.assertIn("正文内容", msg.get_payload(decode=True).decode("utf-8"))

    def test_send_mail_failure_returns_false(self):
        """SMTP 连接/认证/发送异常时返回 False 且告警，不抛异常。"""
        with (
            mock.patch.object(
                notify_mail.smtplib,
                "SMTP_SSL",
                side_effect=Exception("boom"),
            ),
            mock.patch.object(notify_mail.logger, "exception") as exc,
        ):
            ok = notify_mail._send_mail("a@qq.com", "code", "主题", "正文")
        self.assertFalse(ok)
        exc.assert_called_once()


class TestNotifyFailedGames(unittest.TestCase):
    """测试编排：先 collect_log 分析，有失败才发信。"""

    def test_notify_failed_games_noop_when_no_failures(self):
        """无失败脚本时不发信。"""
        with (
            mock.patch.object(
                collect_log, "parse_logs", return_value={"rerun": [], "notify": [], "entries": []}
            ),
            mock.patch.object(notify_mail, "_send_mail") as send,
        ):
            notify_mail.notify_failed_games()
        send.assert_not_called()

    def test_notify_failed_games_skips_when_config_missing(self):
        """有失败但邮件配置缺失时跳过发送。"""
        with (
            mock.patch.object(
                collect_log,
                "parse_logs",
                return_value={"rerun": [], "notify": ["崩铁"], "report": "", "entries": []},
            ),
            mock.patch.object(notify_mail, "_load_mail_config", return_value=None),
            mock.patch.object(notify_mail, "_send_mail") as send,
        ):
            notify_mail.notify_failed_games()
        send.assert_not_called()

    def test_notify_failed_games_sends_mail(self):
        """有失败且配置齐全时发送，正文复用诊断文本（报错信息在前、日志尾部在后）。"""
        with (
            mock.patch.object(
                collect_log,
                "parse_logs",
                return_value={
                    "rerun": [],
                    "notify": ["崩铁"],
                    "report": "脚本运行状况汇总表格\n崩铁 失败 ...",
                    "entries": [
                        {
                            "script_name": "崩铁",
                            "display_name": "崩铁",
                            "result": {
                                "status": "Failed",
                                "log_path": "D:/fake/log.txt",
                                "log_content": "ERROR: boom",
                                "errors": ["ERROR: boom"],
                            },
                        }
                    ],
                },
            ),
            mock.patch.object(
                notify_mail,
                "_load_mail_config",
                return_value={"email": "a@qq.com", "password": "code"},
            ),
            mock.patch.object(notify_mail, "_send_mail", return_value=True) as send,
        ):
            notify_mail.notify_failed_games()
        send.assert_called_once()
        args = send.call_args.args
        self.assertEqual(args[0], "a@qq.com")
        self.assertEqual(args[1], "code")
        self.assertIn("崩铁", args[2])
        # 正文应包含整张汇总表格（report）。
        self.assertIn("脚本运行状况汇总表格", args[3])
        # 正文应复用诊断文本：两段结构、报错信息在日志尾部之前。
        body = args[3]
        self.assertIn("各脚本报错明细", body)
        self.assertIn("各脚本日志尾部", body)
        self.assertIn("ERROR: boom", body)
        self.assertLess(body.index("各脚本报错明细"), body.index("各脚本日志尾部"))


if __name__ == "__main__":
    unittest.main()
