"""
副本配置适配器（外观模式）
对外提供统一的 set_dungeon / set_sequence 接口，内部封装各自动化脚本的 config 读写逻辑。

每个脚本的 config 格式、路径、字段名都不同，
在各自的 _apply_xxx 函数中单独适配，上层无需关心差异。

config 路径推导：
  1. 从 config.yml 中取得各脚本的 script_path（exe 路径），取其父目录作为脚本根目录
  2. dungeon_list.yml 中注释标注了各 config 相对于脚本根目录的路径
  3. 拼接根目录 + 相对路径 = config 文件绝对路径
"""
import os
import json
import yaml
from typing import Optional, Any

from utils import get_config_yml_path_under_root


# ============================================================
# 脚本根目录 & config 路径解析
# ============================================================

# 各脚本 config 文件相对于各自项目根目录的路径
# （与 dungeon_list.yml 中注释一致）
_CONFIG_REL_PATHS: dict[str, str] = {
    "鸣潮":   r"data\apps\ok-ww\working\configs\DailyTask.json",
    "原神":   r"User\OneDragon\默认配置.json",
    "终末地": r"data\apps\ok-ef\working\configs\DailyTask.json",
    "绝区零": r"config\01\one_dragon\charge_plan.yml",
    "崩铁":   r"config.yaml",
    "异环":   r"data\apps\ok-nte\working\configs\DailyTask.json",
    "粥":     r"config\gui.new.json",
}


