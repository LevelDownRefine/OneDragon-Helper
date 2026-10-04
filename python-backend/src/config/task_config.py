"""日常、周常声明的读取与查询入口；结构解析统一委托 task_parser。"""

from pathlib import Path

from src.config.task_parser import parse_task_map
from src.utils import (
    get_daily_task_list_yml_path_under_root,
    get_weekly_task_list_yml_path_under_root,
)
from src.utils.utils_io import load_data


def load_task_map(path: str, *, require_class: bool = False) -> dict[str, list[dict]]:
    """读取层按内容缓存解码结果；本层校验任务声明。

    Args:
        path: 声明文件路径。
        require_class: True 时每个任务必须声明 ``class``（机制类）与 ``config``
            （读写的主文件路径）——日常、周常声明均使用。

    Returns:
        {脚本标识: 任务声明列表}。

    Raises:
        AssertionError: require_class 且某任务未声明 ``class``。
    """
    file = Path(path)
    assert file.is_file(), f"任务声明缺失: {path}"
    return parse_task_map(load_data(path, "yaml", cached=True), require_class)


def load_daily_map() -> dict[str, list[dict]]:
    """取得日常声明（每个日常必须标注机制类 ``class``）。"""
    return load_task_map(get_daily_task_list_yml_path_under_root(), require_class=True)


def load_weekly_map() -> dict[str, list[dict]]:
    """取得周常声明（每条周常必须标注机制类 ``class``；周几起由 weekly.yml 维护）。"""
    return load_task_map(get_weekly_task_list_yml_path_under_root(), require_class=True)


def get_daily_configs(script_name: str) -> list[dict]:
    """取得某脚本的全部日常声明（顺序与声明一致）。

    Args:
        script_name: 脚本标识名。

    Returns:
        该脚本的日常声明列表；单日常脚本长度为 1。

    Raises:
        AssertionError: 缺少脚本声明。
    """
    data = load_daily_map()
    assert script_name in data, f"缺少日常声明: {script_name}"
    return data[script_name]


def get_weekly_config(script_name: str, weekly_name: str) -> dict:
    """按展示名取得指定周常声明。"""
    data = load_weekly_map()
    assert script_name in data, f"缺少周常声明: {script_name}"
    matches = [
        task for task in data[script_name] if task["display_name"] == weekly_name
    ]
    assert len(matches) == 1, f"缺少周常声明: {script_name}/{weekly_name}"
    return matches[0]
