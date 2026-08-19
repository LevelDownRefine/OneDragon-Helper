"""背景控制器：背景模式（视频/图片/渐变）/ 壁纸 / 视频错误回退。

独立 QObject，自管状态（_bg_mode / _bg_url / _grad_color / _grad_char）。
壁纸读写（read_wallpapers / write_wallpapers）与路径解析（resolve_bg）均归本控制器。
"""

import os

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtWidgets import QFileDialog

from src.config.set_config import get_game_bg_img as _get_game_bg_img
from src.config.subscript import resolve_script_path

# 兜底背景：脚本未配置背景图时使用（相对项目根）
DEFAULT_BG = "assets/ds.jpg"


def is_video(path: str) -> bool:
    """判断路径是否为视频背景（其余按图片处理）。"""
    return os.path.splitext(path)[1].lower() in {".mp4", ".webm", ".mkv", ".mov"}


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

    def resolve_bg(self, game: dict) -> str | None:
        """返回该脚本应使用的背景路径（自定义壁纸 → 脚本背景 → DEFAULT_BG）。

        文件不存在返回 None（走渐变兜底）。

        Args:
            game: 当前脚本数据。
        """
        custom = self.read_wallpapers().get(game["script_name"])
        bg_path = custom or (_get_game_bg_img(game["script_name"]) or DEFAULT_BG)
        resolved = resolve_script_path(bg_path)
        if not os.path.isfile(resolved):
            return None
        return resolved

    def apply_current(self, game: dict):
        """按当前选中脚本刷新背景（路径经 resolve_bg 解析）。

        Args:
            game: 当前脚本数据（提供颜色与首字）。
        """
        bg_path = self.resolve_bg(game)
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

    @Slot()
    def open_wallpaper(self):
        """更换当前脚本壁纸：弹文件选择 → 写壁纸表 → 刷新背景。"""
        game = self._game_list.current_game
        path, _ = QFileDialog.getOpenFileName(
            None,
            f"选择 {game['display_name']} 壁纸",
            "",
            "图片/视频 (*.png *.jpg *.jpeg *.webp *.bmp *.mp4 *.webm *.mkv *.mov)",
        )
        if not path:
            return
        wallpapers = self.read_wallpapers()
        wallpapers[game["script_name"]] = path
        self.write_wallpapers(wallpapers)
        self.apply_current(game)
        self._toast(f"已更换 {game['display_name']} 壁纸")

    def read_wallpapers(self) -> dict:
        """读取 config/wallpaper.json（脚本 → 壁纸路径），缺失返回空。"""
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
        """视频背景解码失败时回退渐变。

        Args:
            reason: QML MediaPlayer 上报的错误描述。
        """
        import warnings

        warnings.warn(
            f"[qml] 视频背景不可用，回退：{reason or '媒体解码错误'}",
            RuntimeWarning,
            stacklevel=2,
        )
        self._bg_mode = "gradient"
        self._bg_url = ""
        self.backgroundChanged.emit()