def _load_config_yml() -> dict:
    """读取 config.yml"""
    with open(get_config_yml_path_under_root(), 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def _get_script_root_dir(script_display_name: str) -> Optional[str]:
    """
    从 config.yml 中找到指定脚本的 script_path，
    取其父目录作为脚本项目根目录。
    """
    config_data = _load_config_yml()
    for script in config_data.get('script_list', []):
        if script.get('display_name') == script_display_name:
            script_path = script.get('script_path', '')
            if script_path:
                return os.path.dirname(script_path)
    return None


def get_config_path(script_display_name: str) -> Optional[str]:
    """
    获取指定脚本的 config 文件绝对路径。
    拼接脚本根目录 + config 相对路径。
    """
    root = _get_script_root_dir(script_display_name)
    rel = _CONFIG_REL_PATHS.get(script_display_name)
    if not root or not rel:
        return None
    return os.path.join(root, rel)


# ============================================================
# config 读写工具函数
# ============================================================

def load_config(script_display_name: str) -> Optional[Any]:
    """
    读取指定脚本的 config 文件，返回解析后的 dict/list。
    支持 .json 和 .yaml/.yml 格式。
    """
    path = get_config_path(script_display_name)
    if not path or not os.path.exists(path):
        print(f"[dungeon_adapter] config 文件不存在: {script_display_name} -> {path}")
        return None

    ext = os.path.splitext(path)[1].lower()
    with open(path, 'r', encoding='utf-8') as f:
        if ext == '.json':
            return json.load(f)
        elif ext in ('.yaml', '.yml'):
            return yaml.safe_load(f)
        else:
            print(f"[dungeon_adapter] 不支持的 config 格式: {ext}")
            return None


def save_config(script_display_name: str, data: Any) -> bool:
    """
    将数据写回指定脚本的 config 文件。
    保持原始格式（json / yaml）。
    """
    path = get_config_path(script_display_name)
    if not path:
        print(f"[dungeon_adapter] 无法确定 config 路径: {script_display_name}")
        return False

    ext = os.path.splitext(path)[1].lower()
    with open(path, 'w', encoding='utf-8') as f:
        if ext == '.json':
            json.dump(data, f, ensure_ascii=False, indent=4)
        elif ext in ('.yaml', '.yml'):
            yaml.dump(data, f, allow_unicode=True, sort_keys=False)
        else:
            print(f"[dungeon_adapter] 不支持的 config 格式: {ext}")
            return False
    return True


# ============================================================
# 外观接口
# ============================================================

def set_dungeon(script_display_name: str, dungeon_name: str) -> bool:
    """
    外观接口：为指定脚本设置刷取副本

    Args:
        script_display_name: 脚本显示名称（与 config.yml 中一致）
        dungeon_name: 副本名称（来自 dungeon_list.yml）

    Returns:
        是否设置成功
    """
    if not dungeon_name or dungeon_name == "未选择":
        return True  # 不需要修改

    handlers = {
        "鸣潮": _apply_wuthering_waves_dungeon,
        "原神": _apply_genshin_dungeon,
        "终末地": _apply_endfield_dungeon,
        "绝区零": _apply_zenless_dungeon,
        "崩铁": _apply_star_rail_dungeon,
        "异环": _apply_nte_dungeon,
        "粥": _apply_arknights_dungeon,
    }

    handler = handlers.get(script_display_name)
    if handler is None:
        print(f"[dungeon_adapter] 未适配的脚本: {script_display_name}")
        return False

    try:
        return handler(dungeon_name)
    except Exception as e:
        print(f"[dungeon_adapter] {script_display_name} 写入副本配置失败: {e}")
        return False


def set_sequence(script_display_name: str, sequence: int) -> bool:
    """
    外观接口：为指定脚本设置刷取序列

    是否需要序列由 dungeon_list.yml 中副本项有无二级目录决定，
    而非硬编码按是否 ok 系列判断。此处对所有有 handler 的脚本统一调用。

    Args:
        script_display_name: 脚本显示名称
        sequence: 刷取序列编号（正整数）

    Returns:
        是否设置成功
    """
    if sequence is None:
        return True

    handlers = {
        "鸣潮": _apply_wuthering_waves_sequence,
        "终末地": _apply_endfield_sequence,
        "异环": _apply_nte_sequence,
    }

    handler = handlers.get(script_display_name)
    if handler is None:
        return True  # 该脚本无序列适配，忽略

    try:
        return handler(sequence)
    except Exception as e:
        print(f"[dungeon_adapter] {script_display_name} 写入序列配置失败: {e}")
        return False


# ============================================================
# 各脚本具体实现（待适配）
# ============================================================

# ---- 鸣潮 Wuthering Waves ----
def _apply_wuthering_waves_dungeon(dungeon_name: str) -> bool:
    # TODO: 适配鸣潮的副本配置
    print(f"[dungeon_adapter][Wuthering Waves][dungeon] 待适配: {dungeon_name}")
    return True

def _apply_wuthering_waves_sequence(sequence: int) -> bool:
    # TODO: 适配鸣潮的刷取序列配置
    print(f"[dungeon_adapter][Wuthering Waves][sequence] 待适配: {sequence}")
    return True


# ---- 原神 Genshin Impact ----
def _apply_genshin_dungeon(dungeon_name: str) -> bool:
    # TODO: 适配 BetterGI 的副本配置
    print(f"[dungeon_adapter][Genshin][dungeon] 待适配: {dungeon_name}")
    return True


# ---- 终末地 Arknights: Endfield ----
def _apply_endfield_dungeon(dungeon_name: str) -> bool:
    # TODO: 适配终末地的副本配置
    print(f"[dungeon_adapter][Endfield][dungeon] 待适配: {dungeon_name}")
    return True

def _apply_endfield_sequence(sequence: int) -> bool:
    # TODO: 适配终末地的刷取序列配置
    print(f"[dungeon_adapter][Endfield][sequence] 待适配: {sequence}")
    return True


# ---- 绝区零 Zenless Zone Zero ----
def _apply_zenless_dungeon(dungeon_name: str) -> bool:
    # TODO: 适配绝区零的副本配置
    print(f"[dungeon_adapter][Zenless][dungeon] 待适配: {dungeon_name}")
    return True


# ---- 崩铁 Honkai: Star Rail ----
def _apply_star_rail_dungeon(dungeon_name: str) -> bool:
    # TODO: 适配崩铁的副本配置
    print(f"[dungeon_adapter][Star Rail][dungeon] 待适配: {dungeon_name}")
    return True


# ---- 异环 Neverness to Everness (NTE) ----
def _apply_nte_dungeon(dungeon_name: str) -> bool:
    # TODO: 适配异环的副本配置
    print(f"[dungeon_adapter][NTE][dungeon] 待适配: {dungeon_name}")
    return True

def _apply_nte_sequence(sequence: int) -> bool:
    # TODO: 适配异环的刷取序列配置
    print(f"[dungeon_adapter][NTE][sequence] 待适配: {sequence}")
    return True


# ---- 明日方舟 Arknights（粥）----
def _apply_arknights_dungeon(dungeon_name: str) -> bool:
    # TODO: 适配 MAA 的副本配置
    print(f"[dungeon_adapter][Arknights][dungeon] 待适配: {dungeon_name}")
    return True
