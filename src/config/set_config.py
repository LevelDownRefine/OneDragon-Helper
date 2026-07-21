"""
副本配置适配器（外观模式）
对外提供统一的 set_config 接口，内部封装各自动化脚本的 config 读写逻辑。

每个脚本的 config 格式、路径、字段名都不同，
各脚本子类单独适配，上层无需关心差异。
"""

import os
import json
import yaml
from typing import Any

from src.config.subscript import load_config, save_config, _TEMPLATE_PATHS
from src.utils import get_root_dir


def safe_update(config: dict, template: dict):
    """
    用 template 更新 config，更新前 assert 每个已存在 key 的 value 类型一致。
    config 中不存在的 key 直接添加，不检查类型。
    用 type() 严格比较，避免 bool/int 混淆（isinstance(True, int) 为 True）。
    """
    for key, val in template.items():
        if key in config:
            assert type(config[key]) is type(val), \
                f"[set_config] 类型不一致: key={key}, " \
                f"config={type(config[key]).__name__}, template={type(val).__name__}"
        config[key] = val


# ============================================================
# 基类
# ============================================================

class ScriptConfig:
    """单个自动化脚本的 config 操作基类"""

    display_name: str = ""
    _task_key: str = ""
    """config 中副本类型对应的字段名，设了即启用 _update_task"""
    _task_map: dict[str, Any] = {}
    """副本中文名 → config 值的映射，空 dict 表示直接用 dungeon_name"""

    def _load(self) -> dict:
        config = load_config(self.display_name)
        assert isinstance(config, dict), f"[set_config][{self.display_name}] config 必须是 dict"
        return config

    def _save(self, config: dict) -> None:
        assert isinstance(config, dict), f"[set_config][{self.display_name}] config 必须是 dict"
        save_config(self.display_name, config)

    def _load_template(self) -> dict:
        """
        加载模板文件，支持 JSON 和 YAML 格式。
        文件不存在或格式不支持时抛出 AssertionError。
        """
        assert self.display_name in _TEMPLATE_PATHS, \
            f"[set_config][{self.display_name}] 未配置模板路径"
        rel_path = _TEMPLATE_PATHS[self.display_name]
        template_path = os.path.join(get_root_dir(), "config", rel_path)
        assert os.path.exists(template_path), f"[set_config][{self.display_name}] 未找到模板文件: {template_path}"
        ext = os.path.splitext(template_path)[1].lower()
        with open(template_path, 'r', encoding='utf-8') as f:
            if ext == '.json':
                template = json.load(f)
            elif ext in ('.yaml', '.yml'):
                template = yaml.safe_load(f)
            else:
                raise ValueError(f"[set_config][{self.display_name}] 不支持的模板格式: {ext}")
        assert isinstance(template, dict), \
            f"[set_config][{self.display_name}] 模板必须是 dict"
        return template

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

    def _update_sequence(self, config: dict, dungeon_name: str, sequence: str | int | None) -> bool:
        """更新序列字段。返回是否修改。默认不启用。"""
        assert sequence is None, f"[set_config][{self.display_name}] 不支持 sequence 参数"
        return False

    def _init_config(self) -> None:
        """
        通用的 config 初始化逻辑：加载 config 和 template，检查对齐，合并更新。
        子类重写 _is_aligned 以实现特殊比较逻辑。
        """
        config = self._load()
        template = self._load_template()

        if self._is_aligned(config, template):
            return

        safe_update(config, template)
        print(f"[set_config][{self.display_name}] config 已更新")
        self._save(config)

    def _is_aligned(self, config: dict, template: dict) -> bool:
        """
        默认对齐检查：递归比较模板中的所有 key。
        对于 dict 递归检查，对于 list 按索引逐一比较，其余直接比较值。
        子类重写以实现特殊比较逻辑。
        """
        def _aligned(a, b):
            if isinstance(a, dict) and isinstance(b, dict):
                return all(k in a and _aligned(a[k], b[k]) for k in b)
            if isinstance(a, list) and isinstance(b, list):
                if len(a) < len(b):
                    return False
                return all(_aligned(a[i], b[i]) for i in range(len(b)))
            return a == b

        return all(key in config and _aligned(config[key], template[key]) for key, val in template.items())

    def set_dungeon(self, dungeon_name: str, sequence: str | int | None = None) -> None:
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

    def _update_sequence(self, config: dict, dungeon_name: str, sequence: str | int | None) -> bool:
        if sequence is None:
            return False
        if dungeon_name == "模拟领域":
            material_map = {
                "共鸣者经验": "Resonator EXP",
                "武器经验": "Weapon EXP",
                "贝币": "Shell Credit",
            }
            assert sequence in material_map, f"[set_config][{self.display_name}] 未适配的序列: {sequence}"
            target = material_map[sequence]
            key = "Material Selection"
        elif dungeon_name == "无音区":
            key = "Which Tacet Suppression to Farm"
            target = sequence
        elif dungeon_name == "凝素领域":
            key = "Which Forgery Challenge to Farm"
            target = sequence
        else:
            assert False, f"[set_config][{self.display_name}] 未适配的副本: {dungeon_name}"
        if config[key] == target:
            return False
        config[key] = target
        return True


