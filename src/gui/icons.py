"""图标模块：脚本 exe 图标获取 + GitHub SVG 常量。

- 脚本图标（从 src/gui/icons.py 合并）：``get_script_icon`` 同步链——external
  脚本用 exe 自带图标（崩铁优先同目录 March7th Launcher.exe），python 脚本用
  默认图标（Python 解释器图标，取不到回退 assets/ds.ico）。
- ``_GITHUB_SVG``：GitHub Octocat 单色 SVG（Simple Icons 路径，白色），供
  QML 的 ``UiIconProvider`` 渲染（main_window 导入）。

旧 GUI（main_window.py / widgets.py 自绘控件）所用自绘 ``GlyphButton`` /
``IconButton`` 与 ``draw_*`` 绘制函数已随旧 GUI 移除，本模块不再含 Qt 绘制逻辑。

依赖单向：icons → config.subscript / utils；main_window → icons。
"""

import logging
import os
import sys
from functools import lru_cache

from PySide6.QtCore import QFileInfo
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QFileIconProvider

from src.config.subscript import resolve_script_path
from src.utils import get_root_dir, safe_path_join

logger = logging.getLogger(__name__)


# GitHub Octocat 单色 SVG（Simple Icons 路径，白色）
_GITHUB_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    '<path fill="#FFFFFF" d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 '
    "8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724"
    "-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744"
    ".084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 "
    "1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466"
    "-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 "
    "1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 "
    "2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 "
    "1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 "
    "2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 "
    '17.592 24 12.297c0-6.627-5.373-12-12-12"/>'
    "</svg>"
)


# 复用的文件图标提供器：避免每个 exe 都 new 一个 QFileIconProvider 的开销
_ICON_PROVIDER = QFileIconProvider()

# 默认图标：没有自带图标的脚本（如 python 脚本，或 external 但取不到 exe 图标的）使用。
# 优先用当前 Python 解释器（sys.executable）的 OS 文件图标，即 Python 官方图标；
# 极个别取不到时（如冻结后 sys.executable 指向自身 exe）回退到 assets/ds.ico。
_DEFAULT_ICON_PATH = safe_path_join(get_root_dir(), "assets", "ds.ico")
_DEFAULT_ICON: QIcon | None = None


def _default_icon() -> QIcon:
    """懒加载默认图标（缺自带图标时回退用）：优先 Python 解释器图标，否则 ds。"""
    global _DEFAULT_ICON
    if _DEFAULT_ICON is None:
        python_icon = _exe_icon(sys.executable)
        _DEFAULT_ICON = (
            python_icon if python_icon is not None else QIcon(_DEFAULT_ICON_PATH)
        )
    return _DEFAULT_ICON


@lru_cache
def _exe_icon(path: str) -> QIcon | None:
    """返回 exe 自带图标（OS 文件图标，即程序内嵌图标）。

    文件缺失 / 取不到时返回 None；异常也一并吞掉，不让列表渲染崩溃。
    """
    if not path or not os.path.isfile(path):
        return None
    try:
        icon = _ICON_PROVIDER.icon(QFileInfo(path))
    except Exception:  # noqa: BLE001  # 取图标失败不应影响整个列表
        logger.warning("取 %s 的图标失败", path, exc_info=True)
        return None
    return icon if (icon is not None and not icon.isNull()) else None


def get_icon_source(script_data: dict) -> str | None:
    """返回脚本图标所用的 exe 路径（崩铁优先同目录 March7th Launcher.exe）。"""
    if script_data.get("script_type") != "external":
        return None
    raw = script_data.get("script_path", "")
    if not raw:
        return None
    script_path = resolve_script_path(raw)
    launcher = os.path.join(os.path.dirname(script_path), "March7th Launcher.exe")
    if os.path.isfile(launcher):
        return launcher
    return script_path


def get_script_icon(script_data: dict) -> QIcon:
    """返回脚本在列表中显示的图标。

    - external 脚本（指向 exe）：优先使用 exe 内嵌的自带图标；
      取不到（文件缺失 / 无图标）时回退默认图标。
    - python 脚本及其他：使用默认图标。

    调用方（GameIcon）可缓存结果，本函数仅做轻量解析与缓存。
    """
    source = get_icon_source(script_data)
    if source:
        icon = _exe_icon(source)
        if icon is not None:
            return icon
    return _default_icon()
