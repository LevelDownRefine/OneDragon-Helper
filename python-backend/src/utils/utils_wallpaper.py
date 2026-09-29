"""壁纸来源、自定义映射与预览缓存；解码和渲染由前端负责，无 Qt 依赖。"""

import base64
import binascii
import hashlib
import json
import logging
import os

from src.config.set_config import get_background_rel_path
from src.utils import get_wallpaper_json_path_under_root
from src.utils.utils_config import get_script
from src.utils.utils_sub_config import get_script_root_dir, resolve_script_path

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mkv", ".mov"}
MAX_CACHE_BYTES = 4 * 1024 * 1024


class InvalidWallpaper(ValueError):
    """外部文件或壁纸请求无效。"""


def load_wallpapers() -> dict:
    """读取壁纸表（{脚本标识: 壁纸路径}）。

    缺失返回空 dict；文件损坏（非合法 JSON / 读取失败）视为外部输入可恢复，
    记日志后按空处理——下次保存即覆盖重建，不让 GUI 启动崩在坏文件上。

    Returns:
        壁纸映射 dict。
    """
    path = get_wallpaper_json_path_under_root()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(
            "[wallpaper] 壁纸表读取失败(%s)，按未设置处理：%s %s",
            type(e).__name__,
            path,
            e,
        )
        return {}
    assert isinstance(data, dict), f"[wallpaper] 壁纸表必须是 dict: {path}"
    return data


def save_wallpapers(wallpapers: dict) -> None:
    """写回壁纸表。

    原子写（tmp + os.replace）：写入中断不会留下损坏 JSON——损坏兜底只是
    最后一道防线，不应靠它兜主动写入的锅。

    Args:
        wallpapers: 完整壁纸映射 dict（由调用方原地修改后传入）。
    """
    assert isinstance(wallpapers, dict), "[wallpaper] 待保存的壁纸表非 dict"
    path = get_wallpaper_json_path_under_root()
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(wallpapers, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def video_preview_path(source_path: str) -> str | None:
    """按视频路径、大小与修改时间定位首帧缓存；源文件不可读时跳过。"""
    try:
        stat = os.stat(source_path)
    except OSError as e:
        logger.warning("[wallpaper] 视频缓存源不可读(%s)：%s", type(e).__name__, e)
        return None
    identity = json.dumps(
        [os.path.normcase(os.path.abspath(source_path)), stat.st_size, stat.st_mtime_ns]
    )
    key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return os.path.join(
        os.path.dirname(get_wallpaper_json_path_under_root()),
        "wallpaper_cache",
        f"video_{key}.jpg",
    )


def save_video_preview(source_path: str, cache_path: str, data: bytes) -> bool:
    """原子保存 GUI 编码的首帧；视频在解码期间被替换则放弃缓存。"""
    if video_preview_path(source_path) != cache_path:
        logger.warning("[wallpaper] 视频源已变化，跳过首帧缓存：%s", source_path)
        return False
    try:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path + ".tmp", "wb") as f:
            f.write(data)
        os.replace(cache_path + ".tmp", cache_path)
    except OSError as e:
        logger.warning("[wallpaper] 视频缓存写入失败(%s)：%s", type(e).__name__, e)
        return False
    return True


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
    """只接受当前来源的有界 JPEG 缓存；路径由本模块生成，过期解码丢弃。"""
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
