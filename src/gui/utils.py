"""GUI 工具与 UI 状态持久化。

- UI 状态持久化（config/gui_state.json）与星期计算；
- 统一的消息框 / 打开文件辅助函数（强制浅色样式，避免深色主题下全黑不可读）。

图标相关逻辑已迁移到 :mod:`src.gui.icons`（与 UI 状态/消息框职责分离）。
"""

import json
import logging
import os
from datetime import datetime, timedelta

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from src.utils import get_root_dir, safe_path_join

logger = logging.getLogger(__name__)

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
