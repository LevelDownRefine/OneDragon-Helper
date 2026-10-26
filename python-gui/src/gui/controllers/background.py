"""背景控制器：背景模式（视频/图片/渐变）/ 壁纸 / 视频错误回退。

独立 QObject，自管状态（_bg_mode / _bg_url / _grad_color / _grad_char）。
数据源为 ``AppService.wallpaper_view``（与 Rust 前端 ``wallpaper.view`` 同一
视图）：解析优先级（自定义 → 脚本声明 → 渐变）、图/视频判定、缓存落点与
token 全由后端给出；本控制器只做 Qt 渲染关注点——缓存图的解码缩放、JPEG
编码与首帧预览，写盘经 ``save_wallpaper_cache`` / ``save_video_preview``。
"""

import base64
import logging
import os

from PySide6.QtCore import QBuffer, QIODevice, QObject, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QImage, QImageReader, QTransform

# QML 首次传入对象前注册包装类型，否则 QVideoSink 会被包装成普通 QObject。
from PySide6.QtMultimedia import QVideoSink

from src.utils.utils_wallpaper import InvalidWallpaper

logger = logging.getLogger(__name__)

# 壁纸按最长边压到 WALLPAPER_MAX_SIDE 后交 service 落盘缓存，避免大图直接进
# GPU 纹理（与 main.qml 的 sourceSize 互补）；视频首帧复用此尺寸上限。
WALLPAPER_MAX_SIDE = 1920

# 脚本为空或已被移除时的收缩视图（与 wallpaper_view 的 gradient 形态一致）。
_GRADIENT_VIEW = {
    "mode": "gradient",
    "source": "",
    "token": None,
    "cache": None,
}


