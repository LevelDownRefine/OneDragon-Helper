"""邮件通知：消费 monitor.parse_logs 产出的 report/entries/notify，经标准库 smtplib 发送运行汇总。

默认关闭：未配置 ``notify`` 段、``enabled`` 非 true、或找不到授权码时直接跳过。
底层用标准库 smtplib（隐式 SSL 端口 465）+ ssl.create_default_context()，不引入额外邮件依赖；
QQ 为默认服务商（收发同号），``smtp_host``/``smtp_port`` 可在 schedule.yml 覆盖以支持其他服务商。
邮件在链运行结束后始终发送（含全成功）：有报错时主题标注『脚本运行报错:<脚本名>』，
全成功时标注『脚本运行汇总』。QQ 邮箱约定——收发同号（自己发给自己）。

授权码存储（避免明文落盘）：
- 仅从系统凭据管理器（Windows 凭据管理器 / macOS Keychain）读取，service=``OneDragon-Helper``；
- 不读 ``schedule.yml`` 明文，故 notify 段不存放、也不该存放授权码；
- 注册入口：``python -m src.log.notify_mail register <email> <授权码>``，
  或供 GUI 调用 :func:`register_credentials`。
正文为 ``multipart/alternative``：HTML 部分用真 ``<table>``（不依赖等宽字体，比例字体
下仍对齐），纯文本部分沿用等宽空格填充的汇总表，供纯文本客户端与控制台复用。
"""

import html
import logging
import smtplib
import ssl
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

try:
    import keyring as _keyring
except ImportError:  # keyring 缺失时无法取授权码（无明文兜底），send_mail 直接跳过
    _keyring = None

from src.log.monitor import (
    format_diagnostic_sections,
    summary_counts_line,
    summary_table_rows,
)

logger = logging.getLogger(__name__)

# keyring 槽位（service 名）：本项目的系统凭据管理器命名空间，与具体邮件库无关。
_KEYRING_SERVICE = "OneDragon-Helper"
# socket 超时：防止 SMTP 连接挂起时脚本无限阻塞、被 runner 按 run_timeout 强杀
_SMTP_TIMEOUT_SECONDS = 10
_SUBJECT_PREFIX = "[OneDragon-Helper] "


def register_credentials(email: str, password: str) -> None:
    """将邮箱授权码存入系统凭据管理器（Windows 凭据管理器 / macOS Keychain / Linux SecretService）。

    授权码存入系统凭据管理器，schedule.yml 的 notify 段不存放授权码。
    存入系统凭据管理器的 service 命名空间为 ``OneDragon-Helper``。

    Args:
        email: 发件人邮箱（同时作为凭据管理器的账号标识）。
        password: QQ 邮箱授权码（16 位，非登录密码）。

    Raises:
        RuntimeError: 运行环境缺少 keyring 依赖时。
    """
    if _keyring is None:
        raise RuntimeError(
            "缺少 keyring 依赖，无法写入系统凭据管理器；请先 `uv add keyring`"
        )
    _keyring.set_password(_KEYRING_SERVICE, email, password)


def _resolve_password(email: str) -> str | None:
    """从系统凭据管理器读取发送用授权码；未存储返回 None（调用方跳过发送）。

    授权码只存于系统凭据管理器（service=``OneDragon-Helper``），不读 schedule.yml 明文，
    故 notify 段不存放、也不该存放授权码。

    Args:
        email: 发件人邮箱（凭据管理器账号标识）。

    Returns:
        授权码；未存储或凭据后端不可用时返回 None。
    """
    if _keyring is None:
        return None
    try:
        return _keyring.get_password(_KEYRING_SERVICE, email)
    except Exception:  # 后端不可用等
        return None


