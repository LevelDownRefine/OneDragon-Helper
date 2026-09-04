"""背景控制器：背景模式（视频/图片/渐变）/ 壁纸 / 视频错误回退。

独立 QObject，自管状态（_bg_mode / _bg_url / _grad_color / _grad_char）。
壁纸读写（read_wallpapers / write_wallpapers）与路径解析（resolve_bg）均归本控制器。
"""

import logging
import os

from PySide6.QtCore import QObject, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QFileDialog

from src.config.set_config import get_background_rel_path
from src.utils.utils_sub_config import get_script_root_dir_soft, resolve_script_path

logger = logging.getLogger(__name__)

# 兜底背景：脚本未配置背景图时使用（相对项目根）
DEFAULT_BG = "assets/ds.jpg"

# 自定义壁纸缓存：用户选图时按最长边压到 WALLPAPER_MAX_SIDE 后存于
# config/wallpaper_cache/<script_name>.jpg，resolve_bg 优先返回缓存，避免大图
# 直接进 GPU 纹理（与 main.qml 的 sourceSize 互补）。视频壁纸不缓存。
WALLPAPER_CACHE_DIR = "config/wallpaper_cache"
WALLPAPER_MAX_SIDE = 1920


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
        self._bg_version = 0  # 每次刷新背景自增，供 QML 强制重载图片（见 main.qml）
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

    @property
    def background_version(self) -> int:
        return self._bg_version

    def resolve_bg(self, game: dict) -> str | None:
        """返回该脚本应使用的背景路径（自定义壁纸缓存 → 自定义壁纸 → 脚本背景 → DEFAULT_BG）。

        文件不存在返回 None（走渐变兜底）。

        Args:
            game: 当前脚本数据。
        """
        resolved = resolve_script_path(self._wallpaper_for(game))
        if not os.path.isfile(resolved):
            return None
        return resolved

    def _script_background(self, script_name: str) -> str:
        """读取脚本默认背景图绝对路径（声明在 ScriptConfig.background，相对脚本根目录）。

        Args:
            script_name: 脚本标识名。

        Returns:
            背景图绝对路径；未适配/未声明/文件缺失 → 空字符串（交 DEFAULT_BG 兜底）。
        """
        rel = get_background_rel_path(script_name)
        if not rel:
            return ""
        root = get_script_root_dir_soft(script_name)
        if not root:
            return ""
        path = os.path.join(root, rel)
        return path if os.path.isfile(path) else ""

    def _wallpaper_for(self, game: dict) -> str:
        """解析某脚本应使用的背景路径：定位源（自定义壁纸 → 脚本背景图 → DEFAULT_BG），
        并判定图像/视频。图像交给 _build_wallpaper_cache 确保缓存，视频直接用源路径。
        resolve_bg 负责 resolve + isfile 守卫。

        Args:
            game: 当前脚本数据。
        """
        script_name = game["script_name"]
        wallpapers = self.read_wallpapers()
        if script_name not in wallpapers:
            return self._script_background(script_name) or DEFAULT_BG
        src_path = wallpapers[script_name]
        if not os.path.isfile(src_path):
            return src_path  # 源图缺失：交回 resolve_bg 的 isfile 守卫，走渐变兜底
        if is_video(src_path):
            return src_path  # 视频壁纸不缓存：直接用源路径，交 QML 播放
        return self._build_wallpaper_cache(src_path, script_name) or src_path

    def _build_wallpaper_cache(
        self, src_path: str, script_name: str, force: bool = False
    ) -> str | None:
        """确保某自定义壁纸（调用方已确认是图像且存在）的缓存可用。

        force=False（解析 / 复用路径）：缓存存在且较新直接返回，避免重复压缩大图。
        force=True（用户刚更换壁纸）：源文件已变，先删旧缓存再重建，杜绝旧缓存被当成较新返回。

        Args:
            src_path: 用户原图路径（图像）。
            script_name: 脚本标识（缓存文件名）。
            force: 是否强制重建（换壁纸时 True）。
        """
        if not os.path.isfile(src_path):
            return None
        cache = os.path.join(
            resolve_script_path(WALLPAPER_CACHE_DIR), f"{script_name}.jpg"
        )
        if force and os.path.isfile(cache):
            try:
                os.remove(cache)  # 换壁纸：清掉旧缓存，避免旧内容（不同源）被误用
            except OSError as e:
                logger.warning(
                    "[bg] 旧壁纸缓存删除失败（可能被占用），将覆盖：%s",
                    type(e).__name__,
                )
        if (
            not force
            and os.path.isfile(cache)
            and os.path.getmtime(cache) >= os.path.getmtime(src_path)
        ):
            return cache
        try:
            img = QImage(src_path)
            if img.isNull():
                logger.warning("[bg] 壁纸解码失败，跳过缓存：%s", src_path)
                return None
            src_w, src_h = img.width(), img.height()
            longest = max(src_w, src_h)
            if longest <= WALLPAPER_MAX_SIDE:
                return None
            scale = WALLPAPER_MAX_SIDE / longest
            out = img.scaled(
                max(1, round(src_w * scale)),
                max(1, round(src_h * scale)),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            ).convertToFormat(QImage.Format_RGB888)
            os.makedirs(os.path.dirname(cache), exist_ok=True)
            if not out.save(cache, "JPG", quality=90):
                logger.warning("[bg] 壁纸缓存写入失败：%s", cache)
                return None
        except (OSError, MemoryError) as e:
            logger.warning(
                "[bg] 壁纸缓存生成失败（%s），回退原图", type(e).__name__, exc_info=True
            )
            return None
        return cache

    def apply_current(self, game: dict):
        """按当前选中脚本刷新背景（路径经 resolve_bg 解析）。

        Args:
            game: 当前脚本数据（提供颜色与首字）。
        """
        self._bg_version += (
            1  # 即便 source 路径不变（换壁纸复用同缓存），也强制 QML 重载
        )
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
        if not is_video(path):
            self._build_wallpaper_cache(
                path, game["script_name"], force=True
            )  # 换壁纸：强制重建覆盖旧缓存
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
        logger.warning("[qml] 视频背景不可用，回退：%s", reason or "媒体解码错误")
        self._bg_mode = "gradient"
        self._bg_url = ""
        self.backgroundChanged.emit()
