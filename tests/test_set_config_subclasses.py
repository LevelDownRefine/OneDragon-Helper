"""
测试 set_config.py 中各 ScriptConfig 子类的行为。

覆盖每个子类的 _update_task / _update_sequence / set_dungeon / _init_config / _is_aligned 等方法。
所有文件 I/O 均通过 mock 隔离，不依赖真实 config 文件。
"""
import json
import yaml
import unittest
from unittest.mock import patch, mock_open, MagicMock

from src.config import set_config
from src.config.set_config import (
    ScriptConfig,
    WutheringWavesConfig,
    GenshinConfig,
    EndfieldConfig,
    ZenlessZoneZeroConfig,
    StarRailConfig,
    NTEConfig,
    ArknightsConfig,
)


# ============================================================
# 基类 ScriptConfig
# ============================================================

class TestScriptConfigBase(unittest.TestCase):
    """测试基类 _update_task / _update_sequence / set_dungeon 的默认行为"""

    def test_update_task_without_map_assigns_dungeon_name(self):
        """_task_map 为空时直接用 dungeon_name 赋值"""
        cfg = ScriptConfig()
        cfg.display_name = "测试"
        cfg._task_key = "task"
        cfg._task_map = {}
        config = {"task": "old"}
        changed = cfg._update_task(config, "new")
        self.assertTrue(changed)
        self.assertEqual(config["task"], "new")

    def test_update_task_no_change_returns_false(self):
        """值未变化时返回 False"""
        cfg = ScriptConfig()
        cfg.display_name = "测试"
        cfg._task_key = "task"
        cfg._task_map = {}
        config = {"task": "same"}
        changed = cfg._update_task(config, "same")
        self.assertFalse(changed)

    def test_update_task_with_map_translates(self):
        """_task_map 非空时做映射"""
        cfg = ScriptConfig()
        cfg.display_name = "测试"
        cfg._task_key = "task"
        cfg._task_map = {"副本A": "DungeonA"}
        config = {"task": "old"}
        changed = cfg._update_task(config, "副本A")
        self.assertTrue(changed)
        self.assertEqual(config["task"], "DungeonA")

    def test_update_task_unmapped_dungeon_raises(self):
        """副本不在 _task_map 中应 assert"""
        cfg = ScriptConfig()
        cfg.display_name = "测试"
        cfg._task_key = "task"
        cfg._task_map = {"副本A": "DungeonA"}
        config = {"task": "old"}
        with self.assertRaises(AssertionError):
            cfg._update_task(config, "不存在")

    def test_update_task_no_task_key_raises(self):
        """未设 _task_key 应 assert"""
        cfg = ScriptConfig()
        cfg.display_name = "测试"
        cfg._task_key = ""
        with self.assertRaises(AssertionError):
            cfg._update_task({}, "副本")

    def test_update_task_config_missing_key_raises(self):
        """config 中缺少 _task_key 字段应 assert"""
        cfg = ScriptConfig()
        cfg.display_name = "测试"
        cfg._task_key = "task"
        cfg._task_map = {}
        with self.assertRaises(AssertionError):
            cfg._update_task({}, "副本")

    def test_update_sequence_default_rejects_sequence(self):
        """基类默认 _update_sequence 不接受非 None 的 sequence"""
        cfg = ScriptConfig()
        cfg.display_name = "测试"
        with self.assertRaises(AssertionError):
            cfg._update_sequence({}, "副本", "序列")

    def test_update_sequence_default_none_returns_false(self):
        """基类默认 _update_sequence 接受 None 并返回 False"""
        cfg = ScriptConfig()
        cfg.display_name = "测试"
        self.assertFalse(cfg._update_sequence({}, "副本", None))

    def test_set_dungeon_changed_saves(self):
        """set_dungeon 有修改时应调用 _save"""
        cfg = ScriptConfig()
        cfg.display_name = "测试"
        cfg._task_key = "task"
        cfg._task_map = {}
        with patch.object(cfg, '_load', return_value={"task": "old"}), \
             patch.object(cfg, '_save') as mock_save:
            cfg.set_dungeon("new")
        mock_save.assert_called_once_with({"task": "new"})

    def test_set_dungeon_unchanged_no_save(self):
        """set_dungeon 无修改时不调用 _save"""
        cfg = ScriptConfig()
        cfg.display_name = "测试"
        cfg._task_key = "task"
        cfg._task_map = {}
        with patch.object(cfg, '_load', return_value={"task": "same"}), \
             patch.object(cfg, '_save') as mock_save:
            cfg.set_dungeon("same")
        mock_save.assert_not_called()


