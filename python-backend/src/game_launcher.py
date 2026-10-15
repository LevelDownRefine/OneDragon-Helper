"""在独立 CLI 进程复用已安装脚本的游戏启动流程。"""

# 显式导入以供冻结收集；ok-ef 的动态模块使用 Windows ctypes 类型。
import ctypes.wintypes  # noqa: F401
import importlib.util
import logging
import os
import sys

from src.config.set_config import get_game_launch_info
from src.utils.utils_config import get_script
from src.utils.utils_sub_config import resolve_script_path

logger = logging.getLogger(__name__)


def launch_game(script_name: str) -> None:
    """读取现有游戏路径，调用脚本负责签名校验和父进程关系的启动模块。"""
    if sys.platform != "win32":
        raise OSError("专用游戏启动流程仅支持 Windows")
    script = get_script(script_name)
    if script is None:
        raise ValueError("脚本已不存在")
    info = get_game_launch_info(script_name)
    if info is None:
        raise ValueError("该脚本未提供专用游戏启动流程")
    module_path, game_path = info
    if not os.path.isfile(module_path):
        raise FileNotFoundError("未找到游戏启动模块，请更新对应脚本")
    if not game_path or not os.path.isfile(resolve_script_path(game_path)):
        raise FileNotFoundError("未找到游戏程序，请配置游戏路径")
    arguments = script["game_arguments"] if "game_arguments" in script else ""  # noqa: SIM401
    if not isinstance(arguments, str):
        raise ValueError("游戏启动参数无效")
    # 兼容此前填写的启动器参数；启动模块会自行传给启动器，不能再传给游戏。
    if arguments.strip() == "--game=Endfield --reason=4":
        arguments = ""
    spec = importlib.util.spec_from_file_location("_odh_game_launcher", module_path)
    if spec is None or spec.loader is None:
        raise ImportError("无法加载游戏启动模块")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, "launch_game", None)):
        raise ImportError("游戏启动模块缺少 launch_game，请更新对应脚本")
    if (
        module.launch_game(
            os.path.abspath(resolve_script_path(game_path)), arguments, logger
        )
        is not True
    ):
        raise RuntimeError("游戏启动模块未确认启动成功，详见日志")
