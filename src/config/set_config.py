"""
副本配置适配器（外观模式）
对外提供统一的 set_config 接口，内部封装各自动化脚本的 config 读写逻辑。

每个脚本的 config 格式、路径、字段名都不同，
各脚本子类单独适配，上层无需关心差异。

config 路径推导由 subscript_utils 统一处理：
  1. 从 config.yml 中取得各脚本的 script_path（exe 路径），取其父目录作为脚本根目录
  2. _CONFIG_REL_PATHS 标注了各 config 相对于脚本根目录的路径
  3. 拼接根目录 + 相对路径 = config 文件绝对路径
"""

from src.subscript_utils import load_config, save_config


# ============================================================
# 基类
# ============================================================

class ScriptConfig:
    """单个自动化脚本的 config 操作基类"""

    display_name: str = ""
    _task_key: str = ""
    """config 中副本类型对应的字段名，设了即启用 _update_task"""
    _task_map: dict[str, str] = {}
    """副本中文名 → config 值的映射，空 dict 表示直接用 dungeon_name"""

    # ---- load / save ----

    def _load(self) -> dict:
        return load_config(self.display_name)

    def _save(self, config: dict):
        save_config(self.display_name, config)

    # ---- 子类按需覆盖的操作 ----

    def _update_task(self, config: dict, dungeon_name: str) -> bool:
        """
        更新副本类型字段。返回是否修改。
        子类设 _task_key 即启用，_task_map 为空时直接赋 dungeon_name。
        """
        assert self._task_key, f"[set_config][{self.display_name}] 子类必须设 _task_key"
        if self._task_map:
            assert dungeon_name in self._task_map, f"[set_config][{self.display_name}] 未适配的副本: {dungeon_name}"
            task = self._task_map[dungeon_name]
        else:
            task = dungeon_name
        assert self._task_key in config, f"[set_config][{self.display_name}] config 中缺少字段: {self._task_key}"
        if config[self._task_key] == task:
            return False
        config[self._task_key] = task
        return True

    def _update_sequence(self, config: dict, dungeon_name: str, sequence: str | None) -> bool:
        """更新序列字段。返回是否修改。默认不启用。"""
        return False

    def set_dungeon(self, dungeon_name: str, sequence: str | None = None):
        """
        设置副本。默认流程：_update_task → _update_sequence → save。
        子类直接覆盖 set_dungeon 则完全自定义（如粥）。
        """
        config = self._load()
        changed = self._update_task(config, dungeon_name) or \
                  self._update_sequence(config, dungeon_name, sequence)
        if changed:
            print(f"[set_config][{self.display_name}] config 已更新")
            self._save(config)
        else:
            print(f"[set_config][{self.display_name}] config 无需更新")


# ============================================================
# 各脚本子类
# ============================================================

# ---- 鸣潮 Wuthering Waves ----
class WutheringWavesConfig(ScriptConfig):

    def __init__(self):
        self.display_name = "鸣潮"
        self._task_key = "Which to Farm"
        self._task_map = {
            "凝素领域": "Forgery Challenge",
            "模拟领域": "Simulation Challenge",
            "无音区": "Tacet Suppression",
        }

    def _update_sequence(self, config: dict, dungeon_name: str, sequence: str | None) -> bool:
        if sequence is None:
            return False
        if config['Which to Farm'] == "Simulation Challenge":
            material_map = {
                "共鸣者经验": "Resonator EXP",
                "武器经验": "Weapon EXP",
                "贝币": "Shell Credit",
            }
            assert sequence in material_map, f"[set_config][{self.display_name}] 未适配的序列: {sequence}"
            target = material_map[sequence]
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
            assert False, f"[set_config][{self.display_name}] 未适配的副本: {dungeon_name}"
        return True


# ---- 原神 Genshin Impact ----
class GenshinConfig(ScriptConfig):

    def __init__(self):
        self.display_name = "原神"
        self._task_key = "DomainName"


# ---- 终末地 Arknights: Endfield ----
class EndfieldConfig(ScriptConfig):

    def __init__(self):
        self.display_name = "终末地"
        self._task_key = "体力本"


# ---- 绝区零 Zenless Zone Zero ----
class ZenlessZoneZeroConfig(ScriptConfig):

    def __init__(self):
        self.display_name = "绝区零"

    def set_dungeon(self, dungeon_name: str, sequence: str | None = None):
        print(f"[set_config][{self.display_name}] 暂未适配")


# ---- 崩铁 Honkai: Star Rail ----
class StarRailConfig(ScriptConfig):

    def __init__(self):
        self.display_name = "崩铁"
        self._task_key = "instance_type"


# ---- 异环 Neverness to Everness (NTE) ----
class NTEConfig(ScriptConfig):

    def __init__(self):
        self.display_name = "异环"
        self._task_key = "任务类型"

    def _update_sequence(self, config: dict, dungeon_name: str, sequence: str | None) -> bool:
        assert sequence is not None, f"[set_config][{self.display_name}] 序列不能为空"
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
            assert False, f"[set_config][{self.display_name}] 未适配的副本: {dungeon_name}"
        return True


# ---- 明日方舟 Arknights（粥）----
class ArknightsConfig(ScriptConfig):

    def __init__(self):
        self.display_name = "粥"

    def set_dungeon(self, dungeon_name: str, sequence: str | None = None):
        config = self._load()
        task_map = {
            "红票": 2,
            "经验": 3,
            "龙门币": 4,
            "土": 5,
        }
        task_config = config["Configurations"]["Default"]["TaskQueue"]
        assert dungeon_name in task_map, f"[set_config][{self.display_name}] 未适配的副本: {dungeon_name}"

        # disable other tasks
        for key in task_map:
            task_config[task_map[key]]["IsEnable"] = False

        task_config[task_map[dungeon_name]]["IsEnable"] = True
        task_config[task_map["土"]]["IsEnable"] = True

        print(f"[set_config][{self.display_name}] config 已更新")
        self._save(config)


# ============================================================
# 注册表
# ============================================================

_CONFIGS: dict[str, type[ScriptConfig]] = {
    "鸣潮": WutheringWavesConfig,
    "原神": GenshinConfig,
    "终末地": EndfieldConfig,
    "绝区零": ZenlessZoneZeroConfig,
    "崩铁": StarRailConfig,
    "异环": NTEConfig,
    "粥":   ArknightsConfig,
}


# ============================================================
# 外观接口
# ============================================================

def set_config(script_display_name: str,
               dungeon_name: str | None = None,
               sequence: str | None = None) -> None:
    """
    外观接口：为指定脚本设置副本和刷取序列

    Args:
        script_display_name: 脚本显示名称（与 config.yml 中一致）
        dungeon_name: 副本名称（来自 dungeon_list.yml），None 或 "未选择" 时跳过
        sequence: 刷取序列（字符串），None 表示无序列
    """
    # 未选择副本时，不做更改
    if not dungeon_name or dungeon_name == "未选择":
        return

    assert script_display_name in _CONFIGS, f"[set_config] 未适配的脚本: {script_display_name}"
    cfg_cls = _CONFIGS[script_display_name]

    cfg_cls().set_dungeon(dungeon_name, sequence)
