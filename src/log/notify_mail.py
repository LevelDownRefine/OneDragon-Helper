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
下仍对齐），纯文本部分沿用等宽空格填充的汇总表，供纯文本客户端与控制台复用。HTML 样式
全部内联、布局全部用 table，配色照抄 GUI 主题 ``src/gui/qml/Theme.js`` 的深色语义色——
收件端配色与界面保持同一套视觉语言，不随本机亮/暗模式变化。
"""

import html
import logging
import smtplib
import ssl
from datetime import datetime
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

try:
    import keyring as _keyring
except ImportError:  # keyring 缺失时无法取授权码（无明文兜底），send_mail 直接跳过
    _keyring = None

from src.log.monitor import (
    ScriptLogStatus,
    display_status,
    format_diagnostic_sections,
    status_cn,
    summary_counts,
    summary_table_rows,
)

logger = logging.getLogger(__name__)

# keyring 槽位（service 名）：本项目的系统凭据管理器命名空间，与具体邮件库无关。
_KEYRING_SERVICE = "OneDragon-Helper"
# socket 超时：防止 SMTP 连接挂起时脚本无限阻塞、被 runner 按 run_timeout 强杀
_SMTP_TIMEOUT_SECONDS = 10
_SUBJECT_PREFIX = "[OneDragon-Helper] "

# HTML 正文配色：照抄 GUI 主题（src/gui/qml/Theme.js）的深色语义色，邮件与界面同一套
# 视觉语言——色值改动只应发生在 Theme.js，此处随之对齐。
# 邮件客户端常剥离 <style> 且 CSS 支持不一，故样式一律内联、布局一律用 table。
_CANVAS = "#0B1220"
_PANEL = "#121D2E"  # Theme.panel 的 rgba 去掉 alpha（邮件底不透明）
_CONTROL = "#1D2B40"
_BORDER = "#36465E"
_DIVIDER = "#29384E"
_TEXT = "#F2F6FC"
_MUTED = "#A4B3C8"
_ACCENT = "#8CB9FF"
_ACCENT_SOFT = "#243C5E"
_BATCH = "#FFDE21"
_DANGER = "#C64B5A"
_FONT = "-apple-system,'Segoe UI','Microsoft YaHei',Roboto,Arial,sans-serif"
_MONO = "Consolas,'Courier New',monospace"

# 展示状态配色 (胶囊底色, 文字色)；键集与 monitor.status_cn 一致。
# 前三者按 GUI 的「柔和底 + 亮字」手法取同色相深浅（成功=accent、警告=batch、失败=danger）。
_STATUS_COLORS: dict[str, tuple[str, str]] = {
    ScriptLogStatus.SUCCESS: (_ACCENT_SOFT, _ACCENT),
    ScriptLogStatus.FAILED: ("#3A2027", "#EE8E9C"),
    ScriptLogStatus.WARN: ("#3D3620", _BATCH),
    ScriptLogStatus.NO_LOG: (_CONTROL, _MUTED),
}


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
    # 诊断段两版正文共用一份筛选口径：纯文本版拼文本，HTML 版按 entries 结构化渲染。
    diagnostic = format_diagnostic_sections(result.get("entries", []))
    body = _build_body(result, diagnostic)
    html_body = _build_html(result)
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


def _build_html(result: dict) -> str:
    """拼接邮件正文（HTML）：卡片容器 + 统计徽章 + 汇总表 + 报错明细 / 日志尾部。

    全部用内联样式的真 ``<table>`` 排版，不依赖等宽字体、不受 CJK 双宽与 tabstop 影响。

    Args:
        result: ``monitor.parse_logs`` 的返回值（用其 ``entries`` 渲染各段）。

    Returns:
        HTML 正文。
    """
    entries = result.get("entries", [])
    headers, rows = summary_table_rows(entries)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    return "\n".join(
        [
            '<html><head><meta charset="utf-8">',
            # 声明深色：避免客户端（Gmail / QQ 邮箱的深色模式）再对配色做自动反色。
            '<meta name="color-scheme" content="dark light">',
            '<meta name="supported-color-schemes" content="dark light"></head>',
            f'<body style="margin:0;padding:0;background:{_CANVAS}">',
            f'<div style="margin:0;padding:24px 12px;background:{_CANVAS};'
            f'font-family:{_FONT};color:{_TEXT}">',
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"'
            ' style="border-collapse:collapse"><tr><td align="center">',
            '<table role="presentation" width="660" cellpadding="0" cellspacing="0"'
            f' style="width:660px;max-width:100%;background:{_PANEL};'
            f'border:1px solid {_BORDER};border-radius:14px;border-collapse:collapse">',
            f'<tr><td style="padding:20px 24px;background:{_CONTROL};'
            f'border-bottom:1px solid {_DIVIDER};border-radius:14px 14px 0 0">'
            f'<div style="font-size:18px;font-weight:600;color:{_TEXT}">'
            "脚本运行状况汇总报告</div>"
            f'<div style="margin-top:6px;font-size:12px;color:{_MUTED}">'
            f"{stamp} · 由 OneDragon-Helper 自动发送</div></td></tr>",
            f'<tr><td style="padding:18px 24px 4px">{_render_counts(entries)}</td></tr>',
            f'<tr><td style="padding:10px 24px 0">'
            f"{_render_summary_table(entries, headers, rows)}</td></tr>",
            f'<tr><td style="padding:4px 24px 24px">{_render_diagnostics(entries)}</td></tr>',
            f'<tr><td style="padding:0 24px 20px">'
            f'<div style="border-top:1px solid {_DIVIDER};padding-top:12px;font-size:11px;'
            f'color:{_MUTED}">本邮件由 OneDragon-Helper 在脚本链结束后自动发送。</div>'
            "</td></tr>",
            "</table></td></tr></table></div>",
            "</body></html>",
        ]
    )


def _pill(text: str, *, bg: str, fg: str) -> str:
    """渲染状态胶囊（暗底亮字小圆角标签，圆角取 GUI 控件的 6）。text 需已转义。"""
    return (
        f'<span style="display:inline-block;padding:1px 8px;border-radius:6px;'
        f'font-size:12px;line-height:16px;background:{bg};color:{fg}">{text}</span>'
    )


def _render_counts(entries: list[dict]) -> str:
    """汇总统计徽章行：总计 / 成功 / 失败 / 无日志（数字同源于 ``summary_counts``）。"""
    counts = summary_counts(entries)
    cells = "".join(
        f'<td style="padding-right:8px"><span style="display:inline-block;'
        f"padding:4px 12px;border-radius:8px;font-size:12px;background:{bg};"
        f'color:{fg}">{label} '
        f'<b style="font-size:13px">{counts[key]}</b></span></td>'
        for label, key, (bg, fg) in (
            ("总计", "total", (_CONTROL, _MUTED)),
            ("成功", "success", _STATUS_COLORS[ScriptLogStatus.SUCCESS]),
            ("失败", "failed", _STATUS_COLORS[ScriptLogStatus.FAILED]),
            ("无日志", "no_log", _STATUS_COLORS[ScriptLogStatus.NO_LOG]),
        )
    )
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0"'
        f' style="border-collapse:collapse"><tr>{cells}</tr></table>'
    )


def _render_summary_table(
    entries: list[dict], headers: list[str], rows: list[list[str]]
) -> str:
    """汇总表：无竖线表头 + 分割线行 + 状态胶囊 + 报错数标红。

    单元格文本仍由 ``summary_table_rows`` 决定（与纯文本表、控制台同源），此处只按列名
    上色，不改内容。entries 与 rows 一一对应（同一 entries 派生）。
    """
    col_script = headers.index("脚本")
    col_status = headers.index("每日状态")
    col_errors = headers.index("报错")
    head = "".join(
        f'<th style="padding:8px 10px;text-align:left;font-size:12px;font-weight:600;'
        f'color:{_MUTED};background:{_CONTROL};border-bottom:1px solid {_BORDER}">'
        f"{html.escape(h)}</th>"
        for h in headers
    )
    body: list[str] = []
    for entry, row in zip(entries, rows, strict=True):
        status = display_status(entry["result"])
        pill_bg, pill_fg = _STATUS_COLORS[status]
        # 行分隔靠分割线（与 GUI 列表一致），不用斑马纹。
        style = (
            f"padding:9px 10px;font-size:13px;background:{_PANEL};"
            f"border-bottom:1px solid {_DIVIDER}"
        )
        cells: list[str] = []
        for column, cell in enumerate(row):
            if column == col_status:
                inner = _pill(html.escape(cell), bg=pill_bg, fg=pill_fg)
            elif column == col_errors and cell != "0":
                inner = (
                    f'<span style="font-weight:600;color:{_DANGER}">'
                    f"{html.escape(cell)}</span>"
                )
            elif column == col_script:
                inner = f'<span style="font-weight:600">{html.escape(cell)}</span>'
            else:
                # 缺值（体力无日志可提取）以次要文字色弱化，避免与真值混淆。
                color = _TEXT if cell != "—" else _MUTED
                inner = f'<span style="color:{color}">{html.escape(cell)}</span>'
            cells.append(f'<td style="{style}">{inner}</td>')
        body.append("<tr>" + "".join(cells) + "</tr>")
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"'
        f' style="border-collapse:collapse;border:1px solid {_BORDER};'
        f'border-radius:10px"><tr>{head}</tr>{"".join(body)}</table>'
    )


def _section_title(text: str) -> str:
    """诊断段小标题（左侧强调色条 + 主文字色）。"""
    return (
        '<div style="margin:22px 0 2px;padding-left:8px;border-left:3px solid'
        f' {_ACCENT};font-size:13px;font-weight:600;color:{_TEXT}">'
        f"{html.escape(text)}</div>"
    )


def _render_diagnostics(entries: list[dict]) -> str:
    """诊断明细：报错脚本卡片（在前）+ 失败脚本日志尾部（在后），与纯文本版同序同筛选。

    报错卡片与日志尾部仅渲染有内容的脚本；两段皆空时整段不渲染。
    """
    error_entries = [e for e in entries if e["result"]["errors"]]
    tail_entries = [
        e
        for e in entries
        if e["result"]["status"] == ScriptLogStatus.FAILED
        and e["result"]["log_content"]
    ]
    parts: list[str] = []
    if error_entries:
        parts.append(_section_title("各脚本报错明细"))
        parts.extend(_render_error_card(e) for e in error_entries)
    if tail_entries:
        parts.append(_section_title("各脚本日志尾部"))
        parts.extend(_render_tail_card(e) for e in tail_entries)
    return "".join(parts)


def _render_error_card(entry: dict) -> str:
    """单个脚本的报错卡片：脚本名 + 状态胶囊 + 日志路径 + 报错行列表。"""
    result = entry["result"]
    status = display_status(result)
    pill_bg, pill_fg = _STATUS_COLORS[status]
    log_path = result["log_path"]
    path_html = (
        f'<div style="margin-top:4px;font-size:11px;color:{_MUTED};'
        f'word-break:break-all">{html.escape(log_path)}</div>'
        if log_path
        else ""
    )
    errors = "".join(
        f'<li style="margin-top:4px;word-break:break-all">{html.escape(err)}</li>'
        for err in result["errors"]
    )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"'
        f' style="margin-top:8px;background:{_PANEL};border:1px solid {_BORDER};'
        f"border-left:3px solid {pill_fg};border-radius:10px;"
        'border-collapse:collapse"><tr><td style="padding:12px 14px">'
        f'<div style="font-size:13px;font-weight:600;color:{_TEXT}">'
        f"{html.escape(entry['display_name'])} "
        f"{_pill(status_cn[status], bg=pill_bg, fg=pill_fg)}</div>"
        f"{path_html}"
        f'<ul style="margin:8px 0 0;padding-left:18px;font-family:{_MONO};'
        f'font-size:12px;line-height:18px;color:{_MUTED}">{errors}</ul>'
        "</td></tr></table>"
    )


def _render_tail_card(entry: dict) -> str:
    """单个脚本的日志尾部块：脚本名 + 等宽 ``<pre>``（超长行强制折行防横向溢出）。"""
    return (
        f'<div style="margin-top:10px;font-size:12px;font-weight:600;color:{_MUTED}">'
        f"{html.escape(entry['display_name'])}</div>"
        f'<pre style="margin:6px 0 0;padding:12px 14px;background:{_CANVAS};'
        f"border:1px solid {_BORDER};border-radius:10px;font-family:{_MONO};"
        f"font-size:12px;line-height:18px;color:{_MUTED};white-space:pre-wrap;"
        f'word-break:break-all">{html.escape(entry["result"]["log_content"])}</pre>'
    )


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
