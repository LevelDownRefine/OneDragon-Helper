"""邮件通知：消费 monitor.parse_logs 产出的 notify/report/entries，经 SMTP 发送运行汇总。

默认关闭：未提供 ``smtp_config`` 或配置不完整时直接跳过（调用方按 config 决定是否启用）。
"""

import logging
import smtplib
from email.mime.text import MIMEText

from src.log.monitor import _format_diagnostic_sections

logger = logging.getLogger(__name__)


def send_mail(result: dict, *, smtp_config: dict | None = None) -> None:
    """发送运行汇总邮件（默认关闭）。

    Args:
        result: ``monitor.parse_logs`` 的返回值（含 ``report`` / ``entries`` / ``notify``）。
        smtp_config: SMTP 配置 dict，键含 ``smtp_host`` / ``smtp_port`` / ``smtp_user`` /
            ``smtp_pass`` / ``to`` / ``from_`` / ``subject`` / ``use_ssl``；
            为 None 或缺少 ``smtp_host`` / ``to`` / ``from_`` 时跳过（默认关闭）。
    """
    if not smtp_config:
        return
    host = smtp_config.get("smtp_host")
    to_addr = smtp_config.get("to")
    from_addr = smtp_config.get("from_") or smtp_config.get("from")
    if not host or not to_addr or not from_addr:
        logger.warning("[mail] SMTP 配置不完整，跳过邮件通知: %s", smtp_config)
        return
    body = _build_body(result)
    _send(smtp_config, from_addr, to_addr, body)


def _build_body(result: dict) -> str:
    """拼接邮件正文：汇总表 + 各脚本诊断明细（报错信息在前、日志尾部在后）。"""
    diagnostic = _format_diagnostic_sections(result.get("entries", []))
    report = result.get("report", "")
    return report + ("\n\n" + diagnostic if diagnostic else "")


def _send(
    smtp_config: dict, from_addr: str, to_addr: str, body: str
) -> None:
    """经 SMTP 发送纯文本邮件；use_ssl=True 用 SMTP_SSL，否则用明文 SMTP。"""
    host = smtp_config.get("smtp_host")
    port = smtp_config.get("smtp_port", 465)
    user = smtp_config.get("smtp_user")
    password = smtp_config.get("smtp_pass")
    subject = smtp_config.get("subject", "脚本链运行汇总")
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    use_ssl = smtp_config.get("use_ssl", True)
    if use_ssl:
        with smtplib.SMTP_SSL(host, port, timeout=10) as server:
            if user and password:
                server.login(user, password)
            server.sendmail(from_addr, [to_addr], msg.as_string())
    else:
        with smtplib.SMTP(host, port, timeout=10) as server:
            if user and password:
                server.login(user, password)
            server.sendmail(from_addr, [to_addr], msg.as_string())