# ============================================================
# 鸣潮 WutheringWavesConfig
# ============================================================

class TestWutheringWavesConfig(unittest.TestCase):

    def setUp(self):
        self.cfg = WutheringWavesConfig()

    def test_init_attributes(self):
        self.assertEqual(self.cfg.display_name, "鸣潮")
        self.assertEqual(self.cfg._task_key, "Which to Farm")
        self.assertIn("凝素领域", self.cfg._task_map)
        self.assertIn("模拟领域", self.cfg._task_map)
        self.assertIn("无音区", self.cfg._task_map)

    def test_update_task_maps_dungeon(self):
        config = {"Which to Farm": "old"}
        changed = self.cfg._update_task(config, "无音区")
        self.assertTrue(changed)
        self.assertEqual(config["Which to Farm"], "Tacet Suppression")

    # ---- _update_sequence: 模拟领域 ----

    def test_update_sequence_simulation(self):
        config = {"Which to Farm": "Simulation Challenge", "Material Selection": "old"}
        changed = self.cfg._update_sequence(config, "模拟领域", "共鸣者经验")
        self.assertTrue(changed)
        self.assertEqual(config["Material Selection"], "Resonator EXP")

    def test_update_sequence_simulation_no_change(self):
        config = {"Which to Farm": "Simulation Challenge", "Material Selection": "Weapon EXP"}
        changed = self.cfg._update_sequence(config, "模拟领域", "武器经验")
        self.assertFalse(changed)

    def test_update_sequence_simulation_unknown_raises(self):
        config = {"Which to Farm": "Simulation Challenge", "Material Selection": "old"}
        with self.assertRaises(AssertionError):
            self.cfg._update_sequence(config, "模拟领域", "不存在")

    # ---- _update_sequence: 无音区 ----

    def test_update_sequence_tacet(self):
        config = {"Which to Farm": "Tacet Suppression", "Which Tacet Suppression to Farm": 1}
        changed = self.cfg._update_sequence(config, "无音区", "3")
        self.assertTrue(changed)
        self.assertEqual(config["Which Tacet Suppression to Farm"], "3")

    def test_update_sequence_tacet_no_change(self):
        config = {"Which to Farm": "Tacet Suppression", "Which Tacet Suppression to Farm": 2}
        changed = self.cfg._update_sequence(config, "无音区", "2")
        self.assertFalse(changed)

    # ---- _update_sequence: 凝素领域 ----

    def test_update_sequence_forgery(self):
        config = {"Which to Farm": "Forgery Challenge", "Which Forgery Challenge to Farm": 1}
        changed = self.cfg._update_sequence(config, "凝素领域", "4")
        self.assertTrue(changed)
        self.assertEqual(config["Which Forgery Challenge to Farm"], "4")

    def test_update_sequence_forgery_no_change(self):
        config = {"Which to Farm": "Forgery Challenge", "Which Forgery Challenge to Farm": 2}
        changed = self.cfg._update_sequence(config, "凝素领域", "2")
        self.assertFalse(changed)

    # ---- _update_sequence: None ----

    def test_update_sequence_none_returns_false(self):
        config = {"Which to Farm": "Simulation Challenge"}
        changed = self.cfg._update_sequence(config, "模拟领域", None)
        self.assertFalse(changed)

    # ---- _update_sequence: 未知副本类型 ----

    def test_update_sequence_unknown_dungeon_type_raises(self):
        config = {"Which to Farm": "Unknown Type"}
        with self.assertRaises(AssertionError):
            self.cfg._update_sequence(config, "未知", "1")

    # ---- set_dungeon 集成 ----

    def test_set_dungeon_with_sequence_saves(self):
        config = {
            "Which to Farm": "Forgery Challenge",
            "Which Forgery Challenge to Farm": 1,
        }
        with patch.object(self.cfg, '_load', return_value=config), \
             patch.object(self.cfg, '_save') as mock_save:
            self.cfg.set_dungeon("凝素领域", "3")
        mock_save.assert_called_once()
        saved = mock_save.call_args[0][0]
        self.assertEqual(saved["Which to Farm"], "Forgery Challenge")
        self.assertEqual(saved["Which Forgery Challenge to Farm"], "3")


