"""config.yml 的读写、条目查询与配置文件路径解析。

脚本条目的构造、增删改与排序归 src.service.script_service。
本模块只负责助手配置读写，不写 weekly.yml 或初始化子脚本配置。
"""

import logging
import os

from src.config.set_config import get_config_path
from src.utils import (
    get_config_yml_path_under_root,
    require_config_yml_path,
)
from src.utils.utils_game_command import game_command_of
from src.utils.utils_sub_config import (
    check_script_name_uniqueness,
    get_script_name,
    is_exe_script,
    resolve_script_path,
)
from src.utils.utils_yaml import dump_yaml, load_yaml

logger = logging.getLogger(__name__)


def load_config() -> dict:
    """读取 config.yml（断言存在），返回完整 script_list 配置。

    入口处一次性校验每个条目含 display_name/script_path 且脚本唯一标识唯一，
    script_list 内部数据此后可安全用直接访问。
    """
    config_path = require_config_yml_path()
    data = load_yaml(config_path)
    assert isinstance(data, dict) and "script_list" in data, (
        "[utils_config] config.yml 缺少 script_list 字段"
    )
    for s in data["script_list"]:
        assert "display_name" in s, (
            f"[utils_config] script_list 条目缺少 display_name: {s}"
        )
        assert "script_path" in s, (
            f"[utils_config] script_list 条目缺少 script_path: {s}"
        )
        if "game_path" in s or "game_arguments" in s:
            s["game_command"] = game_command_of(s)
            s.pop("game_path", None)
            s.pop("game_arguments", None)
        # 勾选是 GUI 内存态，不落盘；旧文件残留的 enabled 在此丢弃。
        if s.pop("enabled", None) is not None:
            logger.warning(
                "[config] %s 的 enabled 字段已废弃（勾选改为内存态），已忽略",
                get_script_name(s),
            )
    check_script_name_uniqueness(data)
    return data


def save_config(data: dict) -> None:
    """写回 config.yml（生成目标，不要求已存在）。

    Args:
        data: 完整 script_list 配置字典。
    """
    assert isinstance(data, dict) and "script_list" in data, (
        "[utils_config] 待保存的 config 缺少 script_list 字段"
    )
    config_path = get_config_yml_path_under_root()
    dump_yaml(config_path, data)


def get_script(script_name: str) -> dict | None:
    """按脚本唯一标识读取单个脚本条目。

    Args:
        script_name: 脚本唯一标识（exe 用进程名，脚本文件用 display_name）。

    Returns:
        脚本条目 dict；不存在时返回 None。
    """
    config = load_config()
    for script in config.get("script_list", []):
        if get_script_name(script) == script_name:
            return script
    return None


def config_file_path(script_name: str) -> tuple[str | None, str | None]:
    """返回该脚本「配置文件」的本地路径（用于外部打开）与失败原因。

    python 脚本返回其 .py 源文件路径；external 脚本返回其内部 config 路径。
    文件不存在或脚本未适配配置文件时返回 (None, error)，error 可直接展示给用户。

    Args:
        script_name: 脚本唯一标识。

    Returns:
        (path, error)：path 为可打开的配置文件路径（str）；error 为非空字符串时
            表示未适配或文件缺失（可直接展示），此时 path 为 None。
    """
    script = get_script(script_name)
    if script is None:
        return None, f"找不到脚本: {script_name}"
    script_type = script.get("script_type", "external")
    script_path = script.get("script_path", "")
    if script_type == "python":
        resolved = resolve_script_path(script_path)
        if not resolved or not os.path.isfile(resolved):
            return (
                None,
                f"找不到脚本文件：{script_path or '(未设置路径)'}",
            )
        return resolved, None
    if is_exe_script(script_path):
        try:
            config_path = get_config_path(get_script_name(script))
        except AssertionError as e:
            return None, f"该脚本暂未适配配置文件，无法打开：{e}"
        if not os.path.isfile(config_path):
            return None, f"配置文件不存在：{config_path}"
        return config_path, None
    # external 但非 exe（如 bat 等）：无 config 适配，打开其自身
    resolved = resolve_script_path(script_path)
    if not resolved or not os.path.isfile(resolved):
        return None, f"找不到脚本文件：{script_path or '(未设置路径)'}"
    return resolved, None
