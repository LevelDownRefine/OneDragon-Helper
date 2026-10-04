"""日常和周常选项资源的读取入口；结构解析归 task_parser。"""

from src.config.task_parser import parse_source_names
from src.utils.utils_dict import get_field
from src.utils.utils_sub_config import load_game_config


def read_task_source(script_name: str, source: dict) -> list[str]:
    """读取 path 指向的资源，再解析键路径与候选名。"""
    path = get_field(source, "path", script_name, str)
    return parse_source_names(load_game_config(script_name, path), source, script_name)