# ============================================================
# 原神 GenshinConfig
# ============================================================

class TestGenshinConfig(unittest.TestCase):

    def test_init_attributes(self):
        template = {"DomainName": "测试", "PartyName": "队伍1"}
        with patch.object(GenshinConfig, '_init_config'), \
             patch('os.path.exists', return_value=True), \
             patch('builtins.open', mock_open(read_data=json.dumps(template))):
            cfg = GenshinConfig()
        self.assertEqual(cfg.display_name, "原神")
        self.assertEqual(cfg._task_key, "DomainName")

    def test_init_config_aligned_no_save(self):
        """config 与模板对齐（PartyName 不同但不为空）时不 save"""
        template = {"DomainName": "绝缘本", "PartyName": "队伍A"}
        config = {"DomainName": "绝缘本", "PartyName": "队伍B", "ExtraKey": "val"}
        with patch.object(GenshinConfig, '_load', return_value=config), \
             patch('os.path.exists', return_value=True), \
             patch('builtins.open', mock_open(read_data=json.dumps(template))), \
             patch.object(GenshinConfig, '_save') as mock_save:
            GenshinConfig()
        mock_save.assert_not_called()

    def test_init_config_misaligned_saves(self):
        """config 与模板不对齐时 save"""
        template = {"DomainName": "绝缘本", "PartyName": "队伍A"}
        config = {"DomainName": "旧本", "PartyName": "队伍B"}
        with patch.object(GenshinConfig, '_load', return_value=config), \
             patch('os.path.exists', return_value=True), \
             patch('builtins.open', mock_open(read_data=json.dumps(template))), \
             patch.object(GenshinConfig, '_save') as mock_save:
            GenshinConfig()
        mock_save.assert_called_once()
        saved = mock_save.call_args[0][0]
        self.assertEqual(saved["DomainName"], "绝缘本")
        # PartyName 不为空则保留
        self.assertEqual(saved["PartyName"], "队伍B")

    def test_init_config_party_name_missing_raises(self):
        """config 中缺少 PartyName 应 assert"""
        template = {"DomainName": "绝缘本", "PartyName": "队伍A"}
        config = {"DomainName": "绝缘本"}
        with patch.object(GenshinConfig, '_load', return_value=config), \
             patch('os.path.exists', return_value=True), \
             patch('builtins.open', mock_open(read_data=json.dumps(template))):
            with self.assertRaises(AssertionError):
                GenshinConfig()

    def test_update_task_uses_dungeon_name_directly(self):
        """原神 _task_map 为空，直接用 dungeon_name"""
        with patch.object(GenshinConfig, '_init_config'), \
             patch('os.path.exists', return_value=True), \
             patch('builtins.open', mock_open(read_data='{}')):
            cfg = GenshinConfig()
        config = {"DomainName": "旧本"}
        changed = cfg._update_task(config, "新本")
        self.assertTrue(changed)
        self.assertEqual(config["DomainName"], "新本")


# ============================================================
# 终末地 EndfieldConfig
# ============================================================

class TestEndfieldConfig(unittest.TestCase):

    def test_init_attributes(self):
        cfg = EndfieldConfig()
        self.assertEqual(cfg.display_name, "终末地")
        self.assertEqual(cfg._task_key, "体力本")
        self.assertEqual(cfg._task_map, {})

    def test_update_task_direct_assign(self):
        """终末地 _task_map 为空，直接用 dungeon_name"""
        cfg = EndfieldConfig()
        config = {"体力本": "旧本"}
        changed = cfg._update_task(config, "新本")
        self.assertTrue(changed)
        self.assertEqual(config["体力本"], "新本")

    def test_set_dungeon_no_sequence(self):
        cfg = EndfieldConfig()
        config = {"体力本": "旧本"}
        with patch.object(cfg, '_load', return_value=config), \
             patch.object(cfg, '_save') as mock_save:
            cfg.set_dungeon("新本")
        mock_save.assert_called_once_with({"体力本": "新本"})