class BackgroundController(QObject):
    backgroundChanged = Signal()
    toastRequested = Signal(str)

    def __init__(self, game_list, app_service, toast, parent=None):
        super().__init__(parent)
        self._game_list = game_list
        self._app_service = app_service
        self._toast = toast
        # 默认（apply_current 会在构造末尾按选中脚本刷新，此处防首帧 undefined）
        self._bg_mode = "gradient"
        self._bg_url = ""
        self._bg_preview_url = ""
        self._video_cache_path = None
        self._video_preview_attempted = False
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

    def _wallpaper_view(self, script_name: str) -> dict:
        """取当前脚本的壁纸视图；脚本为空/已移除时收缩为渐变。"""
        if not script_name:
            return _GRADIENT_VIEW
        try:
            view = self._app_service.wallpaper_view(script_name)
            assert all(
                key in view
                for key in ("script_name", "mode", "source", "token", "cache")
            )
            return view
        except InvalidWallpaper:
            logger.debug("[bg] 脚本已移除，背景回退渐变：%s", script_name)
            return _GRADIENT_VIEW

    def _build_image_cache(self, view: dict) -> str | None:
        """为大图生成压缩缓存（小图跳过）；成功返回缓存路径。

        缓存落点与新鲜度（token）由视图给出：源已变化时后端拒收，不会写串。
        """
        assert all(key in view for key in ("script_name", "source", "token"))
        source = view["source"]
        try:
            # 只读图像头判断尺寸：长边未超上限时无需生成缓存，跳过整图解码。
            dims = QImageReader(source).size()
            if dims.width() <= 0 or dims.height() <= 0:
                logger.warning("[bg] 壁纸解码失败，跳过缓存：%s", source)
                return None
            longest = max(dims.width(), dims.height())
            if longest <= WALLPAPER_MAX_SIDE:
                return None
            scale = WALLPAPER_MAX_SIDE / longest
            img = QImage(source)
            if img.isNull():
                logger.warning("[bg] 壁纸解码失败，跳过缓存：%s", source)
                return None
            scaled = img.scaled(
                max(1, round(dims.width() * scale)),
                max(1, round(dims.height() * scale)),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            ).convertToFormat(QImage.Format_RGB888)
            buffer = QBuffer()
            buffer.open(QIODevice.WriteOnly)
            if not scaled.save(buffer, "JPG", quality=90):
                logger.warning("[bg] 壁纸缓存编码失败，回退原图")
                return None
            saved = self._app_service.save_wallpaper_cache(
                view["script_name"],
                view["token"],
                base64.b64encode(bytes(buffer.data())).decode("ascii"),
            )
        except (InvalidWallpaper, OSError, MemoryError) as e:
            logger.warning(
                "[bg] 壁纸缓存生成失败（%s），回退原图", type(e).__name__, exc_info=True
            )
            return None
        if not saved:
            logger.warning("[bg] 壁纸缓存写入被拒（源已变化？）：%s", source)
            return None
        current = self._wallpaper_view(view["script_name"])
        assert "token" in current and "cache" in current
        return current["cache"] if current["token"] == view["token"] else None

    def apply_current(self, game: dict):
        """按当前选中脚本的壁纸视图刷新背景（解码缩放留在 Qt，策略归后端）。

        Args:
            game: 当前脚本数据（提供颜色与首字）。
        """
        self._bg_version += (
            1  # 即便 source 路径不变（换壁纸复用同缓存），也强制 QML 重载
        )
        view = self._wallpaper_view(game["script_name"])
        mode = view["mode"]
        self._bg_preview_url = ""
        self._video_cache_path = None
        self._video_preview_attempted = False
        if mode == "video":
            assert isinstance(view["source"], str) and view["source"]
            self._bg_mode = "video"
            self._bg_url = QUrl.fromLocalFile(view["source"]).toString()
            # cache 只表示已存在的预览；首次播放也须由 service 给出保存位置。
            self._video_cache_path = view[
                "cache"
            ] or self._app_service.video_preview_path(view["source"])
            if view["cache"] and os.path.isfile(view["cache"]):
                if QImageReader(self._video_cache_path).canRead():
                    self._bg_preview_url = QUrl.fromLocalFile(
                        self._video_cache_path
                    ).toString()
                else:
                    logger.warning(
                        "[bg] 视频预览损坏，将重新生成：%s", self._video_cache_path
                    )
        elif mode == "image":
            # 后端 mode=image 已保证源存在；缓存就绪用缓存，小图跳过缓存用源。
            cache = view["cache"]
            if cache and not QImageReader(cache).canRead():
                logger.warning("[bg] 图片缓存损坏，将重新生成：%s", cache)
                cache = None
            bg_path = cache or self._build_image_cache(view) or view["source"]
            self._bg_mode = "image"
            self._bg_url = QUrl.fromLocalFile(bg_path).toString()
        else:
            self._bg_mode = "gradient"
            self._bg_url = ""
        self._grad_color = game["color"]
        self._grad_char = game["char"]
        self.backgroundChanged.emit()

    def video_frame_ready(self, sink: QVideoSink, version: int) -> bool:
        """首个有效视频帧解除占位；图片编码留在 GUI，写盘交给 service。"""
        if self._bg_mode != "video" or version != self._bg_version:
            return False
        assert isinstance(sink, QVideoSink)
        frame = sink.videoFrame()
        if not frame.isValid():
            return False
        if self._bg_preview_url or self._video_preview_attempted:
            return True
        self._video_preview_attempted = True
        if self._video_cache_path is None:
            return True
        try:
            img = frame.toImage()
            if img.isNull():
                logger.warning("[bg] 视频首帧转图片失败，跳过缓存")
                return True
            # toImage 已处理 surface format；帧本身的显示变换需另行应用。
            img = img.transformed(QTransform().rotate(frame.rotation().value))
            if frame.mirrored():
                img = img.mirrored(True, False)
            if max(img.width(), img.height()) > WALLPAPER_MAX_SIDE:
                img = img.scaled(
                    WALLPAPER_MAX_SIDE,
                    WALLPAPER_MAX_SIDE,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
            buffer = QBuffer()
            buffer.open(QIODevice.WriteOnly)
            if not img.save(buffer, "JPG", quality=90):
                logger.warning("[bg] 视频首帧编码失败，跳过缓存")
                return True
            saved = self._app_service.save_video_preview(
                QUrl(self._bg_url).toLocalFile(),
                self._video_cache_path,
                bytes(buffer.data()),
            )
        except MemoryError as e:
            logger.warning("[bg] 视频首帧缓存失败(%s)，继续播放", type(e).__name__)
            return True
        if saved:
            self._bg_preview_url = QUrl.fromLocalFile(self._video_cache_path).toString()
            self.backgroundChanged.emit()
        return True

    @Slot()
    def open_wallpaper(self):
        """更换当前脚本壁纸：弹文件选择 → 经 service 写壁纸表 → 刷新背景。"""
        game = self._game_list.current_game
        if game is None:
            self._toast("尚无脚本")
            return
        from gui.dialogs import pick_file

        path = pick_file(
            None,
            f"选择 {game['display_name']} 壁纸",
            "图片/视频 (*.png *.jpg *.jpeg *.webp *.bmp *.mp4 *.webm *.mkv *.mov)",
        )
        if not path:
            return
        # 新源 → 新 token → 新缓存落点，无需强制清旧缓存（后端按内容身份管理）。
        self._app_service.set_wallpaper(game["script_name"], path)
        self.apply_current(game)
        self._toast(f"已更换 {game['display_name']} 壁纸")

    @Slot(str)
    def videoError(self, reason: str):
        """视频背景解码失败时保留预览图，无缓存则回退渐变。

        Args:
            reason: QML MediaPlayer 上报的错误描述。
        """
        logger.warning("[qml] 视频背景不可用，回退：%s", reason or "媒体解码错误")
        self._bg_mode = "image" if self._bg_preview_url else "gradient"
        self._bg_url = self._bg_preview_url
        self.backgroundChanged.emit()
