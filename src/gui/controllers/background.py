"""背景控制器：背景模式（视频/图片/渐变）/ 壁纸 / 视频错误回退。

独立 QObject，自管状态（_bg_mode / _bg_url / _grad_color / _grad_char）。
按当前选中脚本刷新背景，并联动刷新任务卡（task_card 经构造注入引用）。
壁纸文件的读写仍走 QmlBridge 门面（_load_bg / _wallpapers / _save_wallpapers），
使测试可 mock 这些门面方法。
"""

import os

from PySide6.QtCore import QObject, QUrl, Signal, Slot

from src.config.subscript import resolve_script_path
from src.gui.providers import is_video


class BackgroundController(QObject):
    backgroundChanged = Signal()
    toastRequested = Signal(str)

    def __init__(self, game_list, task_card, toast, parent=None):
        super().__init__(parent)
        self._game_list = game_list
        self._task_card = task_card
        self._toast = toast
        # 默认（apply_current 会在构造末尾按选中脚本刷新，此处防首帧 undefined）
        self._bg_mode = "gradient"
        self._bg_url = ""
        self._grad_color = "#3a3f52"
        self._grad_char = ""

    # ── 读接口（供 QmlBridge 委托）────────────────────────────────────
    @property
    def background_mode(self) -> str:
        return self._bg_mode

    @property
    def background_url(self) -> str:
        return self._bg_url

    @property
    def gradient_color(self) -> str:
        return self._grad_color

    @property
    def gradient_char(self) -> str:
        return self._grad_char

    def apply_current(self, game: dict, bg_path: str | None):
        """按当前选中脚本刷新背景：自定义壁纸 → 脚本背景 → 渐变兜底。"""
        if bg_path and is_video(bg_path) and os.path.isfile(bg_path):
            self._bg_mode = "video"
            self._bg_url = QUrl.fromLocalFile(bg_path).toString()
        elif bg_path and os.path.isfile(bg_path):
            self._bg_mode = "image"
            self._bg_url = QUrl.fromLocalFile(bg_path).toString()
        else:
            self._bg_mode = "gradient"
            self._bg_url = ""
        self._grad_color = game["color"]
        self._grad_char = game["char"]
        self.backgroundChanged.emit()
        self._task_card.refresh()

    def read_wallpapers(self) -> dict:
        """读取 config/wallpaper.json（脚本 → 壁纸路径）；缺失返回空。"""
        import json

        path = resolve_script_path("config/wallpaper.json")
        if not os.path.isfile(path):
            return {}
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def write_wallpapers(self, wallpapers: dict):
        import json

        path = resolve_script_path("config/wallpaper.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(wallpapers, f, ensure_ascii=False, indent=2)

    @Slot(str)
    def videoError(self, reason: str):
        """QML VideoOutput 媒体错误：回退渐变（QML 侧 MediaPlayer 触发）。"""
        import warnings

        warnings.warn(
            f"[qml] 视频背景不可用，回退：{reason or '媒体解码错误'}",
            RuntimeWarning,
            stacklevel=2,
        )
        self._bg_mode = "gradient"
        self._bg_url = ""
        self.backgroundChanged.emit()
