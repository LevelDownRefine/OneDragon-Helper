"""gui 主题：设计 token（甘雨五色）与统一样式模板（QSS / 按钮工厂）。

所有 GUI 模块的样式一律从这里取，禁止在业务代码里再写裸色值/QSS 字符串。
甘雨五色源见 ``theme.py`` 顶部注释（由用户提供的色卡图标注转换而来）。

配色语义：
    DARK_BLUE  深空蓝 —— 标题 / 按下态 / 深色正文
    BLUE       钢蓝   —— 主色（按钮、焦点、选中、开关开启）
    SKY_BLUE   雾蓝   —— 悬停底、浅边框、滚动条
    BEIGE      肤色   —— 窗口暖底 / 强调卡背景
    CRIMSON    酒红   —— 危险 / 删除 / 警示
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QPushButton

# ── 甘雨五色（色卡） ────────────────────────────────────────────────────────
DARK_BLUE = "#333957"  # 深空蓝
BLUE = "#5D74A2"  # 钢蓝
SKY_BLUE = "#C4D8F2"  # 雾蓝
BEIGE = "#F2E8E3"  # 肤
CRIMSON = "#8E2D30"  # 酒红

# ── 派生色（在五色基础上调亮/调深，保证可读性） ────────────────────────────────
BLUE_LIGHT = "#7D93BF"  # 钢蓝亮端（渐变顶 / hover）
BLUE_DARK = "#4A5F8C"  # 钢蓝深端（按下）
TEXT = "#333957"  # 正文 = 深空蓝
TEXT_MUTED = "#6B7390"  # 次要文字（深空蓝降饱和）
TEXT_FAINT = "#9AA1B5"  # 弱文字 / 占位
BG_MAIN = "#F4EDE6"  # 主窗口背景（肤色调亮）
BG_CARD = "#FFFFFF"  # 卡片白底
BG_MUTED = "#F7F8FA"  # 禁用/静音卡片底
BG_HOVER = "#E9F0FA"  # 悬停底（雾蓝极浅）
BG_CHIP = "#EEF3FA"  # 标题 chip 底色
BG_DANGER_SOFT = "#F7EBEB"  # 危险浅底（酒红极浅）
BORDER = "#DAE4F1"  # 中性边框（雾蓝柔化）
BORDER_ACCENT = "#C5D4EA"  # 雾蓝边框（悬停 / 次级按钮）
BORDER_SOFT = "#E8EDF5"  # 极柔边框（弱化层）
DISABLED = "#CBD3E2"  # 禁用底色

FONT_FAMILY = '"Microsoft YaHei", "Segoe UI", sans-serif'


# ── 字号 token（统一所有控件，避免散在多处） ─────────────────────────────────
FONT_SIZE_BODY = 11  # 正文：脚本名 chip / 副本按钮 / 输入框 / 下拉框 / 表单标签
FONT_SIZE_BTN = 12  # 按钮：次级 / 药丸 / 危险
FONT_SIZE_HERO = 13  # 主要操作：运行按钮


# ── 文本 / 布局常量 ──────────────────────────────────────────────────────────
LABEL_WIDTH = 64  # 表单标签固定宽
LABEL_WIDTH = 64  # 表单标签固定宽


def make_font(*, size: int = FONT_SIZE_BODY, bold: bool = False) -> QFont:
    """统一构造像素字号的 QFont（避免 point size 与 QSS px 差异 + 字体名硬编码）。
    所有 GUI 模块必须用此函数构造 QFont，禁止直接写 ``QFont("Microsoft YaHei", ...)``。
    """
    font = QFont("Microsoft YaHei")
    font.setPixelSize(size)
    if bold:
        font.setBold(True)
    return font


# ── 按钮 QSS 模板 ────────────────────────────────────────────────────────────


def primary_button_qss(*, radius: int = 10, font_size: int = FONT_SIZE_BTN) -> str:
    """主按钮：钢蓝渐变底 + 白字。dialogs 主按钮 / 主窗口「运行」共用。"""
    return f"""
        QPushButton {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                        stop:0 {BLUE_LIGHT}, stop:1 {BLUE});
            color: white;
            border: none;
            border-radius: {radius}px;
            font-size: {font_size}px;
        }}
        QPushButton:hover {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                        stop:0 #8FA5CF, stop:1 {BLUE_DARK});
        }}
        QPushButton:pressed {{ background: {DARK_BLUE}; }}
        QPushButton:disabled {{ background: {DISABLED}; color: #F0F3F8; }}
    """


def secondary_button_qss(
    *,
    border: str = BORDER,
    radius: int = 10,
    font_size: int = FONT_SIZE_BODY,
    color: str = TEXT,
) -> str:
    """中性轮廓按钮：白底圆角边框，hover 改边框/字色 + 加浅底，pressed 加深底。"""
    return f"""
        QPushButton {{
            border: 1px solid {border};
            border-radius: {radius}px;
            background: white;
            font-family: {FONT_FAMILY};
            font-size: {font_size}px;
            color: {color};
            padding: 0 16px;
            text-align: center;
        }}
        QPushButton:hover {{
            border-color: {BLUE}; color: {BLUE}; background: {BG_HOVER};
        }}
        QPushButton:pressed {{ background: {BG_CHIP}; }}
        QPushButton:disabled {{ color: {TEXT_FAINT}; border-color: {DISABLED}; }}
    """


def danger_button_qss(*, radius: int = 10, font_size: int = FONT_SIZE_BODY) -> str:
    """危险按钮：白底酒红边框/文字（删除、清空等破坏性操作）。"""
    return f"""
        QPushButton {{
            border: 1px solid #D8B4B6;
            border-radius: {radius}px;
            background: white;
            font-size: {font_size}px;
            color: {CRIMSON};
            padding: 0 24px;
        }}
        QPushButton:hover {{ border-color: {CRIMSON}; color: {CRIMSON};
                            background: {BG_DANGER_SOFT}; }}
        QPushButton:disabled {{ color: {TEXT_FAINT}; border-color: {DISABLED}; }}
    """


def pill_button_qss(
    *,
    accent: str = BLUE,
    hover_color: str | None = None,
    pressed_bg: str | None = None,
    border: str = BORDER,
    radius: int = 10,
    padding: str = "0 18px",
    color: str = TEXT,
    font_size: int = FONT_SIZE_BTN,
) -> str:
    """强调色轮廓药丸按钮：白底圆角边框，hover 改边框/字色，pressed 改淡背景。"""
    hover = hover_color or accent
    pressed = f"background: {pressed_bg};" if pressed_bg else ""
    return f"""
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
    """


def icon_button_qss(
    *,
    accent: str = BLUE,
    normal_color: str = TEXT_FAINT,
    font_size: int = 14,
    hover_bg: str = BG_HOVER,
    pressed_bg: str = "#E2E8F0",
    size: int = 30,
) -> str:
    """圆形透明图标按钮：固定正方形，hover/pressed 变色。"""
    return f"""
        QPushButton {{
            border: none;
            border-radius: {size // 2}px;
            background: transparent;
            font-size: {font_size}px;
            color: {normal_color};
        }}
        QPushButton:hover {{ background-color: {hover_bg}; color: {accent}; }}
        QPushButton:pressed {{ background-color: {pressed_bg}; }}
    """


# ── 输入控件 QSS 模板 ────────────────────────────────────────────────────────


def line_edit_qss(
    *,
    radius: int = 8,
    font_size: int = FONT_SIZE_BODY,
    padding: str = "6px 12px",
) -> str:
    """文本输入框：白底灰边，focus 钢蓝边框。"""
    return f"""
        QLineEdit {{
            border: 1px solid {BORDER};
            border-radius: {radius}px;
            padding: {padding};
            background: white;
            font-size: {font_size}px;
            color: {TEXT};
        }}
        QLineEdit:focus {{ border-color: {BLUE}; outline: none; }}
    """


def small_line_edit_qss(
    *, radius: int = 6, font_size: int = FONT_SIZE_BODY, text_align: str = "center"
) -> str:
    """紧凑文本输入框（如每周超时数字框）：居中或右对齐显示。"""
    return f"""
        QLineEdit {{
            border: 1px solid {BORDER};
            border-radius: {radius}px;
            padding: 4px 8px;
            background: white;
            font-size: {font_size}px;
            text-align: {text_align};
            color: {TEXT};
        }}
        QLineEdit:focus {{ border-color: {BLUE}; outline: none; }}
    """


def combo_box_qss(*, radius: int = 8, font_size: int = FONT_SIZE_BODY) -> str:
    """下拉框：白底灰边，drop-down 无独立边框。padding-left=12 与 line_edit 一致。"""
    return f"""
        QComboBox {{
            border: 1px solid {BORDER};
            border-radius: {radius}px;
            padding: 4px 12px;
            background: white;
            font-size: {font_size}px;
            color: {TEXT};
        }}
        QComboBox:hover {{ border-color: {BLUE}; }}
        QComboBox::drop-down {{ border: none; width: 20px; }}
    """


def check_box_qss(*, size: int = 16) -> str:
    """复选框：只定制文字颜色，indicator 完全走平台原生（原生自带白底方框+勾）。"""
    return f"""
        QCheckBox {{
            color: {TEXT};
        }}
        QCheckBox:disabled {{ color: {TEXT_FAINT}; }}
    """


def menu_qss() -> str:
    """弹出菜单（级联/右键）：白底深字，选中项钢蓝底白字。"""
    return f"""
        QMenu {{
            border: 1px solid {BORDER};
            border-radius: 4px;
            background: white;
            padding: 4px;
            font-size: 11px;
        }}
        QMenu::item {{
            padding: 4px 20px 4px 12px;
            border-radius: 3px;
            color: {TEXT};
        }}
        QMenu::item:selected {{ background-color: {BLUE}; color: white; }}
        QMenu::item:disabled {{ color: {TEXT_FAINT}; }}
        QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 8px; }}
    """


def message_box_qss() -> str:
    """消息框：白底深字 + 中性按钮。"""
    return f"""
        QMessageBox {{ background-color: white; color: {TEXT}; }}
        QMessageBox QLabel {{ color: {TEXT}; background-color: transparent; }}
        QMessageBox QPushButton {{
            background-color: #F1F5F9; color: {TEXT};
            border: 1px solid {BORDER}; border-radius: 6px; padding: 6px 16px;
        }}
        QMessageBox QPushButton:hover {{ background-color: {BG_HOVER}; }}
    """


def scroll_area_qss() -> str:
    """滚动区（透明背景 + 细滚动条）。"""
    return f"""
        QScrollArea {{ background-color: transparent; border: none; }}
        QScrollBar:vertical {{
            width: 8px;
            background: transparent;
        }}
        QScrollBar::handle:vertical {{
            background: {SKY_BLUE};
            border-radius: 4px;
            min-height: 30px;
        }}
        QScrollBar::handle:vertical:hover {{ background: {BLUE}; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    """


def card_qss(
    *,
    background: str = BG_CARD,
    border: str = BORDER,
    hover_border: str | None = None,
    radius: int = 14,
) -> str:
    """卡片容器：圆角 + 边框，可选 hover 变色。"""
    hover = f"QFrame:hover {{ border-color: {hover_border}; }}" if hover_border else ""
    return f"""
        QFrame {{
            background-color: {background};
            border: 1px solid {border};
            border-radius: {radius}px;
        }}
        {hover}
    """


# ── 按钮工厂（统一构造入口，替代各文件手写 QPushButton + setStyleSheet） ──────


def make_pill_button(
    text,
    *,
    accent: str = BLUE,
    hover_color: str | None = None,
    pressed_bg: str | None = None,
    min_width: int = 72,
    fixed_height: int = 34,
    border: str = BORDER,
    radius: int = 10,
    padding: str = "0 18px",
    color: str = TEXT,
    font_size: int = FONT_SIZE_BTN,
) -> QPushButton:
    """强调色轮廓药丸按钮（见 :func:`pill_button_qss`）。"""
    btn = QPushButton(text)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setFixedHeight(fixed_height)
    if min_width:
        btn.setMinimumWidth(min_width)
    btn.setStyleSheet(
        pill_button_qss(
            accent=accent,
            hover_color=hover_color,
            pressed_bg=pressed_bg,
            border=border,
            radius=radius,
            padding=padding,
            color=color,
            font_size=font_size,
        )
    )
    return btn


def make_secondary_button(
    text,
    *,
    fixed_height: int = 30,
    border: str = BORDER,
    radius: int = 10,
    padding: str = "0 16px",
    font_size: int = FONT_SIZE_BODY,
    color: str = TEXT,
    min_width: int = 0,
) -> QPushButton:
    """中性轮廓按钮（见 :func:`secondary_button_qss`）。"""
    btn = QPushButton(text)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setFixedHeight(fixed_height)
    if min_width:
        btn.setMinimumWidth(min_width)
    btn.setStyleSheet(
        secondary_button_qss(
            border=border,
            radius=radius,
            font_size=font_size,
            color=color,
        )
    )
    return btn


def make_icon_button(
    symbol,
    *,
    accent: str = BLUE,
    normal_color: str = TEXT_FAINT,
    font_size: int = 14,
    hover_bg: str = BG_HOVER,
    pressed_bg: str = "#E2E8F0",
    size: int = 30,
) -> QPushButton:
    """圆形透明图标按钮（见 :func:`icon_button_qss`）。"""
    btn = QPushButton(symbol)
    btn.setFixedSize(size, size)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setStyleSheet(
        icon_button_qss(
            accent=accent,
            normal_color=normal_color,
            font_size=font_size,
            hover_bg=hover_bg,
            pressed_bg=pressed_bg,
            size=size,
        )
    )
    return btn
