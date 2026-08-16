"""主题常量与工具：设计稿常量（Ardot 画布原值）的单一来源。

从 main_window.py 按职责拆分而来（2026-08-16）：全部颜色/尺寸/字体/星期名/
元数据链接等常量与 make_font/rgba 工具独立成模块，供 icons/widgets/主窗口共享。
依赖单向：theme → 无（仅 QtGui），其余模块 → theme。
"""

from PySide6.QtGui import QColor, QFont

# ═══════════════════════ 设计稿常量（Ardot 画布原值）═══════════════════════
CANVAS_W, CANVAS_H = 1280, 720

# 颜色（从画布 fills 换算 hex）
C_WINDOW_BG = "#0A0E1A"  # 主窗口底色
C_BTN_DARK = "#1F2937"  # 悬浮条/窗口控制深底
C_YELLOW = "#F4C242"  # 启动全部 / 启动脚本主色
C_BLUE = "#2196F3"  # 启动脚本蓝色大胶囊
C_BLUE_DEEP = "#0F2A4D"  # 蓝色胶囊内圆深底
C_WHITE = "#FFFFFF"
C_BLUE_TEXT = "#7DA8FF"  # 选中/文字高亮蓝

# 拖拽重排 MIME（脚本唯一标识 script_name；与旧 GUI src/gui/widgets.py 一致）
DRAG_MIME = "application/x-onedragon-script"
C_FAINT = "#4A5568"  # 停用文字
C_GREEN = "#3DD68C"  # 启用开关
C_GRAY_TRACK = "#2A2F38"  # 停用开关轨道
C_GRAY_KNOB = "#5A6470"  # 停用开关滑块
C_GAME_DIM = "#161C28"  # 停用游戏图标

# 字体
FONT_FAMILY = "Microsoft YaHei"

# 兜底背景：脚本未配置背景图时使用（相对项目根）
DEFAULT_BG = "assets/ds.jpg"

# 周常「周几以后开始执行」：值 1=周一 ~ 7=周日（对齐 get_week_num 的 0=周一 偏移 +1）
WEEKDAY_NAMES = {
    1: "周一",
    2: "周二",
    3: "周三",
    4: "周四",
    5: "周五",
    6: "周六",
    7: "周日",
}

# ── 游戏元数据（display_name → 图标底色 / 背景主色 / 链接）───────────────
# 通用占位链接（对应内容未配置时使用）
_URL_HOME = "https://github.com/"
_URL_BILIBILI = "https://www.bilibili.com/"


def make_font(size: int, weight: int = 400) -> QFont:
    """统一像素字号 QFont（与 QSS px 渲染一致）。"""
    f = QFont(FONT_FAMILY)
    f.setPixelSize(size)
    f.setWeight(QFont.Weight(weight))
    return f


def rgba(hex_color: str, alpha: int) -> QColor:
    c = QColor(hex_color)
    c.setAlpha(alpha)
    return c
