"""当前脚本/游戏的启动目标；命令沿用既有运行器入口。"""

import os

from src.config.set_config import get_game_exe_path
from src.utils.utils_config import get_script
from src.utils.utils_runner import build_script_command
from src.utils.utils_sub_config import resolve_script_path


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
        return {"kind": "association", "path": os.path.abspath(resolved)}
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
