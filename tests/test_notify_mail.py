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


class TestCollectFailedDetails(unittest.TestCase):
    """测试失败详情收集：从 config.yml 反查 script_path 再补取日志内容。"""

    def test_collect_failed_details_lookup_and_parse(self):
        tmp = tempfile.mkdtemp()
        cfg_dir = os.path.join(tmp, "config")
        os.makedirs(cfg_dir, exist_ok=True)
        with open(os.path.join(cfg_dir, "config.yml"), "w", encoding="utf-8") as f:
            yaml.safe_dump(
                {
                    "script_list": [
                        {"display_name": "崩铁", "script_path": "D:/fake/star.exe"},
                        {"display_name": "原神", "script_path": "D:/fake/bgi.exe"},
                    ]
                },
                f,
            )
        orig = collect_log._get_root_dir
        collect_log._get_root_dir = lambda: tmp  # type: ignore[assignment]
        try:
            with mock.patch.object(
                collect_log,
                "parse_log",
                return_value={
                    "status": "Failed",
                    "log_path": "D:/fake/log.txt",
                    "log_content": "ERROR: boom",
                },
            ) as parse:
                details = notify_mail._collect_failed_details(["崩铁", "原神"])
        finally:
            collect_log._get_root_dir = orig

        # 按 config.yml 中反查到的 script_path 逐个 parse
        self.assertEqual(
            [call.args[0] for call in parse.call_args_list], ["崩铁", "原神"]
        )
        self.assertEqual(
            [call.args[1] for call in parse.call_args_list],
            ["D:/fake/star.exe", "D:/fake/bgi.exe"],
        )
        self.assertEqual(details[0]["display_name"], "崩铁")
        self.assertEqual(details[0]["log_content"], "ERROR: boom")

    def test_collect_failed_details_no_log_result(self):
        """NO_LOG 结果（无 log_content 键）→ log_content 置空串，不抛 KeyError。"""
        tmp = tempfile.mkdtemp()
        cfg_dir = os.path.join(tmp, "config")
        os.makedirs(cfg_dir, exist_ok=True)
        with open(os.path.join(cfg_dir, "config.yml"), "w", encoding="utf-8") as f:
            yaml.safe_dump(
                {
                    "script_list": [
                        {"display_name": "崩铁", "script_path": "D:/fake/star.exe"}
                    ]
                },
                f,
            )
        orig = collect_log._get_root_dir
        collect_log._get_root_dir = lambda: tmp  # type: ignore[assignment]
        try:
            with mock.patch.object(
                collect_log,
                "parse_log",
                return_value={"status": "NoLog", "log_path": None},
            ):
                details = notify_mail._collect_failed_details(["崩铁"])
        finally:
            collect_log._get_root_dir = orig

        self.assertEqual(details[0]["status"], "NoLog")
        self.assertIsNone(details[0]["log_path"])
        self.assertEqual(details[0]["log_content"], "")

    def test_collect_failed_details_config_missing_returns_empty(self):
        """config.yml 不存在时告警并返回空列表，不抛异常（通知环节不中断）。"""
        tmp = tempfile.mkdtemp()  # 无 config/config.yml
        orig = collect_log._get_root_dir
        collect_log._get_root_dir = lambda: tmp  # type: ignore[assignment]
        try:
            details = notify_mail._collect_failed_details(["崩铁"])
        finally:
            collect_log._get_root_dir = orig
        self.assertEqual(details, [])


class TestBuildSubjectBody(unittest.TestCase):
    """测试邮件标题与正文构造。"""

    def test_build_subject_lists_failures(self):
        subject = notify_mail._build_subject(["崩铁", "原神"])
        self.assertIn("崩铁", subject)
        self.assertIn("原神", subject)

    def test_build_body_includes_log_path_and_content(self):
        body = notify_mail._build_body(
            [
                {
                    "display_name": "崩铁",
                    "status": "Failed",
                    "log_path": "D:/fake/log.txt",
                    "log_content": "ERROR: boom",
                }
            ]
        )
        self.assertIn("运行日期", body)
        self.assertIn("崩铁", body)
        self.assertIn("Failed", body)
        self.assertIn("D:/fake/log.txt", body)
        self.assertIn("ERROR: boom", body)

    def test_build_body_no_log_path_omits_log_line(self):
        """NO_LOG 结果（log_path 为 None）不应输出「日志:」行。"""
        body = notify_mail._build_body(
            [
                {
                    "display_name": "崩铁",
                    "status": "NoLog",
                    "log_path": None,
                    "log_content": "",
                }
            ]
        )
        self.assertIn("崩铁", body)
        self.assertNotIn("日志:", body)

    def test_build_body_collapses_repeated_lines(self):
        """邮件正文中的日志尾部应折叠连续重复行，避免刷屏占满内容。"""
        body = notify_mail._build_body(
            [
                {
                    "display_name": "崩铁",
                    "status": "Failed",
                    "log_path": "D:/fake/log.txt",
                    "log_content": "FeatureSet:load\nFeatureSet:load\nFeatureSet:load\nERROR: boom",
                }
            ]
        )
        self.assertIn("FeatureSet:load（重复 3 次）", body)
        self.assertIn("ERROR: boom", body)
        # 折叠后只出现一次折叠行 + 一个错误行
        self.assertEqual(body.count("FeatureSet:load"), 1)


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
            mock.patch.object(collect_log, "parse_logs", return_value=[]),
            mock.patch.object(notify_mail, "_send_mail") as send,
        ):
            notify_mail.notify_failed_games()
        send.assert_not_called()

    def test_notify_failed_games_skips_when_config_missing(self):
        """有失败但邮件配置缺失时跳过发送。"""
        with (
            mock.patch.object(collect_log, "parse_logs", return_value=["崩铁"]),
            mock.patch.object(notify_mail, "_load_mail_config", return_value=None),
            mock.patch.object(notify_mail, "_send_mail") as send,
        ):
            notify_mail.notify_failed_games()
        send.assert_not_called()

    def test_notify_failed_games_sends_mail(self):
        """有失败且配置齐全时发送，主题含失败游戏名。"""
        with (
            mock.patch.object(collect_log, "parse_logs", return_value=["崩铁"]),
            mock.patch.object(
                notify_mail,
                "_load_mail_config",
                return_value={"email": "a@qq.com", "password": "code"},
            ),
            mock.patch.object(
                notify_mail,
                "_collect_failed_details",
                return_value=[
                    {
                        "display_name": "崩铁",
                        "status": "Failed",
                        "log_path": "D:/fake/log.txt",
                        "log_content": "ERROR: boom",
                    }
                ],
            ),
            mock.patch.object(notify_mail, "_send_mail", return_value=True) as send,
        ):
            notify_mail.notify_failed_games()
        send.assert_called_once()
        args = send.call_args.args
        self.assertEqual(args[0], "a@qq.com")
        self.assertEqual(args[1], "code")
        self.assertIn("崩铁", args[2])


if __name__ == "__main__":
    unittest.main()
