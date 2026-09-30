"""邮件正文的 HTML 渲染：把 ``monitor.parse_logs`` 的 entries 渲染成邮件 HTML。

纯呈现层——只读 entries 拼 HTML，不碰网络、凭据与文件；发送侧见 ``notify_mail.py``。
配色照抄 GUI 主题 ``src/gui/qml/Theme.js`` 的深色语义色，收件端与界面保持同一套视觉语言。
邮件客户端常剥离 ``<style>`` 且 CSS 支持不一，故样式一律内联、布局一律用 ``<table>``。
"""

import html
from datetime import datetime

from src.log.monitor import (
    ScriptLogStatus,
    display_status,
    status_cn,
    summary_counts,
    summary_table_rows,
)

# 配色常量名与 GUI 主题一一对应；色值改动只应发生在 Theme.js，此处随之对齐。
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


def build_html(result: dict) -> str:
    """渲染邮件正文（HTML）：卡片容器 + 统计徽章 + 汇总表 + 报错明细 / 日志尾部。

    全部用内联样式的真 ``<table>`` 排版，不依赖等宽字体、不受 CJK 双宽与 tabstop 影响。

    Args:
        result: ``monitor.parse_logs`` 的返回值（用其 ``entries`` 渲染各段）。

    Returns:
        完整的 HTML 文档（含 html/body 包裹与 color-scheme 声明）。
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
