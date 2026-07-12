"""
副本配置适配器（外观模式）
对外提供统一的 set_config 接口，内部封装各自动化脚本的 config 读写逻辑。

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
    "鸣潮":   "data/apps/ok-ww/working/configs/DailyTask.json",
    "原神":   "User/OneDragon/默认配置.json",
    "终末地": "data/apps/ok-ef/working/configs/DailyTask.json",
    "绝区零": "config/01/one_dragon/charge_plan.yml",
    "崩铁":   "config.yaml",
    "异环":   "data/apps/ok-nte/working/configs/DailyTask.json",
    "粥":     "config/gui.new.json",
}


def _load_config_yml() -> dict:
    """读取 config.yml"""
    with open(get_config_yml_path_under_root(), 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def _get_script_root_dir(script_display_name: str) -> Optional[str]:
    """
    从 config.yml 中找到指定脚本的 script_path，
    取其父目录作为脚本项目根目录。

    script_path 可能是 Windows 风格路径（C:\\...\\xxx.exe），
    统一将反斜杠转为正斜杠后再取 dirname，确保跨平台可用。
    """
    config_data = _load_config_yml()
    for script in config_data.get('script_list', []):
        if script.get('display_name') == script_display_name:
            script_path = script.get('script_path', '')
            if script_path:
                # 统一路径分隔符，兼容 Windows 路径在 Linux 上解析
                normalized = script_path.replace('\\', '/')
                root = os.path.dirname(normalized)
                return root if root else None
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

def set_config(script_display_name: str,
               dungeon_name: str | None = None,
               sequence: int = 0) -> bool:
    """
    外观接口：为指定脚本设置副本和刷取序列

    流程：load_config → handler 修改 → save_config
    handler 只负责修改 config dict 并返回，不关心读写细节。

    sequence 默认 0 表示无序列，由各 handler 自行判断是否处理。
    是否需要序列由 dungeon_list.yml 中副本项有无二级目录决定。

    Args:
        script_display_name: 脚本显示名称（与 config.yml 中一致）
        dungeon_name: 副本名称（来自 dungeon_list.yml），None 或 "未选择" 时跳过
        sequence: 刷取序列编号，0 表示无序列

    Returns:
        是否设置成功
    """
    handlers = {
        "鸣潮":   _apply_wuthering_waves,
        "原神":   _apply_genshin,
        "终末地": _apply_endfield,
        "绝区零": _apply_zenless,
        "崩铁":   _apply_star_rail,
        "异环":   _apply_nte,
        "粥":     _apply_arknights,
    }

    if not dungeon_name or dungeon_name == "未选择":
        return True

    handler = handlers.get(script_display_name)
    if handler is None:
        print(f"[dungeon_adapter] 未适配的脚本: {script_display_name}")
        return False

    # 统一 load
    config = load_config(script_display_name)
    if config is None:
        print(f"[dungeon_adapter] {script_display_name} config 读取失败，无法写入")
        return False

    # handler 修改 config，返回修改后的 dict
    try:
        updated = handler(config, dungeon_name, sequence)
        breakpoint()
    except Exception as e:
        print(f"[dungeon_adapter] {script_display_name} 适配配置失败: {e}")
        return False

    if updated is None:
        # handler 返回 None 表示无需写入（例如数据无变化）
        return True

    # 统一 save
    try:
        if not save_config(script_display_name, updated):
            print(f"[dungeon_adapter] {script_display_name} config 写入失败")
            return False
    except Exception as e:
        print(f"[dungeon_adapter] {script_display_name} config 写入异常: {e}")
        return False

    return True


# ============================================================
# 各脚本具体实现（待适配）
# 每个 handler 接收 (config, dungeon_name, sequence)，
# 修改 config dict 并返回；返回 None 表示无需写入。
# ============================================================

# ---- 鸣潮 Wuthering Waves ----
def _apply_wuthering_waves(config: dict, dungeon_name: str, sequence=None) -> dict | None:

    def update_task() -> bool:
        """更新副本类型，返回是否有变化"""
        dungeon_map = {
            "凝素领域": "Forgery Challenge",
            "模拟领域": "Simulation Challenge",
            "无音区": "Tacet Suppression",
        }
        task = dungeon_map.get(dungeon_name)
        if task is None:
            print(f"[dungeon_adapter][Wuthering Waves] 未适配的副本: {dungeon_name}")
            return False
        if config['Which to Farm'] == task:
            return False
        config['Which to Farm'] = task
        return True

    def update_sequence() -> bool:
        """更新序列，返回是否有变化"""
        if sequence is None:
            return False
        if config['Which to Farm'] == "Simulation Challenge":
            material_map = {1: "Resonator EXP", 2: "Weapon EXP", 3: "Shell Credit"}
            if config['Material Selection'] == material_map[sequence]:
                return False
            config['Material Selection'] = material_map[sequence]
        elif config['Which to Farm'] == "Tacet Suppression":
            if int(config['Which Tacet Suppression to Farm']) == sequence:
                return False
            config['Which Tacet Suppression to Farm'] = sequence
        elif config['Which to Farm'] == "Forgery Challenge":
            if int(config['Which Forgery Challenge to Farm']) == sequence:
                return False
            config['Which Forgery Challenge to Farm'] = sequence
        return True

    changed = update_task() or update_sequence()
    if not changed:
        print(f"[dungeon_adapter][Wuthering Waves] config 无需更新: {config}")
        return None
    
    print(f"[dungeon_adapter][Wuthering Waves] config 已更新: {config}")
    return config

# ---- 原神 Genshin Impact ----
def _apply_genshin(config: dict, dungeon_name: str, sequence: int = 0) -> dict | None:
    # TODO: 适配 BetterGI 的副本配置
    print(f"[dungeon_adapter][Genshin] 待适配: {dungeon_name}")
    return None


# ---- 终末地 Arknights: Endfield ----
def _apply_endfield(config: dict, dungeon_name: str, sequence: int = 0) -> dict | None:
    # TODO: 适配终末地的副本配置（sequence > 0 时同时写入序列）
    print(f"[dungeon_adapter][Endfield] 待适配: {dungeon_name}, seq={sequence}")
    return None


# ---- 绝区零 Zenless Zone Zero ----
def _apply_zenless(config: dict, dungeon_name: str, sequence: int = 0) -> dict | None:
    # TODO: 适配绝区零的副本配置
    print(f"[dungeon_adapter][Zenless] 待适配: {dungeon_name}")
    return None


# ---- 崩铁 Honkai: Star Rail ----
def _apply_star_rail(config: dict, dungeon_name: str, sequence: int = 0) -> dict | None:
    # TODO: 适配崩铁的副本配置
    print(f"[dungeon_adapter][Star Rail] 待适配: {dungeon_name}")
    return None


# ---- 异环 Neverness to Everness (NTE) ----
def _apply_nte(config: dict, dungeon_name: str, sequence: int = 0) -> dict | None:
    # TODO: 适配异环的副本配置（sequence > 0 时同时写入序列）
    print(f"[dungeon_adapter][NTE] 待适配: {dungeon_name}, seq={sequence}")
    return None


# ---- 明日方舟 Arknights（粥）----
def _apply_arknights(config: dict, dungeon_name: str, sequence: int = 0) -> dict | None:
    # TODO: 适配 MAA 的副本配置
    print(f"[dungeon_adapter][Arknights] 待适配: {dungeon_name}")
    return None
