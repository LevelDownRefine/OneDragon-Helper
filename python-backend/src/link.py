"""游戏 / 脚本关联目标查询：链接、目录、图标和启动命令；不执行打开或启动。"""

import os

from src.config.script_resources import get_script_resources
from src.config.set_config import get_game_exe_path
from src.log import get_log_dir
from src.utils.utils_config import config_file_path, get_script
from src.utils.utils_runner import build_script_command
from src.utils.utils_sub_config import resolve_script_path

_LINKS = {
    "home": ("homepage", "https://github.com/LevelDownRefine/OneDragon-Helper"),
    "bili": ("bilibili", "https://www.bilibili.com/"),
    "github": ("github", "https://github.com/LevelDownRefine/OneDragon-Helper"),
}


def get_game_link(script_name: str, kind: str) -> str:
    """读取官网 / B 站 / GitHub 链接；未声明脚本返回空字符串。"""
    resources = get_script_resources(script_name)
    if resources is None:
        return ""
    assert "links" in resources
    links = resources["links"]
    assert kind in links, f"未知链接种类: {kind}"
    return links[kind]


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
        if not script["script_path"]:
            return _unavailable("未找到脚本路径")
        resolved = resolve_script_path(script["script_path"])
        if target == "folder":
            path = os.path.dirname(resolved)
        else:
            path = get_log_dir(script)
            if path is None:
                return _unavailable("暂不支持日志跳转")
        if not os.path.isdir(path):
            return _unavailable(
                "脚本目录不存在" if target == "folder" else "日志目录不存在"
            )
    return {"kind": "path", "value": os.path.abspath(path)}


def resolve_launch_target(script_name: str, target: str) -> dict:
    """只解析启动信息；前端显式点击后启动，不启动调度链。"""
    if target not in ("script", "game"):
        raise ValueError("不支持的启动入口")
    script = get_script(script_name)
    if script is None:
        return {"kind": "unavailable", "reason": "脚本已不存在，请刷新列表"}
    assert "script_path" in script
    path = get_game_exe_path(script_name) if target == "game" else script["script_path"]
    if not path:
        return {
            "kind": "unavailable",
            "reason": "未找到游戏路径" if target == "game" else "未找到脚本路径",
        }
    resolved = resolve_script_path(path)
    if not resolved or not os.path.isfile(resolved):
        return {"kind": "unavailable", "reason": "启动文件不存在，请检查配置"}
    script_type = script["script_type"] if "script_type" in script else "external"  # noqa: SIM401
    if target == "game" or script_type != "python":
        result = {"kind": "association", "path": os.path.abspath(resolved)}
        if target == "game" and "game_arguments" in script:
            arguments = script["game_arguments"]
            if not isinstance(arguments, str):
                return _unavailable("游戏启动参数无效")
            if arguments:
                result["arguments"] = arguments
        return result
    command, cwd, environment = build_script_command(["--script", resolved])
    # 不经传输携带整个父进程环境，仅给出运行器增加/修改的项。
    overrides = {}
    if environment is not None:
        for key, value in environment.items():
            if key not in os.environ or os.environ[key] != value:
                overrides[key] = value
    return {
        "kind": "command",
        "program": command[0],
        "args": command[1:],
        "cwd": cwd,
        "env": overrides,
    }
