"""壁纸来源与映射；图像解码由前端负责，缓存落盘仍经 service。"""

import base64
import binascii
import hashlib
import json
import os

from src.config.set_config import get_background_rel_path
from src.utils import get_wallpaper_json_path_under_root
from src.utils.utils_config import get_script
from src.utils.utils_sub_config import get_script_root_dir, resolve_script_path
from src.utils.utils_wallpaper import load_wallpapers, save_wallpapers

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mkv", ".mov"}
MAX_CACHE_BYTES = 4 * 1024 * 1024


class InvalidWallpaper(ValueError):
    """外部文件或壁纸请求无效。"""


def wallpaper_view(script_name: str) -> dict:
    """按自定义、脚本声明、助手默认的顺序解析；缺失自定义文件走渐变。"""
    script = get_script(script_name)
    if script is None:
        raise InvalidWallpaper("脚本已不存在，请刷新列表")
    assert "display_name" in script
    wallpapers = load_wallpapers()
    custom_path = None
    if script_name in wallpapers:
        custom_path = wallpapers[script_name]
        if not isinstance(custom_path, str) or not custom_path:
            raise InvalidWallpaper("壁纸路径无效，请重置")
        source = resolve_script_path(custom_path)
    else:
        source = ""
        relative = get_background_rel_path(script_name)
        if relative:
            root = get_script_root_dir(script_name)
            if root:
                candidate = os.path.join(root, relative)
                if os.path.isfile(candidate):
                    source = candidate
        if not source:
            source = resolve_script_path("assets/ds.jpg")
    source = os.path.abspath(source)
    mode = (
        "video" if os.path.splitext(source)[1].lower() in VIDEO_EXTENSIONS else "image"
    )
    token = None
    cache = None
    if os.path.isfile(source):
        stat = os.stat(source)
        identity = json.dumps(
            [os.path.normcase(source), stat.st_size, stat.st_mtime_ns]
        )
        token = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        prefix = "video_" if mode == "video" else "rust_image_"
        cache = os.path.join(
            os.path.dirname(get_wallpaper_json_path_under_root()),
            "wallpaper_cache",
            f"{prefix}{token}.jpg",
        )
    else:
        mode = "gradient"
    return {
        "script_name": script_name,
        "display_name": script["display_name"],
        "mode": mode,
        "source": source,
        "custom_path": custom_path,
        "token": token,
        "cache": cache if cache and os.path.isfile(cache) else None,
    }


def set_wallpaper(script_name: str, file_path: str | None) -> None:
    """只修改当前脚本映射；空值重置为脚本/助手默认，不删除原文件。"""
    if get_script(script_name) is None:
        raise InvalidWallpaper("脚本已不存在，请刷新列表")
    if file_path is not None:
        if not isinstance(file_path, str) or not file_path.strip():
            raise InvalidWallpaper("请选择图片或视频")
        file_path = os.path.abspath(resolve_script_path(file_path.strip()))
        if (
            os.path.splitext(file_path)[1].lower()
            not in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS
        ):
            raise InvalidWallpaper("不支持此壁纸格式")
        if not os.path.isfile(file_path):
            raise InvalidWallpaper("壁纸文件不存在")
    wallpapers = load_wallpapers()
    if file_path is None:
        if script_name in wallpapers:
            del wallpapers[script_name]
    else:
        wallpapers[script_name] = file_path
    save_wallpapers(wallpapers)


def save_wallpaper_cache(script_name: str, token: str, jpeg_base64: str) -> bool:
    """只接受当前来源的有界 JPEG 缓存；路径由 service 生成，过期解码丢弃。"""
    if not isinstance(token, str) or not token:
        raise InvalidWallpaper("缓存标识无效")
    if (
        not isinstance(jpeg_base64, str)
        or len(jpeg_base64) > (MAX_CACHE_BYTES + 2) // 3 * 4
    ):
        raise InvalidWallpaper("壁纸缓存过大")
    try:
        data = base64.b64decode(jpeg_base64, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise InvalidWallpaper("缓存编码无效") from exc
    if (
        len(data) > MAX_CACHE_BYTES
        or not data.startswith(b"\xff\xd8")
        or not data.endswith(b"\xff\xd9")
    ):
        raise InvalidWallpaper("缓存必须是 JPEG 图像")
    current = wallpaper_view(script_name)
    assert "token" in current and "mode" in current
    if current["token"] != token:
        return False
    prefix = "video_" if current["mode"] == "video" else "rust_image_"
    directory = os.path.join(
        os.path.dirname(get_wallpaper_json_path_under_root()), "wallpaper_cache"
    )
    path = os.path.join(directory, f"{prefix}{token}.jpg")
    os.makedirs(directory, exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "wb") as stream:
        stream.write(data)
    os.replace(temporary, path)
    return True
