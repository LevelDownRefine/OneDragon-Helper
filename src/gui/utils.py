"""GUI 工具与 UI 状态持久化。

- UI 状态持久化（config/gui_state.json）与星期计算；
- 统一的消息框 / 打开文件辅助函数（强制浅色样式，避免深色主题下全黑不可读）。
"""

import json
import os
import sys
from datetime import datetime, timedelta
from functools import lru_cache

from PySide6.QtCore import QFileInfo, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QFileIconProvider, QMessageBox

from src.utils import get_root_dir, safe_path_join

# 默认图标：没有自带图标的脚本（如 python 脚本，或 external 但取不到 exe 图标的）使用。
# 优先用当前 Python 解释器（sys.executable）的 OS 文件图标，即 Python 官方图标；
# 极个别取不到时（如冻结后 sys.executable 指向自身 exe）回退到 assets/Chtholly.ico。
_DEFAULT_ICON_PATH = safe_path_join(get_root_dir(), "assets", "Chtholly.ico")
_DEFAULT_ICON: QIcon | None = None

_STATE_FILE = safe_path_join(get_root_dir(), "config", "gui_state.json")


def load_ui_state() -> dict:
    """读取上次保存的 UI 状态"""
    if os.path.exists(_STATE_FILE):
        with open(_STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_ui_state(state: dict):
    """保存 UI 状态"""
    with open(_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def get_week_num() -> int:
    """返回星期数字：0周一 ~ 6周日。

    以凌晨 4 点为界：4 点前归前一天，例如周一 03:00 仍按上周日(6)计。
    """
    return (datetime.now() - timedelta(hours=4)).weekday()


DEFAULT_RUN_TIMEOUT = 3600
"""脚本运行默认超时秒数。当 weekly_timeouts.yml 无条目或不足 7 格时作为 fallback。"""


def apply_weekly_timeout(script: dict, weekly_timeouts: dict) -> None:
    """根据 weekly_timeouts.yml 就地设置 script['run_timeout_seconds']。

    - 有完整 7 格 → 取当天值，且不低于 10（避免 0 秒杀脚本）。
    - 无条目 / 不足 7 格 → fallback 到 DEFAULT_RUN_TIMEOUT。
    """
    assert "display_name" in script, "[state] script_list 条目缺少 display_name 字段"
    timeouts = weekly_timeouts.get(script["display_name"])
    if timeouts and len(timeouts) == 7:
        script["run_timeout_seconds"] = max(timeouts[get_week_num()], 10)
    else:
        script["run_timeout_seconds"] = DEFAULT_RUN_TIMEOUT


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


def _safe_startfile(parent, path, fail_text):
    """用系统默认程序打开 path；任何异常都转成清晰可读的提示，不让 GUI 崩溃。"""
    try:
        os.startfile(path)
    except OSError as e:
        _styled_msg_box(
            parent, QMessageBox.Warning, "提示", f"{fail_text}：\n{e}"
        ).exec()


# ---------------------------------------------------------------------------
# 脚本图标解析
# ---------------------------------------------------------------------------


def _default_icon() -> QIcon:
    """懒加载默认图标（缺自带图标时回退用）：优先 Python 解释器图标，否则 Chtholly。"""
    global _DEFAULT_ICON
    if _DEFAULT_ICON is None:
        python_icon = _exe_icon(sys.executable)
        _DEFAULT_ICON = (
            python_icon if python_icon is not None else QIcon(_DEFAULT_ICON_PATH)
        )
    return _DEFAULT_ICON


@lru_cache(maxsize=256)
def _exe_icon(path: str) -> QIcon | None:
    """返回 exe 自带图标（OS 文件图标，即程序内嵌图标）。

    文件缺失 / 取不到时返回 None；异常也一并吞掉，不让列表渲染崩溃。
    """
    if not path or not os.path.isfile(path):
        return None
    try:
        icon = QFileIconProvider().icon(QFileInfo(path))
    except Exception:  # noqa: BLE001  # 取图标失败不应影响整个列表
        return None
    return icon if (icon is not None and not icon.isNull()) else None


def get_script_icon(script_data: dict) -> QIcon:
    """返回脚本在列表中显示的图标。

    - external 脚本（指向 exe）：优先使用 exe 内嵌的自带图标；
      取不到（文件缺失 / 无图标）时回退默认图标。
    - python 脚本及其他：使用默认图标。

    调用方（ScriptItem）可缓存结果，本函数仅做轻量解析与缓存。
    """
    if script_data.get("script_type") == "external":
        icon = _exe_icon(script_data.get("script_path", ""))
        if icon is not None:
            return icon
    return _default_icon()
