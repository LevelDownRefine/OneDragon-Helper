"""GUI 工具：统一消息框 / 打开文件辅助 / 共享按钮工厂（强制浅色样式，避免深色主题下全黑不可读）。

UI 状态持久化见 :mod:`src.service.chain_service`，每周超时应用见 :mod:`src.service.chain_gen`，
默认超时常量见 :mod:`src.config.subscript`（均无 Qt，GUI 与 CLI 共用，由调用方直接 import）。
图标相关逻辑在 :mod:`src.gui.icons`。
"""

import logging
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QPushButton

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 统一消息框 / 打开文件辅助（强制浅色样式，避免深色主题下全黑不可读）
# ---------------------------------------------------------------------------

_MSG_STYLE = """
QMessageBox { background-color: #ffffff; color: #1f2937; }
QMessageBox QLabel { color: #1f2937; background-color: transparent; }
QMessageBox QPushButton {
    background-color: #f1f5f9; color: #1f2937;
    border: 1px solid #cbd5e1; border-radius: 6px; padding: 6px 16px;
}
QMessageBox QPushButton:hover { background-color: #e2e8f0; }
"""


def _styled_msg_box(parent, icon, title, text):
    """构造一个样式固定的消息框（白底深字，带图标），直接 .exec() 即可。"""
    box = QMessageBox(parent)
    box.setIcon(icon)
    box.setWindowTitle(title)
    box.setText(text)
    box.setTextFormat(Qt.PlainText)
    box.setStyleSheet(_MSG_STYLE)
    return box


def safe_startfile(parent, path, fail_text):
    """用系统默认程序打开 path；任何异常都转成清晰可读的提示，不让 GUI 崩溃。"""
    try:
        os.startfile(path)
    except OSError as e:
        _styled_msg_box(
            parent, QMessageBox.Warning, "提示", f"{fail_text}：\n{e}"
        ).exec()


# ---------------------------------------------------------------------------
# 共享按钮工厂（样式集中管理，避免各处重复 QSS 字符串）
# ---------------------------------------------------------------------------


def make_pill_button(
    text,
    *,
    accent="#3b82f6",
    hover_color=None,
    pressed_bg=None,
    min_width=72,
    fixed_height=32,
    border="#d8dee9",
    radius=8,
    padding="0 16px",
    color="#4b5563",
    font_size=11,
) -> QPushButton:
    """强调色轮廓药丸按钮：白底圆角边框，hover 改边框/字色，pressed 改淡背景。"""
    btn = QPushButton(text)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setFixedHeight(fixed_height)
    if min_width:
        btn.setMinimumWidth(min_width)
    hover = hover_color or accent
    pressed = f"background: {pressed_bg};" if pressed_bg else ""
    btn.setStyleSheet(f"""
        QPushButton {{
            background: white;
            border: 1px solid {border};
            border-radius: {radius}px;
            padding: {padding};
            color: {color};
            font-size: {font_size}px;
        }}
        QPushButton:hover {{ border-color: {accent}; color: {hover}; }}
        QPushButton:pressed {{ {pressed} }}
    """)
    return btn


def make_secondary_button(
    text,
    *,
    fixed_height=28,
    border="#d0d0d0",
    radius=6,
    padding="0 16px",
    font_size=10,
    color="#303030",
    min_width=0,
) -> QPushButton:
    """中性轮廓按钮：白底圆角边框，hover 改边框灰，pressed 改边框蓝。"""
    btn = QPushButton(text)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setFixedHeight(fixed_height)
    if min_width:
        btn.setMinimumWidth(min_width)
    btn.setStyleSheet(f"""
        QPushButton {{
            border: 1px solid {border};
            border-radius: {radius}px;
            background: white;
            font-family: "Microsoft YaHei";
            font-size: {font_size}px;
            color: {color};
            padding: {padding};
            text-align: center;
        }}
        QPushButton:hover {{ border-color: #a0a0a0; }}
        QPushButton:pressed {{ border-color: #0078D4; }}
    """)
    return btn


def make_icon_button(
    symbol,
    *,
    accent="#3b82f6",
    normal_color="#9aa3b2",
    font_size=14,
    hover_bg="#eef2f7",
    pressed_bg="#e2e8f0",
    size=30,
    tooltip=None,
) -> QPushButton:
    """圆形透明图标按钮：固定正方形，hover/pressed 变色。"""
    btn = QPushButton(symbol)
    btn.setFixedSize(size, size)
    btn.setCursor(Qt.PointingHandCursor)
    if tooltip:
        btn.setToolTip(tooltip)
    btn.setStyleSheet(f"""
        QPushButton {{
            border: none;
            border-radius: {size // 2}px;
            background: transparent;
            font-size: {font_size}px;
            color: {normal_color};
        }}
        QPushButton:hover {{ background-color: {hover_bg}; color: {accent}; }}
        QPushButton:pressed {{ background-color: {pressed_bg}; }}
    """)
    return btn