# ============================================================
# 绝区零 ZenlessZoneZeroConfig
# ============================================================

class TestZenlessZoneZeroConfig(unittest.TestCase):

    def test_init_attributes(self):
        template = {"plan_list": [], "double_reward": False}
        with patch.object(ZenlessZoneZeroConfig, '_load', return_value=template), \
             patch('os.path.exists', return_value=True), \
             patch('builtins.open', mock_open(read_data=yaml.dump(template))), \
             patch.object(ZenlessZoneZeroConfig, '_save'):
            cfg = ZenlessZoneZeroConfig()
        self.assertEqual(cfg.display_name, "绝区零")
        self.assertEqual(cfg._task_key, "")

    def test_init_config_aligned_no_save(self):
        """config 与模板对齐时不 save"""
        template = {"plan_list": [{"tab_name": "A", "category_name": "x"}], "double_reward": False}
        config = {"plan_list": [{"tab_name": "A", "category_name": "x", "extra": 1}], "double_reward": False}
        with patch.object(ZenlessZoneZeroConfig, '_load', return_value=config), \
             patch('os.path.exists', return_value=True), \
             patch('builtins.open', mock_open(read_data=yaml.dump(template))), \
             patch.object(ZenlessZoneZeroConfig, '_save') as mock_save:
            ZenlessZoneZeroConfig()
        mock_save.assert_not_called()

    def test_init_config_misaligned_saves(self):
        """config 与模板不对齐时 save 模板"""
        template = {"plan_list": [{"tab_name": "A", "category_name": "x"}], "double_reward": True}
        config = {"plan_list": [{"tab_name": "B", "category_name": "y"}], "double_reward": False}
        with patch.object(ZenlessZoneZeroConfig, '_load', return_value=config), \
             patch('os.path.exists', return_value=True), \
             patch('builtins.open', mock_open(read_data=yaml.dump(template))), \
             patch.object(ZenlessZoneZeroConfig, '_save') as mock_save:
            ZenlessZoneZeroConfig()
        mock_save.assert_called_once_with(template)

    def test_set_dungeon_only_prints(self):
        """set_dungeon 应只 print 不做修改"""
        with patch.object(ZenlessZoneZeroConfig, '_init_config'), \
             patch('os.path.exists', return_value=True), \
             patch('builtins.open', mock_open(read_data='{}')):
            cfg = ZenlessZoneZeroConfig()
        with patch.object(cfg, '_load') as mock_load, \
             patch.object(cfg, '_save') as mock_save:
            cfg.set_dungeon("任何副本", "任何序列")
        mock_load.assert_not_called()
        mock_save.assert_not_called()

    # ---- _is_aligned 单元测试 ----

    def _make_cfg(self):
        """创建一个跳过 _init_config 的 ZenlessZoneZeroConfig 实例"""
        with patch.object(ZenlessZoneZeroConfig, '_init_config'):
            return ZenlessZoneZeroConfig()

    def test_is_aligned_identical(self):
        template = {"plan_list": [{"tab_name": "A", "category_name": "x"}], "double_reward": False}
        config = {"plan_list": [{"tab_name": "A", "category_name": "x"}], "double_reward": False}
        cfg = self._make_cfg()
        self.assertTrue(cfg._is_aligned(config, template))

    def test_is_aligned_extra_fields_in_config_ok(self):
        """config 中 plan_list 项有额外字段，模板中出现的字段一致即可"""
        template = {"plan_list": [{"tab_name": "A", "category_name": "x"}]}
        config = {"plan_list": [{"tab_name": "A", "category_name": "x", "extra": 1}]}
        cfg = self._make_cfg()
        self.assertTrue(cfg._is_aligned(config, template))

    def test_is_aligned_more_items_in_config_ok(self):
        """config plan_list 比模板长是可以的"""
        template = {"plan_list": [{"tab_name": "A", "category_name": "x"}]}
        config = {"plan_list": [
            {"tab_name": "A", "category_name": "x"},
            {"tab_name": "B", "category_name": "y"},
        ]}
        cfg = self._make_cfg()
        self.assertTrue(cfg._is_aligned(config, template))

    def test_is_aligned_order_mismatch_returns_false(self):
        """plan_list 顺序不一致应返回 False"""
        template = {"plan_list": [
            {"tab_name": "A", "category_name": "x"},
            {"tab_name": "B", "category_name": "y"},
        ]}
        config = {"plan_list": [
            {"tab_name": "B", "category_name": "y"},
            {"tab_name": "A", "category_name": "x"},
        ]}
        cfg = self._make_cfg()
        self.assertFalse(cfg._is_aligned(config, template))

    def test_is_aligned_field_value_mismatch_returns_false(self):
        """plan_list 项字段值不一致应返回 False"""
        template = {"plan_list": [{"tab_name": "A", "category_name": "x"}]}
        config = {"plan_list": [{"tab_name": "A", "category_name": "z"}]}
        cfg = self._make_cfg()
        self.assertFalse(cfg._is_aligned(config, template))

    def test_is_aligned_missing_field_returns_false(self):
        """plan_list 项缺少模板中出现的字段应返回 False"""
        template = {"plan_list": [{"tab_name": "A", "category_name": "x"}]}
        config = {"plan_list": [{"tab_name": "A"}]}
        cfg = self._make_cfg()
        self.assertFalse(cfg._is_aligned(config, template))

    def test_is_aligned_config_shorter_list_returns_false(self):
        """config plan_list 比模板短应返回 False"""
        template = {"plan_list": [
            {"tab_name": "A", "category_name": "x"},
            {"tab_name": "B", "category_name": "y"},
        ]}
        config = {"plan_list": [{"tab_name": "A", "category_name": "x"}]}
        cfg = self._make_cfg()
        self.assertFalse(cfg._is_aligned(config, template))

    def test_is_aligned_missing_top_key_returns_false(self):
        """config 缺少模板中的顶层 key 应返回 False"""
        template = {"double_reward": False}
        config = {}
        cfg = self._make_cfg()
        self.assertFalse(cfg._is_aligned(config, template))

    def test_is_aligned_top_key_value_mismatch_returns_false(self):
        """顶层 key 值不一致应返回 False"""
        template = {"double_reward": False}
        config = {"double_reward": True}
        cfg = self._make_cfg()
        self.assertFalse(cfg._is_aligned(config, template))


