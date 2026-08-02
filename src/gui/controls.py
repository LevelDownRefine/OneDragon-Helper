"""共享 UI 控件工厂：按钮样式集中管理，避免各处重复 QSS 字符串。

三个工厂精确还原既有配色与交互（hover/pressed），不改动视觉设计：
- make_pill_button    : 强调色轮廓药丸按钮（pressed 改淡背景），用于全选/清空/添加脚本。
- make_secondary_button: 中性轮廓按钮（pressed 改边框蓝），用于选择/选择副本/浏览。
- make_icon_button    : 圆形透明图标按钮，用于 🗑/⚙ 等。
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton


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
