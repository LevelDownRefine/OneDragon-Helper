"""供前端打开的脚本资源目标；只解析，不启动程序或读取配置内容。"""

import os

from src.config.set_config import get_game_exe_path
from src.link import get_game_link
from src.log import get_log_dir
from src.utils.utils_config import config_file_path, get_script
from src.utils.utils_sub_config import resolve_script_path

_LINKS = {
    "home": ("homepage", "https://github.com/LevelDownRefine/OneDragon-Helper"),
    "bili": ("bilibili", "https://www.bilibili.com/"),
    "github": ("github", "https://github.com/LevelDownRefine/OneDragon-Helper"),
}


def _unavailable(reason: str) -> dict:
    return {"kind": "unavailable", "reason": reason}


def game_icon_path(script_name: str) -> dict:
    """悬停时解析游戏路径，缺失返回空；不读图标、不启动程序。"""
    path = None
    if get_script(script_name) is not None:
        raw = get_game_exe_path(script_name)
        if raw:
            path = os.path.abspath(resolve_script_path(raw))
    return {"script_name": script_name, "path": path}


def resolve_script_target(script_name: str, target: str) -> dict:
    """复用资源声明与原路径解析，返回 URL、绝对路径或不可用原因。"""
    if target not in (*_LINKS, "folder", "log", "configfile"):
        raise ValueError(f"不支持的资源入口：{target}")
    script = get_script(script_name)
    if script is None:
        return _unavailable("尚无脚本或脚本已移除")
    if target in _LINKS:
        assert target in _LINKS
        kind, fallback = _LINKS[target]
        return {"kind": "url", "value": get_game_link(script_name, kind) or fallback}
    if target == "configfile":
        path, error = config_file_path(script_name)
        if error is not None:
            return _unavailable(error)
        assert path is not None
    else:
        assert "script_path" in script
        resolved = resolve_script_path(script["script_path"])
        if not resolved:
            return _unavailable("未找到脚本路径")
        if target == "folder":
            path = os.path.dirname(resolved)
        else:
            path = get_log_dir(script_name, resolved)
            if path is None:
                return _unavailable("暂不支持日志跳转")
        if not os.path.isdir(path):
            return _unavailable(
                "脚本目录不存在" if target == "folder" else "日志目录不存在"
            )
    return {"kind": "path", "value": os.path.abspath(path)}
