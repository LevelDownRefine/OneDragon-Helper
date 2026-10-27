"""背景的 Qt 展示状态；壁纸查询和保存由 RPC 控制器负责。"""

import logging

from PySide6.QtCore import QObject, Signal, Slot

logger = logging.getLogger(__name__)
WALLPAPER_MAX_SIDE = 1920


class BackgroundController(QObject):
    backgroundChanged = Signal()
    toastRequested = Signal(str)

    def __init__(self, game_list, toast, parent=None):
        super().__init__(parent)
        self._game_list = game_list
        self._toast = toast
        self._bg_mode = "gradient"
        self._bg_url = ""
        self._bg_preview_url = ""
        self._video_preview_attempted = False
        self._bg_version = 0
        self._grad_color = "#3a3f52"
        self._grad_char = ""

    @property
    def background_mode(self) -> str:
        return self._bg_mode

    @property
    def background_url(self) -> str:
        return self._bg_url

    @property
    def background_preview_url(self) -> str:
        return self._bg_preview_url

    @property
    def gradient_color(self) -> str:
        return self._grad_color

    @property
    def gradient_char(self) -> str:
        return self._grad_char

    @property
    def background_version(self) -> int:
        return self._bg_version

    @Slot(str)
    def videoError(self, reason: str):
        """解码失败时保留已有预览，没有预览则显示渐变。"""
        logger.warning("[qml] 视频背景不可用，回退：%s", reason or "媒体解码错误")
        self._bg_mode = "image" if self._bg_preview_url else "gradient"
        self._bg_url = self._bg_preview_url
        self.backgroundChanged.emit()
