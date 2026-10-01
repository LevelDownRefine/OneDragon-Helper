"""壁纸目标和映射经 CLI 获取，Qt 负责显示与视频帧编码。"""

import base64

from PySide6.QtCore import QBuffer, QIODevice, Qt, QUrl
from PySide6.QtGui import QImage, QImageReader, QTransform

from gui.controllers.background import WALLPAPER_MAX_SIDE, BackgroundController


class CliBackgroundController(BackgroundController):
    def __init__(self, game_list, session, toast, parent=None):
        super().__init__(game_list, None, toast, parent)
        self._session = session
        self._view = None

    def apply_current(self, game):
        self._bg_version += 1
        version = self._bg_version
        self._view = None
        self._bg_mode = "gradient"
        self._bg_url = self._bg_preview_url = ""
        self._video_preview_attempted = False
        self._grad_color, self._grad_char = game["color"], game["char"]
        self.backgroundChanged.emit()
        name = game["script_name"]

        def loaded(view):
            if version != self._bg_version:
                return
            if not valid_wallpaper(view, name):
                raise ValueError("壁纸数据无效")
            self._view = view
            self._bg_mode = view["mode"]
            path = view["source"]
            if view["mode"] == "image" and view["cache"]:
                if QImageReader(view["cache"]).canRead():
                    path = view["cache"]
            if view["mode"] != "gradient":
                self._bg_url = QUrl.fromLocalFile(path).toString()
            if (
                view["mode"] == "video"
                and view["cache"]
                and QImageReader(view["cache"]).canRead()
            ):
                self._bg_preview_url = QUrl.fromLocalFile(view["cache"]).toString()
            self.backgroundChanged.emit()
            if view["mode"] == "image" and path == view["source"]:
                reader = QImageReader(path)
                size = reader.size()
                if max(size.width(), size.height()) > WALLPAPER_MAX_SIDE:
                    scale = WALLPAPER_MAX_SIDE / max(size.width(), size.height())
                    reader.setScaledSize(size * scale)
                    image = reader.read()
                    if not image.isNull():
                        self._save_cache(image, view, version)

        def failed(failure):
            if version == self._bg_version:
                self._toast(failure.message)

        self._session.call("wallpaper.current", {"script_name": name}, loaded, failed)

    def open_wallpaper(self):
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

        def saved(result):
            if result is not None:
                raise ValueError("壁纸保存响应应返回 null")
            current = self._game_list.current_game
            if current is not None:
                self.apply_current(current)
            self._toast(f"已更换 {game['display_name']} 壁纸")

        self._session.call(
            "wallpaper.set",
            {"script_name": game["script_name"], "file_path": path},
            saved,
            lambda failure: self._toast(failure.message),
        )

    def video_frame_ready(self, sink, version):
        if (
            self._bg_mode != "video"
            or version != self._bg_version
            or self._view is None
        ):
            return False
        frame = sink.videoFrame()
        if not frame.isValid():
            return False
        if self._bg_preview_url or self._video_preview_attempted:
            return True
        self._video_preview_attempted = True
        img = frame.toImage()
        if img.isNull():
            return True
        img = img.transformed(QTransform().rotate(frame.rotation().value))
        if frame.mirrored():
            img = img.mirrored(True, False)
        self._save_cache(img, self._view, version)
        return True

    def _save_cache(self, img, view, version):
        if max(img.width(), img.height()) > WALLPAPER_MAX_SIDE:
            img = img.scaled(
                WALLPAPER_MAX_SIDE,
                WALLPAPER_MAX_SIDE,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        buffer = QBuffer()
        buffer.open(QIODevice.WriteOnly)
        if not img.convertToFormat(QImage.Format_RGB888).save(
            buffer, "JPG", quality=90
        ):
            self._toast("壁纸预览编码失败")
            return

        def saved(result):
            if type(result) is not bool:
                raise ValueError("缓存保存响应无效")
            if result and version == self._bg_version:
                self._session.call(
                    "wallpaper.current",
                    {"script_name": view["script_name"]},
                    preview,
                    lambda failure: self._toast(failure.message),
                )

        def preview(current):
            if version != self._bg_version:
                return
            if not valid_wallpaper(current, view["script_name"]):
                raise ValueError("视频预览响应无效")
            if current["token"] == view["token"] and current["cache"]:
                url = QUrl.fromLocalFile(current["cache"]).toString()
                if view["mode"] == "video":
                    self._bg_preview_url = url
                else:
                    self._bg_url = url
                self.backgroundChanged.emit()

        self._session.call(
            "wallpaper.cache",
            {
                "script_name": view["script_name"],
                "token": view["token"],
                "jpeg_base64": base64.b64encode(bytes(buffer.data())).decode("ascii"),
            },
            saved,
            lambda failure: self._toast(failure.message),
        )


def valid_wallpaper(view, name):
    return (
        isinstance(view, dict)
        and all(
            key in view
            for key in (
                "script_name",
                "display_name",
                "mode",
                "source",
                "cache",
                "token",
                "custom_path",
            )
        )
        and view["script_name"] == name
        and isinstance(view["display_name"], str)
        and isinstance(view["mode"], str)
        and view["mode"] in {"gradient", "image", "video"}
        and isinstance(view["source"], str)
        and all(
            view[key] is None or isinstance(view[key], str)
            for key in ("cache", "token", "custom_path")
        )
        and (view["mode"] == "gradient" or bool(view["source"] and view["token"]))
    )
