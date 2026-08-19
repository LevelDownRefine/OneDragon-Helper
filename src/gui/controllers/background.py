"""背景控制器：背景模式（视频/图片/渐变）/ 壁纸 / 视频错误回退。

共享状态（_games / _grad_* / icon_provider）由 BridgeBase 持有。_apply_current
按当前选中脚本刷新背景，并联动刷新任务卡（_refresh_task_card 由 TaskCardController
提供，经门面 QmlBridge 的 MRO 在运行时解析）。
"""

import os

from PySide6.QtCore import Property, QUrl, Signal, Slot

from src.config.set_config import get_game_bg_img as _get_game_bg_img
from src.config.subscript import resolve_script_path
from src.gui.controllers.base import BridgeBase
from src.gui.providers import is_video
from src.gui.theme import DEFAULT_BG


class BackgroundController(BridgeBase):
    # notify 信号就地定义（与 property 同类），避免 PySide6 跨类 notify 段错误
    backgroundChanged = Signal()

    @Property(str, notify=backgroundChanged)
    def backgroundMode(self) -> str:
        return self._bg_mode

    @Property(str, notify=backgroundChanged)
    def backgroundUrl(self) -> str:
        return self._bg_url

    @Property(str, notify=backgroundChanged)
    def gradientColor(self) -> str:
        return self._grad_color

    @Property(str, notify=backgroundChanged)
    def gradientChar(self) -> str:
        return self._grad_char

    def _apply_current(self):
        """按当前选中脚本刷新背景：自定义壁纸 → 脚本背景 → 渐变兜底。"""
        game = self._games[self.current_index]
        path = self._load_bg(game)
        if path and is_video(path) and os.path.isfile(path):
            self._bg_mode = "video"
            self._bg_url = QUrl.fromLocalFile(path).toString()
        elif path and os.path.isfile(path):
            self._bg_mode = "image"
            self._bg_url = QUrl.fromLocalFile(path).toString()
        else:
            self._bg_mode = "gradient"
            self._bg_url = ""
        self._grad_color = game["color"]
        self._grad_char = game["char"]
        self.backgroundChanged.emit()
        self._refresh_task_card()

    def _load_bg(self, game: dict) -> str | None:
        """返回该脚本应使用的背景路径（自定义壁纸 → 脚本背景 → DEFAULT_BG）。

        文件不存在返回 None（走渐变）；扩展名由调用方分发（视频/图片）。
        """
        custom = self._wallpapers().get(game["script_name"])
        bg_path = custom or (_get_game_bg_img(game["script_name"]) or DEFAULT_BG)
        resolved = resolve_script_path(bg_path)
        if not os.path.isfile(resolved):
            return None
        return resolved

    def _wallpapers(self) -> dict:
        """读取 config/wallpaper.json（脚本 → 壁纸路径）；缺失返回空。"""
        import json

        path = resolve_script_path("config/wallpaper.json")
        if not os.path.isfile(path):
            return {}
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    @Slot()
    def openWallpaper(self):
        """更改当前脚本壁纸并持久化到 config/wallpaper.json（对齐旧 GUI）。"""
        from PySide6.QtWidgets import QFileDialog

        game = self._current_game()
        path, _ = QFileDialog.getOpenFileName(
            None,
            f"选择 {game['display_name']} 壁纸",
            "",
            "图片/视频 (*.png *.jpg *.jpeg *.webp *.bmp *.mp4 *.webm *.mkv *.mov)",
        )
        if not path:
            return
        wallpapers = self._wallpapers()
        wallpapers[game["script_name"]] = path
        self._save_wallpapers(wallpapers)
        self._apply_current()
        self.toastRequested.emit(f"已更换 {game['display_name']} 壁纸")

    def _save_wallpapers(self, wallpapers: dict):
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
