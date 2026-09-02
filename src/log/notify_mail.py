"""邮件通知：消费 monitor.parse_logs 产出的 report/entries/notify，经 QQ SMTP 发送运行汇总。

默认关闭：未配置 ``notify`` 段、``enabled`` 非 true、或 email/password 缺失时直接跳过。
邮件在链运行结束后始终发送（含全成功）：有报错时主题标注『脚本运行报错:<脚本名>』，
全成功时标注『脚本运行汇总』。QQ 邮箱约定——收发同号（自己发给自己）。

正文为 ``multipart/alternative``：HTML 部分用真 ``<table>``（不依赖等宽字体，比例字体
下仍对齐），纯文本部分沿用等宽空格填充的汇总表，供纯文本客户端与控制台复用。
"""

import html
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from src.log.monitor import (
    format_diagnostic_sections,
    summary_counts_line,
    summary_table_rows,
)

logger = logging.getLogger(__name__)

# QQ 邮箱 SMTP（收发同号，自己发给自己）；参考 OneDragon-ScriptChainer 的服务表。
_SMTP_HOST = "smtp.qq.com"
_SMTP_PORT = 465
# socket 超时：防止 SMTP 连接挂起时脚本无限阻塞、被 runner 按 run_timeout 强杀
_SMTP_TIMEOUT_SECONDS = 10
_SUBJECT_PREFIX = "[OneDragon-Helper] "


def send_mail(result: dict, *, smtp_config: dict | None = None) -> None:
    """发送运行汇总邮件（默认关闭；开启后无论成败均发送）。

    Args:
        result: ``monitor.parse_logs`` 的返回值（含 ``report`` / ``entries`` / ``notify``）。
        smtp_config: ``schedule.yml`` 的 ``notify`` 段；需 ``enabled=true`` 且
            ``email``/``password`` 齐全才发送，否则跳过（默认关闭）。
    """
    if not smtp_config or not smtp_config.get("enabled", False):
        return
    email = (smtp_config.get("email") or "").strip()
    password = (smtp_config.get("password") or "").strip()
    if not email or not password:
        logger.warning("[mail] 邮件未启用或 email/password 缺失，跳过: %s", smtp_config)
        return
    # 始终发送汇总邮件：无论成败均回报本次运行结果。
    # 有报错时主题带报错脚本名，全成功时标注『脚本运行汇总』。
    notify_list = result.get("notify") or []
    if notify_list:
        subject = f"{_SUBJECT_PREFIX}脚本运行报错: {'、'.join(notify_list)}"
    else:
        subject = f"{_SUBJECT_PREFIX}脚本运行汇总"
    # 诊断段两版正文共用，只算一次（日志尾部可能很长）。
    diagnostic = format_diagnostic_sections(result.get("entries", []))
    body = _build_body(result, diagnostic)
    html_body = _build_html(result, diagnostic)
    _send(email, password, email, email, subject, body, html_body)


def _build_body(result: dict, diagnostic: str) -> str:
    """拼接邮件正文（纯文本）：汇总表 + 各脚本诊断明细（报错信息在前、日志尾部在后）。

    Args:
        result: ``monitor.parse_logs`` 的返回值（用其 ``report`` 汇总表文本）。
        diagnostic: 已算好的诊断文本；空串表示不附加该段。

    Returns:
        纯文本正文。
    """
    report = result.get("report", "")
    return report + ("\n\n" + diagnostic if diagnostic else "")


def _build_html(result: dict, diagnostic: str) -> str:
    """拼接邮件正文（HTML）：真 <table> 汇总表 + 统计行 + 诊断明细 <pre>。

    表格由渲染器排版，故不依赖等宽字体、不受 CJK 双宽与 tabstop 影响。

    Args:
        result: ``monitor.parse_logs`` 的返回值（用其 ``entries`` 构造表格）。
        diagnostic: 已算好的诊断文本；空串表示不附加该段。

    Returns:
        HTML 正文。
    """
    entries = result.get("entries", [])
    headers, rows = summary_table_rows(entries)
    head_cells = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    body_rows = "".join(
        "<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in row) + "</tr>"
        for row in rows
    )
    parts = [
        '<html><head><meta charset="utf-8"></head><body>',
        "<h3>脚本运行状况汇总报告</h3>",
        '<table border="1" cellspacing="0" cellpadding="4"'
        ' style="border-collapse:collapse">',
        f"<tr>{head_cells}</tr>{body_rows}",
        "</table>",
        f"<p>{html.escape(summary_counts_line(entries))}</p>",
    ]
    if diagnostic:
        parts.append(f"<pre>{html.escape(diagnostic)}</pre>")
    parts.append("</body></html>")
    return "\n".join(parts)


def _send(
    user: str,
    password: str,
    from_addr: str,
    to_addr: str,
    subject: str,
    body: str,
    html_body: str,
) -> None:
    """经 QQ SMTP_SSL 发送邮件（收发同号）；正文为 plain/html 的 alternative。"""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    # alternative 按「越靠后越优先」选取，故 plain 先、html 后：纯文本客户端只读得到
    # 前者，支持 HTML 的客户端展示后者（表格由渲染器排版，不依赖等宽字体）。
    msg.attach(MIMEText(body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    with smtplib.SMTP_SSL(
        _SMTP_HOST, _SMTP_PORT, timeout=_SMTP_TIMEOUT_SECONDS
    ) as server:
        server.login(user, password)
        server.sendmail(from_addr, [to_addr], msg.as_string())
