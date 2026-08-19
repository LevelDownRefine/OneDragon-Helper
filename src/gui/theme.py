"""主题常量：当前 QML GUI 使用的颜色/字体/星期名/元数据链接。

单一来源，供 main_window / launcher 引用。旧 Widgets GUI（main_window/widgets/
task_card）已删除，相关常量一并移除。
"""

# 字体
FONT_FAMILY = "Microsoft YaHei"

# 游戏图标停用底色（渐变兜底水印等场景复用）
C_GAME_DIM = "#161C28"

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

# 通用占位链接（对应内容未配置时使用）
_URL_HOME = "https://github.com/LevelDownRefine/OneDragon-Helper"
_URL_BILIBILI = "https://www.bilibili.com/"
