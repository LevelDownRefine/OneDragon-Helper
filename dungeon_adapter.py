"""
副本配置适配器（外观模式）
对外提供统一的 set_dungeon 接口，内部封装各自动化脚本的 config 写入逻辑。

每个脚本的 config 格式、路径、字段名都不同，
在各自的 _apply_xxx 函数中单独适配，上层无需关心差异。
"""
import os
from typing import Optional


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
    外观接口：为指定脚本设置刷取序列（ok 系列脚本专用）

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
        return True  # 非 ok 脚本，忽略

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
