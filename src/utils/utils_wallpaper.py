"""自定义壁纸表（config/wallpaper.json）读写（无 Qt 依赖）。

持久化「脚本唯一标识 → 自定义壁纸路径」映射。壁纸缓存图（wallpaper_cache/）
的生成属 GUI 渲染关注点（Qt 依赖），由 src.gui.controllers.background 负责，
不在本模块。
"""

import json
import logging
import os

from src.utils import get_wallpaper_json_path_under_root

logger = logging.getLogger(__name__)


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