def send_mail(result: dict, *, smtp_config: dict | None = None) -> None:
    """发送运行汇总邮件（默认关闭；开启后无论成败均发送）。

    Args:
        result: ``monitor.parse_logs`` 的返回值（含 ``report`` / ``entries`` / ``notify``）。
    smtp_config: ``schedule.yml`` 的 ``notify`` 段；需 ``enabled=true`` 且系统凭据管理器
        能取到该邮箱授权码才发送，否则跳过（默认关闭）。
    """
    if not smtp_config or not smtp_config.get("enabled", False):
        return
    email = (smtp_config.get("email") or "").strip()
    if not email:
        logger.warning("[mail] 邮件未启用或 email 缺失，跳过: %s", smtp_config)
        return
    password = _resolve_password(email)
    if not password:
        logger.warning("[mail] 未找到授权码（系统凭据管理器无该邮箱记录），跳过发送")
        return
    host = (smtp_config.get("smtp_host") or "").strip()
    raw_port = smtp_config.get("smtp_port")
    # smtp_host/smtp_port 以 schedule.yml 为准（默认 QQ 见 schedule.example.yml），
    # 缺失即视为未配置、跳过发送（与 email 缺失同处理，不静默回落到硬编码默认值）。
    if not host or raw_port in (None, ""):
        logger.warning("[mail] 邮件 smtp_host/smtp_port 未配置，跳过发送")
        return
    # 手改 yml 可能写入非数字/非正端口；运行期校验失败直接跳过（不静默回落、不抛异常中断链）。
    try:
        port = int(raw_port)
    except (TypeError, ValueError):
        logger.warning("[mail] smtp_port 非法(%r)，跳过发送", raw_port)
        return
    if port <= 0:
        logger.warning("[mail] smtp_port 非法(%r)，跳过发送", raw_port)
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
    _send(email, password, email, subject, body, html_body, host=host, port=port)


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
    to_addr: str,
    subject: str,
    body: str,
    html_body: str,
    *,
    host: str,
    port: int,
) -> None:
    """经标准库 smtplib 发送邮件（收发同号）；正文为 plain/html 的 alternative。

    隐式 SSL（端口 465）走 ``smtp.SMTP_SSL`` + ``ssl.create_default_context()``；
    凭证由 keyring 提供（见 :func:`_resolve_password`）。其他服务商经 smtp_host/port 覆盖。
    """
    # alternative 按「越靠后越优先」选取，故 plain 先、html 后：纯文本客户端只读得到
    # 前者，支持 HTML 的客户端展示后者（表格由渲染器排版，不依赖等宽字体）。
    msg = MIMEMultipart("alternative")
    msg["From"] = user
    msg["To"] = to_addr
    msg["Subject"] = Header(subject, "utf-8").encode()
    msg.attach(MIMEText(body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(
        host, port, timeout=_SMTP_TIMEOUT_SECONDS, context=context
    ) as smtp:
        smtp.login(user, password)
        smtp.send_message(msg)


def _main(argv: list[str] | None = None) -> None:
    """命令行入口：管理邮件授权码（需系统凭据管理器）。

    - ``python -m src.log.notify_mail register <email> <授权码>`` 存储到凭据管理器；
    - ``python -m src.log.notify_mail check <email>`` 检查是否已存储。
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="notify_mail", description="管理邮件授权码（系统凭据管理器）"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    reg = sub.add_parser("register", help="存储授权码到系统凭据管理器")
    reg.add_argument("email")
    reg.add_argument("password", help="QQ 邮箱授权码（16 位，非登录密码）")
    chk = sub.add_parser("check", help="检查系统凭据管理器是否已有该邮箱授权码")
    chk.add_argument("email")
    args = parser.parse_args(argv)
    if args.cmd == "register":
        register_credentials(args.email, args.password)
        print(f"已存储 {args.email} 的授权码到系统凭据管理器")
    else:
        has = (
            _keyring is not None
            and _keyring.get_password(_KEYRING_SERVICE, args.email) is not None
        )
        print(f"{args.email}: {'已存在' if has else '未找到'}")


if __name__ == "__main__":
    _main()
