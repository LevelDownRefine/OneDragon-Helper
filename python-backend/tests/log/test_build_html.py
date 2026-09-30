"""测试 src/log/build_html.py：邮件 HTML 正文的结构、配色与转义。"""

import unittest

from src.log.build_html import build_html
from src.log.monitor import ScriptLogStatus
from tests.log.helpers import make_entry, make_result


class TestBuildHtml(unittest.TestCase):
    """HTML 正文渲染：真表格、GUI 深色配色、诊断卡片与转义。"""

    def test_uses_real_table(self):
        """HTML 正文用真 <table> 呈现汇总表（不依赖等宽字体，比例字体下仍对齐）。"""
        entries = (make_entry("崩铁", ScriptLogStatus.FAILED, errors=("ERROR x",)),)
        html_body = build_html(make_result(entries=entries))
        self.assertIn("<table", html_body)
        self.assertIn("每日状态", html_body)
        self.assertIn("崩铁", html_body)
        self.assertIn("失败", html_body)

    def test_colors_status_pill(self):
        """状态列按展示状态上色：失败红、成功蓝（色值取自 GUI 主题 Theme.js）；文本仍与纯文本表同源。"""
        entries = (
            make_entry("崩铁", ScriptLogStatus.FAILED, errors=("ERROR x",)),
            make_entry("鸣潮", ScriptLogStatus.SUCCESS, stamina="180"),
        )
        html_body = build_html(make_result(entries=entries))
        self.assertIn('background:#3A2027;color:#EE8E9C">失败</span>', html_body)
        self.assertIn('background:#243C5E;color:#8CB9FF">成功</span>', html_body)

    def test_uses_gui_dark_palette(self):
        """底色与主文字色取自 GUI 主题：邮件与界面同一套配色。"""
        entries = (make_entry("鸣潮", ScriptLogStatus.SUCCESS),)
        html_body = build_html(make_result(entries=entries))
        self.assertIn("background:#0B1220", html_body)  # Theme.canvas
        self.assertIn("background:#121D2E", html_body)  # Theme.panel
        self.assertIn("color:#F2F6FC", html_body)  # Theme.text

    def test_diagnostics_cards(self):
        """报错明细渲染为卡片、失败脚本另附日志尾部，且报错段在日志尾部之前。"""
        entry = make_entry("崩铁", ScriptLogStatus.FAILED, errors=("ERROR boom",))
        entry["result"]["log_content"] = "tail line"
        html_body = build_html(make_result(entries=(entry,)))
        self.assertIn("各脚本报错明细", html_body)
        self.assertIn("ERROR boom", html_body)
        self.assertIn("各脚本日志尾部", html_body)
        self.assertIn("tail line", html_body)
        self.assertLess(
            html_body.index("各脚本报错明细"), html_body.index("各脚本日志尾部")
        )

    def test_no_diagnostics_when_all_ok(self):
        """无报错脚本且无失败脚本：整段诊断不渲染（不留空标题）。"""
        entries = (make_entry("鸣潮", ScriptLogStatus.SUCCESS, stamina="180"),)
        html_body = build_html(make_result(entries=entries))
        self.assertNotIn("各脚本报错明细", html_body)
        self.assertNotIn("各脚本日志尾部", html_body)

    def test_escapes_cells(self):
        """单元格内容经 html.escape，脚本名含标记字符也不会破坏表格结构。"""
        entries = (make_entry("<script>x</script>", ScriptLogStatus.SUCCESS),)
        html_body = build_html(make_result(entries=entries))
        self.assertNotIn("<script>x</script>", html_body)
        self.assertIn("&lt;script&gt;", html_body)

    def test_counts_badges_without_stale_actions(self):
        """统计徽章与表格同源（数字取自 summary_counts）；不再出现已过期的「将重跑 / 将通知」。

        邮件在重跑之后发送，该行语义已失效；且改判据后重跑集合即非成功行、通知集合
        即报错非零行，均与表格本身冗余。
        """
        entries = (
            make_entry("崩铁", ScriptLogStatus.FAILED, errors=("ERROR x",)),
            make_entry("鸣潮", ScriptLogStatus.SUCCESS, stamina="180"),
        )
        html_body = build_html(make_result(entries=entries))
        for label in ("总计", "成功", "失败", "无日志"):
            self.assertIn(f"{label} <b", html_body)
        self.assertNotIn("将重跑", html_body)
        self.assertNotIn("将通知", html_body)


if __name__ == "__main__":
    unittest.main()
