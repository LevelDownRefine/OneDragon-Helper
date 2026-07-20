"""
脚本配置读写模块
提供脚本根目录解析、config 路径推导、配置文件读写等功能。
"""

import os
import json
import yaml
from typing import Any

from src.utils import get_config_yml_path_under_root


# ============================================================
# 各脚本 config 相对路径映射
# ============================================================

_CONFIG_REL_PATHS: dict[str, str] = {
    "鸣潮":   "data/apps/ok-ww/working/configs/DailyTask.json",
    "原神":   "User/OneDragon/默认配置.json",
    "终末地": "data/apps/ok-ef/working/configs/DailyTask.json",
    "绝区零": "config/01/one_dragon/charge_plan.yml",
    "崩铁":   "config.yaml",
    "异环":   "data/apps/ok-nte/working/configs/DailyTask.json",
    "粥":     "config/gui.new.json",
}


# ============================================================
# 模板文件路径映射
# ============================================================

_TEMPLATE_PATHS: dict[str, str] = {
    "原神":   "BGI一条龙.json",
    "绝区零": "ZZZ一条龙.yml",
    "粥":     "MAA一条龙.json",
    "崩铁":   "M7A一条龙.yml",
}


# ============================================================
# 主配置加载
# ============================================================

def _load_config_yml() -> dict:
    """读取主配置 config.yml"""
    with open(get_config_yml_path_under_root(), 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


# ============================================================
# 脚本根目录 & config 路径解析
# ============================================================

def _get_script_root_dir(script_display_name: str) -> str:
    """
    从 config.yml 中找到指定脚本的 script_path，
    取其父目录作为脚本项目根目录。

    script_path 可能是 Windows 风格路径（C:\\...\\xxx.exe），
    统一将反斜杠转为正斜杠后再取 dirname，确保跨平台可用。
    并确保 exe 脚本存在。
    """
    config_data = _load_config_yml()
    for script in config_data.get('script_list', []):
        if script.get('display_name') == script_display_name:
            script_path = script.get('script_path', '')
            assert script_path, f"[set_config] config.yml 中 {script_display_name} 的 script_path 为空"
            normalized = script_path.replace('\\', '/')
            assert os.path.exists(normalized), f"[set_config] exe 不存在: {normalized}"
            return os.path.dirname(normalized)
    assert False, f"[set_config] config.yml 中找不到脚本: {script_display_name}"


def get_config_path(script_display_name: str) -> str:
    """
    获取指定脚本的 config 文件绝对路径。
    拼接脚本根目录 + config 相对路径。
    并确保 config 文件存在。
    """
    assert script_display_name in _CONFIG_REL_PATHS, \
        f"[set_config] 未适配脚本: {script_display_name}"
    root = _get_script_root_dir(script_display_name)
    rel = _CONFIG_REL_PATHS[script_display_name]
    config_path = os.path.join(root, rel)
    assert os.path.exists(config_path), f"[set_config] config 文件不存在: {config_path}"
    return config_path


# ============================================================
# config 读写
# ============================================================

def load_config(script_display_name: str) -> dict | list:
    """
    读取指定脚本的 config 文件，返回解析后的 dict 或 list。
    支持 .json 和 .yaml/.yml 格式。
    assert 文件存在。
    """
    path = get_config_path(script_display_name)
    assert os.path.exists(path), f"[set_config] config 文件不存在: {path}"
    ext = os.path.splitext(path)[1].lower()
    with open(path, 'r', encoding='utf-8') as f:
        if ext == '.json':
            return json.load(f)
        elif ext in ('.yaml', '.yml'):
            return yaml.safe_load(f)
        raise ValueError(f"[set_config] 不支持的 config 格式: {ext}")


def save_config(script_display_name: str, data: dict | list) -> None:
    """
    将数据写回指定脚本的 config 文件。
    保持原始格式（json / yaml）。
    并确保 config 文件已存在且能被写入。
    """
    path = get_config_path(script_display_name)
    ext = os.path.splitext(path)[1].lower()
    with open(path, 'w', encoding='utf-8') as f:
        if ext == '.json':
            json.dump(data, f, ensure_ascii=False, indent=4)
        elif ext in ('.yaml', '.yml'):
            yaml.dump(data, f, allow_unicode=True, sort_keys=False)
        else:
            raise ValueError(f"[set_config] 不支持的 config 格式: {ext}")
