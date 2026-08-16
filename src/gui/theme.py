"""gui 主题：设计 token 与统一样式模板（QSS）。

旧 GUI 残留中仅被 dialogs.py 使用的表单样式子集（2026-08-16 清理死代码后）：
其余 QSS 工厂 / 按钮工厂 / 旧色系常量（BEIGE、BG_MAIN、BG_MUTED 等）已随
旧 GUI 主窗口删除。
"""

from PySide6.QtGui import QFont

# ── 甘雨五色（色卡） ────────────────────────────────────────────────────────
DARK_BLUE = "#333957"  # 深空蓝
BLUE = "#5D74A2"  # 钢蓝
SKY_BLUE = "#C4D8F2"  # 雾蓝
CRIMSON = "#8E2D30"  # 酒红

# ── 语义色（直接引用五色） ──────────────────────────────────────────────────
TEXT = DARK_BLUE  # 正文
TEXT_MUTED = DARK_BLUE  # 次要文字
TEXT_FAINT = DARK_BLUE  # 弱文字 / 占位
BG_CARD = "#FFFFFF"  # 卡片底（白色保留）
BG_HOVER = SKY_BLUE  # 悬停底
BORDER = SKY_BLUE  # 中性边框
DISABLED = SKY_BLUE  # 禁用底色
BORDER_WIDTH = "1px"  # 统一边框宽度（QSS 模板引用）

FONT_FAMILY = '"Microsoft YaHei", "Segoe UI", sans-serif'


# ── 字号 token ──────────────────────────────────────────────────────────────
FONT_SIZE_BODY = 11  # 正文：输入框 / 下拉框 / 表单标签
FONT_SIZE_BTN = 12  # 按钮：主 / 次级 / 危险


# ── 文本 / 布局常量 ──────────────────────────────────────────────────────────
LABEL_WIDTH = 64  # 表单标签固定宽


def make_font(*, size: int = FONT_SIZE_BODY, bold: bool = False) -> QFont:
    """统一构造像素字号的 QFont（避免 point size 与 QSS px 差异 + 字体名硬编码）。"""
    font = QFont("Microsoft YaHei")
    font.setPixelSize(size)
    if bold:
        font.setBold(True)
    return font


# ── 按钮 QSS 模板 ────────────────────────────────────────────────────────────


def primary_button_qss(*, radius: int = 10, font_size: int = FONT_SIZE_BTN) -> str:
    """主按钮：钢蓝纯色底 + 白字（平面风格，无渐变）。dialogs 主按钮用。"""
    return f"""
        QPushButton {{
            background: {BLUE};
            color: white;
            border: none;
            border-radius: {radius}px;
            font-size: {font_size}px;
        }}
        QPushButton:hover {{ background: {DARK_BLUE}; }}
        QPushButton:pressed {{ background: {DARK_BLUE}; }}
        QPushButton:disabled {{ background: {DISABLED}; color: #F0F3F8; }}
    """


def outlined_qss(
    *,
    selector: str = "QPushButton",
    accent: str = BLUE,
    radius: int = 8,
    font_size: int = FONT_SIZE_BODY,
    color: str = DARK_BLUE,
    border: str = BORDER,
    padding: str = "4px 10px",
) -> str:
    """轮廓控件模板（次级按钮 / 危险按钮共用）：
    透明底 + 圆角边框，hover 只变边框/文字色（不填充背景，保持平面风格）。"""
    return f"""
        {selector} {{
            border: {BORDER_WIDTH} solid {border};
            border-radius: {radius}px;
            background: transparent;
            font-family: {FONT_FAMILY};
            font-size: {font_size}px;
            color: {color};
            padding: {padding};
        }}
        {selector}:hover {{ border-color: {accent}; color: {accent}; }}
        {selector}:disabled {{ color: {TEXT_FAINT}; border-color: {DISABLED}; }}
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
            border: {BORDER_WIDTH} solid {BORDER};
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
            border: {BORDER_WIDTH} solid {BORDER};
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
            border: {BORDER_WIDTH} solid {BORDER};
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


def message_box_qss() -> str:
    """消息框：白底深字 + 中性按钮。"""
    return f"""
        QMessageBox {{ background-color: white; color: {TEXT}; }}
        QMessageBox QLabel {{ color: {TEXT}; background-color: transparent; }}
        QMessageBox QPushButton {{
            background-color: #F1F5F9; color: {TEXT};
            border: {BORDER_WIDTH} solid {BORDER}; border-radius: 6px; padding: 6px 16px;
        }}
        QMessageBox QPushButton:hover {{ background-color: {BG_HOVER}; }}
    """
