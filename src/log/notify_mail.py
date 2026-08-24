"""邮件通知：消费 monitor.parse_logs 产出的 report/entries/notify，经 QQ SMTP 发送运行汇总。

默认关闭：未配置 ``notify`` 段、``enabled`` 非 true、或 email/password 缺失时直接跳过。
仅在有失败脚本时发送（``notify`` 列表为空即「本次无报错」，不发），沿用旧
notify_mail.yml 的「仅失败才通知」语义。QQ 邮箱约定——收发同号（自己发给自己）。
"""

import logging
import smtplib
from email.mime.text import MIMEText

from src.log.monitor import _format_diagnostic_sections

logger = logging.getLogger(__name__)

# QQ 邮箱 SMTP（收发同号，自己发给自己）；参考 OneDragon-ScriptChainer 的服务表。
_SMTP_HOST = "smtp.qq.com"
_SMTP_PORT = 465
# socket 超时：防止 SMTP 连接挂起时脚本无限阻塞、被 runner 按 run_timeout 强杀
_SMTP_TIMEOUT_SECONDS = 10
_DEFAULT_SUBJECT_PREFIX = "[OneDragon-Helper] 脚本运行报错: "


def send_mail(result: dict, *, smtp_config: dict | None = None) -> None:
    """发送运行汇总邮件（默认关闭，且仅失败时发）。

    Args:
        result: ``monitor.parse_logs`` 的返回值（含 ``report`` / ``entries`` / ``notify``）。
        smtp_config: ``config.yml`` 的 ``notify`` 段；需 ``enabled=true`` 且
            ``email``/``password`` 齐全才发送，否则跳过（默认关闭）。
    """
    if not smtp_config or not smtp_config.get("enabled", False):
        return
    email = (smtp_config.get("email") or "").strip()
    password = (smtp_config.get("password") or "").strip()
    if not email or not password:
        logger.warning("[mail] 邮件未启用或 email/password 缺失，跳过: %s", smtp_config)
        return
    # 仅失败才发：notify 为空表示本次无报错脚本，无需通知。
    notify_list = result.get("notify") or []
    if not notify_list:
        logger.info("[mail] 无报错脚本，无需发送邮件")
        return
    subject = _DEFAULT_SUBJECT_PREFIX + "、".join(notify_list)
    body = _build_body(result)
    _send(email, password, email, email, subject, body)


def _build_body(result: dict) -> str:
    """拼接邮件正文：汇总表 + 各脚本诊断明细（报错信息在前、日志尾部在后）。"""
    diagnostic = _format_diagnostic_sections(result.get("entries", []))
    report = result.get("report", "")
    return report + ("\n\n" + diagnostic if diagnostic else "")


def _send(
    user: str,
    password: str,
    from_addr: str,
    to_addr: str,
    subject: str,
    body: str,
) -> None:
    """经 QQ SMTP_SSL 发送纯文本邮件（收发同号）。"""
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    with smtplib.SMTP_SSL(
        _SMTP_HOST, _SMTP_PORT, timeout=_SMTP_TIMEOUT_SECONDS
    ) as server:
        server.login(user, password)
        server.sendmail(from_addr, [to_addr], msg.as_string())
