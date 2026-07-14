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
        return {'$type': 'FightTask', 'UseMedicine': False, 'MedicineCount': 0, 'UseStone': False, 'StoneCount': 0, 'EnableTargetDrop': False, 'DropId': '', 'DropCount': drop_count, 'IsInventoryTarget': False, 'EnableTimesLimit': False, 'TimesLimit': 2147483647, 'Series': 0, 'StagePlan': [stage], 'IsDrGrandet': False, 'UseExpiringMedicine': use_expiring_medicine, 'MedicineExpireDays': 2, 'UseExpireMedicineForActivity': False, 'UseCustomAnnihilation': False, 'AnnihilationStage': 'Annihilation', 'HideUnavailableStage': hide_unavailable, 'IsStageManually': False, 'UseOptionalStage': False, 'UseStoneAllowSave': False, 'HideSeries': False, 'StageResetMode': 'Current', 'UseWeeklySchedule': False, 'Name': name, 'IsEnable': is_enable, 'TaskType': 'Fight'}

    def _init_config(self):
        config = self._load()
        cur_config = config["Configurations"]["Default"]["TaskQueue"]

        task_config: list = [None] * 10
        task_config[0] = {'$type': 'StartUpTask', 'AccountName': '', 'AccountSwitchEnabled': False, 'Name': '开始唤醒', 'IsEnable': True, 'TaskType': 'StartUp'}
        # 索引 1-5: 由 _task_map 生成 FightTask
        task_config[1] = self._make_fight_task("剿灭", is_enable=True, hide_unavailable=True)
        task_config[2] = self._make_fight_task("红票")
        task_config[3] = self._make_fight_task("经验")
        task_config[4] = self._make_fight_task("龙门币")
        task_config[5] = self._make_fight_task("土", is_enable=True, drop_count=5, use_expiring_medicine=True)
        # 索引 6-9: 非战斗任务
        task_config[6] = {'$type': 'RecruitTask', 'MaxTimes': 4, 'ExtraTagMode': 0, 'Level3PreferTags': [], 'PreferTagEnabled': True, 'PreserveTagList': ['支援机械'], 'PreserveTagEnabled': False, 'RefreshLevel3': True, 'ForceRefresh': True, 'Level3Choose': True, 'Level4Choose': True, 'Level5Choose': True, 'Level6Choose': False, 'Level3Time': 540, 'Level4Time': 540, 'Name': '自动公招', 'IsEnable': True, 'TaskType': 'Recruit'}
        task_config[7] = {'$type': 'InfrastTask', 'Mode': 'Normal', 'UsesOfDrones': 'PureGold', 'DormThreshold': 30, 'DormTrustEnabled': True, 'OriginiumShardAutoReplenishment': True, 'DormFilterNotStationed': True, 'ReceptionMessageBoard': True, 'ReceptionClueExchange': True, 'SendClue': True, 'ContinueTraining': False, 'Filename': '', 'PlanSelect': -1, 'RoomList': [{'Room': 'Mfg'}, {'Room': 'Trade'}, {'Room': 'Control'}, {'Room': 'Power'}, {'Room': 'Reception'}, {'Room': 'Office'}, {'Room': 'Dorm'}, {'Room': 'Processing'}, {'Room': 'Training'}], 'Name': '基建换班', 'IsEnable': True, 'TaskType': 'Infrast'}
        task_config[8] = {'$type': 'MallTask', 'Shopping': True, 'CreditFight': False, 'CreditFightFormation': 0, 'CreditFightLastTime': '2025/09/13 00:00:00', 'CreditFightOnceADay': True, 'VisitFriends': True, 'VisitFriendsOnceADay': True, 'VisitFriendsLastTime': '2026/07/14 00:00:00', 'FirstList': '招聘许可', 'BlackList': '碳;家具;加急许可', 'ShoppingIgnoreBlackListWhenFull': False, 'OnlyBuyDiscount': False, 'ReserveMaxCredit': False, 'IsCreditFightAvailable': False, 'IsVisitFriendsAvailable': False, 'Name': '信用收支', 'IsEnable': True, 'TaskType': 'Mall'}
        task_config[9] = {'$type': 'AwardTask', 'Award': True, 'Mail': True, 'FreeGacha': True, 'Orundum': True, 'Mining': True, 'SpecialAccess': True, 'Name': '领取奖励', 'IsEnable': True, 'TaskType': 'Award'}

        if self._is_task_queue_equal(cur_config, task_config):
            return

        config["Configurations"]["Default"]["TaskQueue"] = task_config
        print(f"[set_config][{self.display_name}] init config")
        self._save(config)

    def _is_task_queue_equal(self, cur: list, template: list) -> bool:
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