# ============================================================
# 崩铁 StarRailConfig
# ============================================================

class TestStarRailConfig(unittest.TestCase):

    def test_init_attributes(self):
        cfg = StarRailConfig()
        self.assertEqual(cfg.display_name, "崩铁")
        self.assertEqual(cfg._task_key, "instance_type")
        self.assertEqual(cfg._task_map, {})

    def test_update_task_direct_assign(self):
        cfg = StarRailConfig()
        config = {"instance_type": "旧本"}
        changed = cfg._update_task(config, "新本")
        self.assertTrue(changed)
        self.assertEqual(config["instance_type"], "新本")

    def test_set_dungeon_changed_saves(self):
        cfg = StarRailConfig()
        config = {"instance_type": "旧本"}
        with patch.object(cfg, '_load', return_value=config), \
             patch.object(cfg, '_save') as mock_save:
            cfg.set_dungeon("新本")
        mock_save.assert_called_once_with({"instance_type": "新本"})


# ============================================================
# 异环 NTEConfig
# ============================================================

class TestNTEConfig(unittest.TestCase):

    def setUp(self):
        self.cfg = NTEConfig()

    def test_init_attributes(self):
        self.assertEqual(self.cfg.display_name, "异环")
        self.assertEqual(self.cfg._task_key, "任务类型")
        self.assertIn("空幕", self.cfg._seq_key_map)
        self.assertEqual(self.cfg._seq_key_map["空幕"], "空幕序号")

    def test_update_sequence_changes_value(self):
        config = {"空幕序号": 1}
        changed = self.cfg._update_sequence(config, "空幕", "3")
        self.assertTrue(changed)
        self.assertEqual(config["空幕序号"], "3")

    def test_update_sequence_no_change(self):
        config = {"空幕序号": 2}
        changed = self.cfg._update_sequence(config, "空幕", "2")
        self.assertFalse(changed)

    def test_update_sequence_none_raises(self):
        """异环要求 sequence 不能为 None"""
        config = {"空幕序号": 1}
        with self.assertRaises(AssertionError):
            self.cfg._update_sequence(config, "空幕", None)

    def test_update_sequence_unknown_dungeon_raises(self):
        config = {"未知序号": 1}
        with self.assertRaises(AssertionError):
            self.cfg._update_sequence(config, "不存在", "1")

    def test_update_sequence_all_mapped_dungeons(self):
        """测试 _seq_key_map 中所有副本都能正确更新"""
        for dungeon_name, seq_key in self.cfg._seq_key_map.items():
            config = {seq_key: 0}
            changed = self.cfg._update_sequence(config, dungeon_name, "5")
            self.assertTrue(changed, f"{dungeon_name} 未正确更新")
            self.assertEqual(config[seq_key], "5")

    def test_set_dungeon_with_sequence_saves(self):
        config = {"任务类型": "空幕", "空幕序号": 1}
        with patch.object(self.cfg, '_load', return_value=config), \
             patch.object(self.cfg, '_save') as mock_save:
            self.cfg.set_dungeon("空幕", "3")
        mock_save.assert_called_once()
        saved = mock_save.call_args[0][0]
        self.assertEqual(saved["空幕序号"], "3")


