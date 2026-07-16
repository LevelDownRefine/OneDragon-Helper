"""
副本配置适配器（外观模式）
对外提供统一的 set_config 接口，内部封装各自动化脚本的 config 读写逻辑。

每个脚本的 config 格式、路径、字段名都不同，
各脚本子类单独适配，上层无需关心差异。

config 路径推导：
  1. 从 config.yml 中取得各脚本的 script_path（exe 路径），取其父目录作为脚本根目录
  2. _CONFIG_REL_PATHS 标注了各 config 相对于脚本根目录的路径
  3. 拼接根目录 + 相对路径 = config 文件绝对路径
"""

import os
import json
import yaml
from typing import Any

from src.utils import get_config_yml_path_under_root, get_root_dir


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

def load_config(script_display_name: str) -> Any:
    """
    读取指定脚本的 config 文件，返回解析后的 dict/list。
    支持 .json 和 .yaml/.yml 格式。
    并确保 config 文件能被读取。
    """
    path = get_config_path(script_display_name)
    ext = os.path.splitext(path)[1].lower()
    with open(path, 'r', encoding='utf-8') as f:
        if ext == '.json':
            return json.load(f)
        elif ext in ('.yaml', '.yml'):
            return yaml.safe_load(f)
        raise ValueError(f"[set_config] 不支持的 config 格式: {ext}")


def save_config(script_display_name: str, data: Any) -> None:
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

    # ---- 安全检查工具 ----

    def _assert_template_exists(self, template_path: str) -> None:
        """
        检查模板文件是否存在，不存在则抛出 AssertionError。
        统一格式：[set_config][display_name] 未找到模板文件: path。
        """
        assert os.path.exists(template_path), f"[set_config][{self.display_name}] 未找到模板文件: {template_path}"

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
        assert sequence is None, f"[set_config][{self.display_name}] 子类必须设 _update_sequence"
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
        self._init_config()

    def _init_config(self):
        config = self._load()
        template_path = os.path.join(get_root_dir(), "config", "BGI一条龙.json")
        self._assert_template_exists(template_path)
        with open(template_path, 'r', encoding='utf-8') as f:
            template = json.load(f)

        changed = False
        for key, val in template.items():
            if key == "PartyName":
                # PartyName 可以与模板不同，但不能为空
                assert key in config, f"[set_config][{self.display_name}] config 中缺少字段: {key}"
            elif key not in config or config[key] != val:
                config[key] = val
                changed = True

        if changed:
            print(f"[set_config][{self.display_name}] init config") # TODO: assert False
            self._save(config)


# ---- 终末地 Arknights: Endfield ----
class EndfieldConfig(ScriptConfig):

    def __init__(self):
        self.display_name = "终末地"
        self._task_key = "体力本"


# ---- 绝区零 Zenless Zone Zero ----
class ZenlessZoneZeroConfig(ScriptConfig):

    def __init__(self):
        self.display_name = "绝区零"
        self._init_config()

    def _init_config(self):
        config = self._load()
        template_path = os.path.join(get_root_dir(), "config", "zzz_charge_plan.yml")
        self._assert_template_exists(template_path)
        with open(template_path, 'r', encoding='utf-8') as f:
            template = yaml.safe_load(f)

        if self._is_aligned(config, template):
            return

        print(f"[set_config][{self.display_name}] init config")
        self._save(template)

    def set_dungeon(self, dungeon_name: str, sequence: str | None = None):
        print(f"[set_config][{self.display_name}] zzz无需适配")

    def _is_aligned(self, config: dict, template: dict) -> bool:
        """
        检查游戏脚本 config 与模板是否对齐（严格要求顺序一致）：
        - plan_list: 逐项按顺序比较，模板中出现的字段必须一致
        - 其余顶层 key（double_reward 等）：值必须一致
        """
        for key, val in template.items():
            if key not in config:
                return False
            if key == "plan_list":
                cur_list = config[key]
                if len(cur_list) < len(val):
                    return False
                for i, tpl_item in enumerate(val):
                    cur_item = cur_list[i]
                    for field, field_val in tpl_item.items():
                        if field not in cur_item or cur_item[field] != field_val:
                            return False
            else:
                if config[key] != val:
                    return False
        return True


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
        self._seq_key_map = {
            "异能升级材料": "异能材料序号",
            "空幕": "空幕序号",
            "弧盘突破材料": "弧盘材料序号",
        }

    def _update_sequence(self, config: dict, dungeon_name: str, sequence: str | None) -> bool:
        assert sequence is not None, f"[set_config][{self.display_name}] 序列不能为空"
        assert dungeon_name in self._seq_key_map, f"[set_config][{self.display_name}] 未适配的副本: {dungeon_name}"
        key = self._seq_key_map[dungeon_name]
        if str(config[key]) == sequence:
            return False
        config[key] = str(sequence)
        return True


