"""GUI 工具：统一消息框 / 打开文件辅助 / 共享按钮工厂。

样式模板（按钮、消息框）已抽到 :mod:`src.gui.theme`，本模块只保留 Qt 工具函数
与对 theme 工厂的转发。UI 状态持久化见 :mod:`src.service.chain_service`，每周超时
应用见 :mod:`src.service.chain_gen`，默认超时常量见 :mod:`src.config.subscript`
（均无 Qt，GUI 与 CLI 共用，由调用方直接 import）。图标相关逻辑在
:mod:`src.gui.icons`。
"""

import logging
import os
import warnings

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from src.gui.theme import (
    make_icon_button,
    make_pill_button,
    make_secondary_button,
    message_box_qss,
)

logger = logging.getLogger(__name__)

__all__ = [
    "_styled_msg_box",
    "safe_startfile",
    "make_pill_button",
    "make_secondary_button",
    "make_icon_button",
]


# ---------------------------------------------------------------------------
# 统一消息框 / 打开文件辅助（强制浅色样式，避免深色主题下全黑不可读）
# ---------------------------------------------------------------------------


def _styled_msg_box(parent, icon, title, text):
    """构造一个样式固定的消息框（白底深字，带图标），直接 .exec() 即可。"""
    box = QMessageBox(parent)
    box.setIcon(icon)
    box.setWindowTitle(title)
    box.setText(text)
    box.setTextFormat(Qt.PlainText)
    box.setStyleSheet(message_box_qss())
    return box


def safe_startfile(parent, path, fail_text):
    """用系统默认程序打开 path；任何异常都转成清晰可读的提示，不让 GUI 崩溃。"""
    try:
        os.startfile(path)
    except OSError as e:
        warnings.warn(f"{fail_text}: {e}", RuntimeWarning, stacklevel=2)
        _styled_msg_box(
            parent, QMessageBox.Warning, "提示", f"{fail_text}：\n{e}"
        ).exec()