# ============================================================
# 明日方舟 ArknightsConfig（粥）
# ============================================================

class TestArknightsConfig(unittest.TestCase):
    """测试粥的 _make_fight_task / _is_aligned / _init_config / set_dungeon"""

    def _make_cfg(self):
        """创建一个跳过 _init_config 的 ArknightsConfig 实例"""
        with patch.object(ArknightsConfig, '_init_config'):
            return ArknightsConfig()

    def test_init_attributes(self):
        cfg = self._make_cfg()
        self.assertEqual(cfg.display_name, "粥")
        self.assertIn("剿灭", cfg._task_map)
        self.assertEqual(cfg._task_map["剿灭"]["index"], 1)
        self.assertEqual(cfg._task_map["土"]["index"], 5)

    # ---- _make_fight_task ----

    def test_make_fight_task_basic(self):
        cfg = self._make_cfg()
        task = cfg._make_fight_task("剿灭")
        self.assertEqual(task["$type"], "FightTask")
        self.assertEqual(task["Name"], "剿灭")
        self.assertEqual(task["StagePlan"], ["Annihilation"])
        self.assertEqual(task["IsEnable"], False)  # 默认 False

    def test_make_fight_task_with_kwargs(self):
        cfg = self._make_cfg()
        task = cfg._make_fight_task("土", is_enable=True, drop_count=5, use_expiring_medicine=True)
        self.assertTrue(task["IsEnable"])
        self.assertEqual(task["DropCount"], 5)
        self.assertTrue(task["UseExpiringMedicine"])
        self.assertEqual(task["StagePlan"], ["1-7"])

    def test_make_fight_task_hide_unavailable(self):
        cfg = self._make_cfg()
        task = cfg._make_fight_task("剿灭", hide_unavailable=True)
        self.assertTrue(task["HideUnavailableStage"])

    # ---- _is_aligned ----

    def test_is_aligned_identical(self):
        cfg = self._make_cfg()
        template = [
            {"Name": "开始唤醒", "$type": "StartUpTask"},
            {"Name": "剿灭", "$type": "FightTask", "StagePlan": ["Annihilation"]},
        ]
        cur = [
            {"Name": "开始唤醒", "$type": "StartUpTask", "ExtraKey": 1},
            {"Name": "剿灭", "$type": "FightTask", "StagePlan": ["Annihilation"], "IsEnable": True},
        ]
        self.assertTrue(cfg._is_aligned(cur, template))

    def test_is_aligned_name_mismatch(self):
        cfg = self._make_cfg()
        template = [{"Name": "剿灭", "$type": "FightTask"}]
        cur = [{"Name": "红票", "$type": "FightTask"}]
        self.assertFalse(cfg._is_aligned(cur, template))

    def test_is_aligned_type_mismatch(self):
        cfg = self._make_cfg()
        template = [{"Name": "剿灭", "$type": "FightTask"}]
        cur = [{"Name": "剿灭", "$type": "StartUpTask"}]
        self.assertFalse(cfg._is_aligned(cur, template))

    def test_is_aligned_stageplan_mismatch(self):
        cfg = self._make_cfg()
        template = [{"Name": "剿灭", "$type": "FightTask", "StagePlan": ["Annihilation"]}]
        cur = [{"Name": "剿灭", "$type": "FightTask", "StagePlan": ["AP-5"]}]
        self.assertFalse(cfg._is_aligned(cur, template))

    def test_is_aligned_cur_shorter_returns_false(self):
        cfg = self._make_cfg()
        template = [{"Name": "A", "$type": "X"}, {"Name": "B", "$type": "Y"}]
        cur = [{"Name": "A", "$type": "X"}]
        self.assertFalse(cfg._is_aligned(cur, template))

    def test_is_aligned_cur_longer_ok(self):
        """cur 比 template 长是可以的"""
        cfg = self._make_cfg()
        template = [{"Name": "A", "$type": "X"}]
        cur = [{"Name": "A", "$type": "X"}, {"Name": "B", "$type": "Y"}]
        self.assertTrue(cfg._is_aligned(cur, template))

    def test_is_aligned_non_fight_task_skips_stageplan(self):
        """非 FightTask 不检查 StagePlan"""
        cfg = self._make_cfg()
        template = [{"Name": "自动公招", "$type": "RecruitTask"}]
        cur = [{"Name": "自动公招", "$type": "RecruitTask"}]
        self.assertTrue(cfg._is_aligned(cur, template))

    # ---- _init_config ----

    def test_init_config_aligned_no_save(self):
        """TaskQueue 已与模板对齐时不 save"""
        cfg = self._make_cfg()
        template_queue = [
            {"Name": "开始唤醒", "$type": "StartUpTask"},
            {"Name": "剿灭", "$type": "FightTask", "StagePlan": ["Annihilation"]},
            {"Name": "红票", "$type": "FightTask", "StagePlan": ["AP-5"]},
            {"Name": "经验", "$type": "FightTask", "StagePlan": ["LS-6"]},
            {"Name": "龙门币", "$type": "FightTask", "StagePlan": ["CE-6"]},
            {"Name": "土", "$type": "FightTask", "StagePlan": ["1-7"]},
            {"Name": "自动公招", "$type": "RecruitTask"},
            {"Name": "基建换班", "$type": "InfrastTask"},
            {"Name": "信用收支", "$type": "MallTask"},
            {"Name": "领取奖励", "$type": "AwardTask"},
        ]

        config = {"Configurations": {"Default": {"TaskQueue": template_queue}}}
        with patch.object(cfg, '_load', return_value=config), \
             patch('os.path.exists', return_value=True), \
             patch('builtins.open', mock_open(read_data=json.dumps(template_queue))), \
             patch.object(cfg, '_save') as mock_save:
            cfg._init_config()
        mock_save.assert_not_called()

    def test_init_config_misaligned_saves(self):
        """TaskQueue 不对齐时 save"""
        cfg = self._make_cfg()
        template_queue = [
            {"Name": "开始唤醒", "$type": "StartUpTask"},
            {"Name": "剿灭", "$type": "FightTask", "StagePlan": ["Annihilation"]},
            {"Name": "红票", "$type": "FightTask", "StagePlan": ["AP-5"]},
            {"Name": "经验", "$type": "FightTask", "StagePlan": ["LS-6"]},
            {"Name": "龙门币", "$type": "FightTask", "StagePlan": ["CE-6"]},
            {"Name": "土", "$type": "FightTask", "StagePlan": ["1-7"]},
            {"Name": "自动公招", "$type": "RecruitTask"},
            {"Name": "基建换班", "$type": "InfrastTask"},
            {"Name": "信用收支", "$type": "MallTask"},
            {"Name": "领取奖励", "$type": "AwardTask"},
        ]
        cur_queue = [{"Name": "wrong", "$type": "Unknown"}]
        config = {"Configurations": {"Default": {"TaskQueue": cur_queue}}}
        with patch.object(cfg, '_load', return_value=config), \
             patch('os.path.exists', return_value=True), \
             patch('builtins.open', mock_open(read_data=json.dumps(template_queue))), \
             patch.object(cfg, '_save') as mock_save:
            cfg._init_config()
        mock_save.assert_called_once()
        saved = mock_save.call_args[0][0]
        saved_queue = saved["Configurations"]["Default"]["TaskQueue"]
        self.assertEqual(len(saved_queue), 10)
        self.assertEqual(saved_queue[0]["Name"], "开始唤醒")
        self.assertEqual(saved_queue[1]["Name"], "剿灭")
        self.assertEqual(saved_queue[5]["Name"], "土")

    # ---- set_dungeon ----

    def test_set_dungeon_disables_all_enables_selected_and_土(self):
        cfg = self._make_cfg()
        # 构造合法的 TaskQueue
        queue = [None] * 10
        queue[0] = {"Name": "开始唤醒", "$type": "StartUpTask"}
        for name, info in cfg._task_map.items():
            queue[info["index"]] = {
                "Name": name, "$type": "FightTask",
                "StagePlan": [info["stage"]], "IsEnable": True,
            }
        queue[6] = {"Name": "自动公招", "$type": "RecruitTask"}
        queue[7] = {"Name": "基建换班", "$type": "InfrastTask"}
        queue[8] = {"Name": "信用收支", "$type": "MallTask"}
        queue[9] = {"Name": "领取奖励", "$type": "AwardTask"}

        config = {"Configurations": {"Default": {"TaskQueue": queue}}}
        with patch.object(cfg, '_load', return_value=config), \
             patch.object(cfg, '_save') as mock_save:
            cfg.set_dungeon("红票")

        mock_save.assert_called_once()
        saved_queue = mock_save.call_args[0][0]["Configurations"]["Default"]["TaskQueue"]
        # 红票启用
        self.assertTrue(saved_queue[2]["IsEnable"])
        # 土启用（清理剩余体力）
        self.assertTrue(saved_queue[5]["IsEnable"])
        # 其他副本禁用
        self.assertFalse(saved_queue[1]["IsEnable"])  # 剿灭
        self.assertFalse(saved_queue[3]["IsEnable"])  # 经验
        self.assertFalse(saved_queue[4]["IsEnable"])  # 龙门币

    def test_set_dungeon_unknown_raises(self):
        cfg = self._make_cfg()
        config = {"Configurations": {"Default": {"TaskQueue": []}}}
        with patch.object(cfg, '_load', return_value=config):
            with self.assertRaises(AssertionError):
                cfg.set_dungeon("不存在")

    def test_set_dungeon_name_mismatch_raises(self):
        """TaskQueue 中 Name 不匹配应 assert"""
        cfg = self._make_cfg()
        queue = [None] * 10
        queue[1] = {"Name": "wrong", "$type": "FightTask", "StagePlan": ["Annihilation"], "IsEnable": True}
        config = {"Configurations": {"Default": {"TaskQueue": queue}}}
        with patch.object(cfg, '_load', return_value=config):
            with self.assertRaises(AssertionError):
                cfg.set_dungeon("剿灭")