# ---- 原神 Genshin Impact ----
class GenshinConfig(ScriptConfig):

    def __init__(self):
        self.display_name = "原神"
        self._task_key = "DomainName"
        self._init_config()

    def _init_config(self):
        """
        目前只确认与模板相同，未完全适配。
        PartyName 是用户自定义的，模板中不包含，只检查存在性。
        TODO: 完成适配后启用保存逻辑
        """
        config = self._load()
        assert "PartyName" in config, f"[set_config][{self.display_name}] config 中缺少字段: PartyName"
        template = self._load_template()
        assert self._is_aligned(config, template), f"[set_config][{self.display_name}] config 与模板不一致（未完成适配）"


# ---- 终末地 Arknights: Endfield ----
class EndfieldConfig(ScriptConfig):

    def __init__(self):
        self.display_name = "终末地"
        self._task_key = "体力本"
        self._init_config()

    def _init_config(self):
        # TODO: 确认包含了绳索等配置
        pass


# ---- 绝区零 Zenless Zone Zero ----
class ZenlessZoneZeroConfig(ScriptConfig):

    def __init__(self):
        self.display_name = "绝区零"
        self._init_config()

    def set_dungeon(self, dungeon_name: str, sequence: str | int | None = None):
        print(f"[set_config][{self.display_name}] zzz无需适配")


# ---- 崩铁 Honkai: Star Rail ----
class StarRailConfig(ScriptConfig):

    def __init__(self):
        self.display_name = "崩铁"
        self._task_key = "instance_type"
        self._init_config()


# ---- 异环 Neverness to Everness (NTE) ----
class NTEConfig(ScriptConfig):

    def __init__(self):
        self.display_name = "异环"
        self._task_key = "任务类型"
        self._seq_key_map = {
            "异能升级材料": "异能材料序号",
            "空幕": "空幕序号",
            "弧盘突破材料": "弧盘材料序号",
        }

    def _update_sequence(self, config: dict, dungeon_name: str, sequence: str | int | None) -> bool:
        assert sequence is not None, f"[set_config][{self.display_name}] 序列不能为空"
        assert dungeon_name in self._seq_key_map, f"[set_config][{self.display_name}] 未适配的副本: {dungeon_name}"
        key = self._seq_key_map[dungeon_name]
        if config[key] == sequence:
            return False
        config[key] = sequence
        return True


# ---- 明日方舟 Arknights（粥）----
class ArknightsConfig(ScriptConfig):

    def __init__(self):
        self.display_name = "粥"
        self._init_task_map()
        self._init_config()

    def _init_task_map(self):
        """
        self._task_map = {
            "剿灭":   {"index": 1, "stage": "Annihilation"},
            "红票":   {"index": 2, "stage": "AP-5"},
            "经验":   {"index": 3, "stage": "LS-6"},
            "龙门币": {"index": 4, "stage": "CE-6"},
            "土":     {"index": 5, "stage": "1-7"},
        }
        """
        template = self._load_template()
        task_config = template["Configurations"]["Default"]["TaskQueue"]
        self._task_map = {}
        for index, task in enumerate(task_config):
            if task.get("$type") == "FightTask":
                name = task.get("Name", "")
                stage = task.get("StagePlan", [])[0] if task.get("StagePlan") else ""
                if name and stage:
                    self._task_map[name] = {"index": index, "stage": stage}

    def _update_task(self, config: dict, dungeon_name: str) -> bool:
        """
        粥的副本设置逻辑：禁用所有副本 → 启用选定副本 → 启用刷土清理剩余体力。
        只有状态变化时返回 True。
        """
        task_config = config["Configurations"]["Default"]["TaskQueue"]
        assert dungeon_name in self._task_map, f"[set_config][{self.display_name}] 未适配的副本: {dungeon_name}"

        changed = False
        for name, info in self._task_map.items():
            idx = info["index"]
            stage = info["stage"]
            assert task_config[idx]["Name"] == name, \
                f"[set_config][{self.display_name}] TaskQueue[{idx}] Name 不匹配: 期望 {name}, 实际 {task_config[idx]['Name']}"
            assert task_config[idx]["StagePlan"] == [stage], \
                f"[set_config][{self.display_name}] TaskQueue[{idx}] StagePlan 不匹配: 期望 {[stage]}, 实际 {task_config[idx]['StagePlan']}"

            should_enable = (name == dungeon_name) or (name == "土")
            if task_config[idx]["IsEnable"] != should_enable:
                task_config[idx]["IsEnable"] = should_enable
                changed = True

        return changed


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
               sequence: str | int | None = None) -> None:
    """
    外观接口：为指定脚本设置副本和刷取序列

    Args:
        script_display_name: 脚本显示名称（与 config.yml 中一致）
        dungeon_name: 副本名称（来自 dungeon_list.yml），None 或 "未选择" 时跳过
        sequence: 刷取序列（字符串或整数），None 表示无序列
    """
    # 未选择副本时，不做更改
    if not dungeon_name or dungeon_name == "未选择":
        return

    assert script_display_name in _CONFIGS, f"[set_config] 未适配的脚本: {script_display_name}"
    cfg_cls = _CONFIGS[script_display_name]

    cfg_cls().set_dungeon(dungeon_name, sequence)
