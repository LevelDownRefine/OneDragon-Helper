"""
副本配置适配器（外观模式）
对外提供统一的 set_config 接口，内部封装各自动化脚本的 config 读写逻辑。

每个脚本的 config 格式、路径、字段名都不同，
在各自的 _apply_xxx 函数中单独适配，上层无需关心差异。

config 路径推导由 subscript_utils 统一处理：
  1. 从 config.yml 中取得各脚本的 script_path（exe 路径），取其父目录作为脚本根目录
  2. _CONFIG_REL_PATHS 标注了各 config 相对于脚本根目录的路径
  3. 拼接根目录 + 相对路径 = config 文件绝对路径
"""

from src.subscript_utils import load_config, save_config


# ============================================================
# 外观接口
# ============================================================

def set_config(script_display_name: str,
               dungeon_name: str | None = None,
               sequence: str | None = None) -> bool:
    """
    外观接口：为指定脚本设置副本和刷取序列

    流程：load_config → handler 修改 → save_config
    handler 只负责修改 config dict 并返回，不关心读写细节。

    sequence 为 str 类型，None 表示无序列。
    是否需要序列由 dungeon_list.yml 中副本项有无二级目录决定。

    Args:
        script_display_name: 脚本显示名称（与 config.yml 中一致）
        dungeon_name: 副本名称（来自 dungeon_list.yml），None 或 "未选择" 时跳过
        sequence: 刷取序列（字符串），None 表示无序列

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

    # handler 修改 config，返回修改后的 dict
    updated = handler(config, dungeon_name, sequence)

    if updated is None:
        # handler 返回 None 表示无需写入（例如数据无变化）
        return True

    # 统一 save
    save_config(script_display_name, updated)
    return True


# ============================================================
# 各脚本具体实现（待适配）
# 每个 handler 接收 (config, dungeon_name, sequence)，
# 修改 config dict 并返回；返回 None 表示无需写入。
# ============================================================

# ---- 鸣潮 Wuthering Waves ----
def _apply_wuthering_waves(config: dict, dungeon_name: str, sequence: str | None = None) -> dict | None:

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
            material_map = {
                "共鸣者经验": "Resonator EXP",
                "武器经验": "Weapon EXP",
                "贝币": "Shell Credit",
            }
            target = material_map.get(sequence)
            if target is None:
                print(f"[dungeon_adapter][Wuthering Waves] 未适配的序列: {sequence}")
                return False
            if config['Material Selection'] == target:
                return False
            config['Material Selection'] = target
        elif config['Which to Farm'] == "Tacet Suppression":
            if str(config['Which Tacet Suppression to Farm']) == sequence:
                return False
            config['Which Tacet Suppression to Farm'] = str(sequence)
        elif config['Which to Farm'] == "Forgery Challenge":
            if str(config['Which Forgery Challenge to Farm']) == sequence:
                return False
            config['Which Forgery Challenge to Farm'] = str(sequence)
        else:
            print(f"[dungeon_adapter][Wuthering Waves] 未适配的副本: {dungeon_name}")
            return False
        return True

    changed = update_task() or update_sequence()
    if not changed:
        print(f"[dungeon_adapter][Wuthering Waves] config 无需更新: {config}")
        return None

    print(f"[dungeon_adapter][Wuthering Waves] config 已更新: {config}")
    return config


# ---- 原神 Genshin Impact ----
def _apply_genshin(config: dict, dungeon_name: str, sequence: str | None = None) -> dict | None:

    def update_task() -> bool:
        """更新副本类型，返回是否有变化"""
        key = 'DomainName'
        if config[key] == dungeon_name:
            return False
        config[key] = dungeon_name
        return True
    
    if not update_task():
        print(f"[dungeon_adapter][Genshin] config 无需更新: {config}")
        return None

    print(f"[dungeon_adapter][Genshin] config 已更新: {config}")
    return config


# ---- 终末地 Arknights: Endfield ----
def _apply_endfield(config: dict, dungeon_name: str, sequence: str | None = None) -> dict | None:

    def update_task() -> bool:
        """更新副本类型，返回是否有变化"""
        key = "体力本"
        if config[key] == dungeon_name:
            return False
        config[key] = dungeon_name
        return True

    if not update_task():
        print(f"[dungeon_adapter][Endfield] config 无需更新: {config}")
        return None

    print(f"[dungeon_adapter][Endfield] config 已更新: {config}")
    return config


# ---- 绝区零 Zenless Zone Zero ----
def _apply_zenless(config: dict, dungeon_name: str, sequence: str | None = None) -> dict | None:
    # TODO: 适配绝区零的副本配置
    print(f"[dungeon_adapter][Zenless] 待适配: {dungeon_name}")
    return None


# ---- 崩铁 Honkai: Star Rail ----
def _apply_star_rail(config: dict, dungeon_name: str, sequence: str | None = None) -> dict | None:

    def update_task() -> bool:
        """更新副本类型，返回是否有变化"""
        key = "instance_type"
        if config[key] == dungeon_name:
            return False
        config[key] = dungeon_name
        return True

    if not update_task():
        print(f"[dungeon_adapter][Star Rail] config 无需更新")
        return None

    print(f"[dungeon_adapter][Star Rail] config 已更新")
    return config


# ---- 异环 Neverness to Everness (NTE) ----
def _apply_nte(config: dict, dungeon_name: str, sequence: str | None = None) -> dict | None:

    def update_task() -> bool:
        """更新副本类型，返回是否有变化"""
        key = "任务类型"
        if config[key] == dungeon_name:
            return False
        config[key] = dungeon_name
        return True

    def update_sequence() -> bool:
        """更新序列，返回是否有变化"""
        if sequence is None:
            return False
        if dungeon_name == "异能升级材料":
            if str(config['异能材料序号']) == sequence:
                return False
            config['异能材料序号'] = str(sequence)
        elif dungeon_name == "空幕":
            if str(config['空幕序号']) == sequence:
                return False
            config['空幕序号'] = str(sequence)
        elif dungeon_name == "弧盘突破材料":
            if str(config['弧盘材料序号']) == sequence:
                return False
            config['弧盘材料序号'] = str(sequence)
        else:
            print(f"[dungeon_adapter][NTE] 未适配的副本: {dungeon_name}")
            return False
        return True

    changed = update_task() or update_sequence()
    if not changed:
        print(f"[dungeon_adapter][NTE] config 无需更新: {config}")
        return None

    print(f"[dungeon_adapter][NTE] config 已更新: {config}")
    return config


# ---- 明日方舟 Arknights（粥）----
def _apply_arknights(config: dict, dungeon_name: str, sequence: str | None = None) -> dict | None:

    def update_task() -> bool:
        """更新副本类型，返回是否有变化"""
        task_map = {
            "红票": 2,
            "经验": 3,
            "龙门币": 4,
            "土": 5,
        }
        task_config = config["Configurations"]["Default"]["TaskQueue"]
        if dungeon_name not in task_map:
            print(f"[dungeon_adapter][Arknights] 未适配的副本: {dungeon_name}")
            return False

        # disable other tasks
        for key in task_map:
            task_config[task_map[key]]["IsEnable"] = False
        
        task_config[task_map[dungeon_name]]["IsEnable"] = True
        task_config[task_map["土"]]["IsEnable"] = True
        print(f"enable task: {dungeon_name}")

        # always update task config for stability
        return True

    if not update_task():
        print(f"[dungeon_adapter][Arknights] config 无需更新")
        return None

    print(f"[dungeon_adapter][Arknights] config 已更新")
    return config