# ============================================================
# 外观接口 set_config()
# ============================================================

class TestSetConfigFacade(unittest.TestCase):
    """测试外观接口 set_config() 的分发逻辑"""

    def test_skip_when_dungeon_name_none(self):
        """dungeon_name 为 None 时直接返回，不创建实例"""
        mock_instance = MagicMock()
        mock_cls = MagicMock(return_value=mock_instance)
        with patch.dict('src.config.set_config._CONFIGS', {"鸣潮": mock_cls}):
            set_config.set_config("鸣潮", None, None)
        mock_cls.assert_not_called()
        mock_instance.set_dungeon.assert_not_called()

    def test_skip_when_dungeon_name_empty(self):
        set_config.set_config("鸣潮", "", None)

    def test_skip_when_dungeon_name_unselected(self):
        set_config.set_config("鸣潮", "未选择", None)

    def test_unknown_script_raises(self):
        with self.assertRaises(AssertionError):
            set_config.set_config("不存在", "副本", "序列")

    def test_dispatches_to_correct_subclass(self):
        """验证 set_config 正确分发到对应子类"""
        mock_instance = MagicMock()
        mock_cls = MagicMock(return_value=mock_instance)
        with patch.dict('src.config.set_config._CONFIGS', {"鸣潮": mock_cls}):
            set_config.set_config("鸣潮", "无音区", "1")
        mock_cls.assert_called_once()
        mock_instance.set_dungeon.assert_called_once_with("无音区", "1")


if __name__ == "__main__":
    unittest.main()