# ---- 明日方舟 Arknights（粥）----
class ArknightsConfig(ScriptConfig):

    def __init__(self):
        self.display_name = "粥"
        self._task_map = {
            "剿灭":   {"index": 1, "stage": "Annihilation"},
            "红票":   {"index": 2, "stage": "AP-5"},
            "经验":   {"index": 3, "stage": "LS-6"},
            "龙门币": {"index": 4, "stage": "CE-6"},
            "土":     {"index": 5, "stage": "1-7"},
        }
        self._init_config()

    def _make_fight_task(self, name: str, *, is_enable: bool = False,
                         hide_unavailable: bool = False, drop_count: int = 0,
                         use_expiring_medicine: bool = False) -> dict:
        """生成 FightTask 模板，stage 从 self._task_map 获取"""
        stage = self._task_map[name]["stage"]
        return {'$type': 'FightTask', 'UseMedicine': False, 'MedicineCount': 0, 'UseStone': False,
                'StoneCount': 0, 'EnableTargetDrop': False, 'DropId': '', 'DropCount': drop_count, 'IsInventoryTarget': False, 'EnableTimesLimit': False,
                'TimesLimit': 2147483647, 'Series': 0, 'StagePlan': [stage], 'IsDrGrandet': False, 'UseExpiringMedicine': use_expiring_medicine, 'MedicineExpireDays': 2,
                'UseExpireMedicineForActivity': False, 'UseCustomAnnihilation': False, 'AnnihilationStage': 'Annihilation', 'HideUnavailableStage': hide_unavailable,
                'IsStageManually': False, 'UseOptionalStage': False, 'UseStoneAllowSave': False, 'HideSeries': False, 'StageResetMode': 'Current',
                'UseWeeklySchedule': False, 'Name': name, 'IsEnable': is_enable, 'TaskType': 'Fight'}

    def _init_config(self):
        config = self._load()
        cur_config = config["Configurations"]["Default"]["TaskQueue"]

        template_path = os.path.join(get_root_dir(), "config", "MAA一条龙.json")
        self._assert_template_exists(template_path)
        with open(template_path, 'r', encoding='utf-8') as f:
            task_config = json.load(f)

        if self._is_aligned(cur_config, task_config):
            return

        config["Configurations"]["Default"]["TaskQueue"] = task_config
        print(f"[set_config][{self.display_name}] init config")
        self._save(config)

    def _is_aligned(self, cur: list, template: list) -> bool:
        """比较当前 TaskQueue 与模板是否一致（只比较关键字段）"""
        if len(cur) < len(template):
            return False
        for i in range(len(template)):
            if cur[i].get("Name") != template[i]["Name"]:
                return False
            if cur[i].get("$type") != template[i]["$type"]:
                return False
            if template[i]["$type"] == "FightTask":
                if cur[i].get("StagePlan") != template[i]["StagePlan"]:
                    return False
        return True

    # ---- set_dungeon ----

    def set_dungeon(self, dungeon_name: str, sequence: str | None = None):
        config = self._load()
        task_config = config["Configurations"]["Default"]["TaskQueue"]
        assert dungeon_name in self._task_map, f"[set_config][{self.display_name}] 未适配的副本: {dungeon_name}"

        # 校验并禁用所有副本任务
        for name, info in self._task_map.items():
            idx = info["index"]
            stage = info["stage"]
            assert task_config[idx]["Name"] == name, \
                f"[set_config][{self.display_name}] TaskQueue[{idx}] Name 不匹配: 期望 {name}, 实际 {task_config[idx]['Name']}"
            assert task_config[idx]["StagePlan"] == [stage], \
                f"[set_config][{self.display_name}] TaskQueue[{idx}] StagePlan 不匹配: 期望 {[stage]}, 实际 {task_config[idx]['StagePlan']}"
            task_config[idx]["IsEnable"] = False

        # 启用选定副本
        task_config[self._task_map[dungeon_name]["index"]]["IsEnable"] = True
        # 启用刷土清理剩余体力
        task_config[self._task_map["土"]["index"]]["IsEnable"] = True

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
