"""
测试 set_config.py 中各 ScriptConfig 子类的行为。

覆盖每个子类的 _update_task / _update_sequence / set_dungeon / _init_config / _is_aligned 等方法。
所有文件 I/O 均通过 mock 隔离，不依赖真实 config 文件。
"""

import json
import unittest
from unittest.mock import MagicMock, mock_open, patch

import yaml

from src.config import set_config
from src.config.set_config import (
    ArknightsConfig,
    EndfieldConfig,
    GenshinConfig,
    NTEConfig,
    ScriptConfig,
    StarRailConfig,
    WutheringWavesConfig,
    ZenlessZoneZeroConfig,
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
        with (
            patch.object(cfg, "_load", return_value={"task": "old"}),
            patch.object(cfg, "_save") as mock_save,
        ):
            cfg.set_dungeon("new")
        mock_save.assert_called_once_with({"task": "new"})

    def test_set_dungeon_unchanged_no_save(self):
        """set_dungeon 无修改时不调用 _save"""
        cfg = ScriptConfig()
        cfg.display_name = "测试"
        cfg._task_key = "task"
        cfg._task_map = {}
        with (
            patch.object(cfg, "_load", return_value={"task": "same"}),
            patch.object(cfg, "_save") as mock_save,
        ):
            cfg.set_dungeon("same")
        mock_save.assert_not_called()


# ============================================================
# _save / _verify_saved（保存后重读校验）
# ============================================================


class TestVerifySaved(unittest.TestCase):
    """测试 _save 保存后重读校验（_verify_saved）"""

    def _make_cfg(self):
        cfg = ScriptConfig()
        cfg._script_name = "测试"
        cfg.display_name = "测试展示名"
        return cfg

    def test_save_round_trip_verifies_ok(self):
        """_save 写盘后重读一致，不抛异常且按预期调用 save_config"""
        cfg = self._make_cfg()
        sample = {"k": "v", "n": 1}
        with (
            patch.object(cfg, "_load", return_value=sample),
            patch("src.config.set_config.save_config") as mock_save,
        ):
            cfg._save(sample)  # 不应抛异常
        mock_save.assert_called_once_with("测试", "", sample)

    def test_save_mismatch_raises(self):
        """_save 后重读内容不一致应 assert"""
        cfg = self._make_cfg()
        with (
            patch.object(cfg, "_load", return_value={"k": "different"}),
            patch("src.config.set_config.save_config"),
            self.assertRaises(AssertionError),
        ):
            cfg._save({"k": "expected"})

    def test_verify_saved_equal_ok(self):
        """_verify_saved 重读等于预期时不抛异常"""
        cfg = self._make_cfg()
        with patch.object(cfg, "_load", return_value={"a": 1}):
            cfg._verify_saved({"a": 1})

    def test_verify_saved_not_equal_raises(self):
        """_verify_saved 重读不等于预期时 assert"""
        cfg = self._make_cfg()
        with (
            patch.object(cfg, "_load", return_value={"a": 2}),
            self.assertRaises(AssertionError),
        ):
            cfg._verify_saved({"a": 1})


# ============================================================
# 鸣潮 WutheringWavesConfig
# ============================================================


class TestWutheringWavesConfig(unittest.TestCase):
    def setUp(self):
        self.cfg = WutheringWavesConfig()

    def test_init_attributes(self):
        self.assertEqual(self.cfg.display_name, "鸣潮")
        self.assertEqual(self.cfg._script_name, "ok-ww")
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
        config = {
            "Which to Farm": "Simulation Challenge",
            "Material Selection": "Weapon EXP",
        }
        changed = self.cfg._update_sequence(config, "模拟领域", "武器经验")
        self.assertFalse(changed)

    def test_update_sequence_simulation_unknown_raises(self):
        config = {"Which to Farm": "Simulation Challenge", "Material Selection": "old"}
        with self.assertRaises(AssertionError):
            self.cfg._update_sequence(config, "模拟领域", "不存在")

    # ---- _update_sequence: 无音区 ----

    def test_update_sequence_tacet(self):
        config = {
            "Which to Farm": "Tacet Suppression",
            "Which Tacet Suppression to Farm": 1,
        }
        changed = self.cfg._update_sequence(config, "无音区", 3)
        self.assertTrue(changed)
        self.assertEqual(config["Which Tacet Suppression to Farm"], 3)

    def test_update_sequence_tacet_no_change(self):
        config = {
            "Which to Farm": "Tacet Suppression",
            "Which Tacet Suppression to Farm": 2,
        }
        changed = self.cfg._update_sequence(config, "无音区", 2)
        self.assertFalse(changed)

    # ---- _update_sequence: 凝素领域 ----

    def test_update_sequence_forgery(self):
        config = {
            "Which to Farm": "Forgery Challenge",
            "Which Forgery Challenge to Farm": 1,
        }
        changed = self.cfg._update_sequence(config, "凝素领域", 4)
        self.assertTrue(changed)
        self.assertEqual(config["Which Forgery Challenge to Farm"], 4)

    def test_update_sequence_forgery_no_change(self):
        config = {
            "Which to Farm": "Forgery Challenge",
            "Which Forgery Challenge to Farm": 2,
        }
        changed = self.cfg._update_sequence(config, "凝素领域", 2)
        self.assertFalse(changed)

    # ---- _update_sequence: None ----

    def test_update_sequence_none_raises(self):
        config = {"Which to Farm": "Simulation Challenge"}
        with self.assertRaises(AssertionError):
            self.cfg._update_sequence(config, "模拟领域", None)

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
        with (
            patch.object(self.cfg, "_load", return_value=config),
            patch.object(self.cfg, "_save") as mock_save,
        ):
            self.cfg.set_dungeon("凝素领域", 3)
        mock_save.assert_called_once()
        saved = mock_save.call_args[0][0]
        self.assertEqual(saved["Which to Farm"], "Forgery Challenge")
        self.assertEqual(saved["Which Forgery Challenge to Farm"], 3)


# ============================================================
# 原神 GenshinConfig
# ============================================================


class TestGenshinConfig(unittest.TestCase):
    def test_init_attributes(self):
        template = {"DomainName": "测试", "PartyName": "队伍1"}
        with (
            patch.object(GenshinConfig, "_init_config"),
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=json.dumps(template))),
        ):
            cfg = GenshinConfig()
        self.assertEqual(cfg.display_name, "原神")
        self.assertEqual(cfg._script_name, "BetterGI")
        self.assertEqual(cfg._task_key, "DomainName")

    def test_init_config_aligned_no_save(self):
        """config 与模板对齐（含模板外的自定义 key）时不保存"""
        template = {
            "TaskEnabledList": {"领取邮件": True},
            "CompletionAction": "关闭游戏",
        }
        config = {
            "TaskEnabledList": {"领取邮件": True},
            "CompletionAction": "关闭游戏",
            "PartyName": "队伍B",  # 模板外的用户自定义 key，不应被改动
        }
        with (
            patch.object(GenshinConfig, "_load", return_value=config),
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=json.dumps(template))),
            patch.object(GenshinConfig, "_save") as mock_save,
        ):
            GenshinConfig()
        mock_save.assert_not_called()

    def test_init_config_misaligned_saves(self):
        """config 与模板不对齐时用模板值回填并保存"""
        template = {
            "TaskEnabledList": {"领取邮件": True},
            "CompletionAction": "关闭游戏",
        }
        config = {
            "TaskEnabledList": {"领取邮件": False},
            "CompletionAction": "不操作",
        }
        with (
            patch.object(GenshinConfig, "_load", return_value=config),
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=json.dumps(template))),
            patch.object(GenshinConfig, "_save") as mock_save,
        ):
            GenshinConfig()
        mock_save.assert_called_once_with(template)

    def test_update_task_uses_dungeon_name_directly(self):
        """原神 _task_map 为空，直接用 dungeon_name"""
        with (
            patch.object(GenshinConfig, "_init_config"),
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data="{}")),
        ):
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
        self.assertEqual(cfg._script_name, "ok-ef")
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
        with (
            patch.object(cfg, "_load", return_value=config),
            patch.object(cfg, "_save") as mock_save,
        ):
            cfg.set_dungeon("新本")
        mock_save.assert_called_once_with({"体力本": "新本"})

    def test_set_dungeon_with_sequence_writes_second_level(self):
        """终末地副本按「类型 → 副本」两级组织（假一级目录）：写入的是二级副本名。"""
        cfg = EndfieldConfig()
        config = {"体力本": "旧本"}
        with (
            patch.object(cfg, "_load", return_value=config),
            patch.object(cfg, "_save") as mock_save,
        ):
            cfg.set_dungeon("能量淤积点", sequence="枢纽区")
        mock_save.assert_called_once_with({"体力本": "枢纽区"})


# ============================================================
# 绝区零 ZenlessZoneZeroConfig
# ============================================================


class TestZenlessZoneZeroConfig(unittest.TestCase):
    def test_init_attributes(self):
        template = {"plan_list": [], "double_reward": False}
        with (
            patch.object(ZenlessZoneZeroConfig, "_load", return_value=template),
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=yaml.dump(template))),
            patch.object(ZenlessZoneZeroConfig, "_save"),
        ):
            cfg = ZenlessZoneZeroConfig()
        self.assertEqual(cfg.display_name, "绝区零")
        self.assertEqual(cfg._script_name, "OneDragon-Launcher")
        self.assertEqual(cfg._task_key, "")

    def test_init_config_aligned_no_save(self):
        """config 与模板对齐时不 save"""
        template = {
            "plan_list": [{"tab_name": "A", "category_name": "x"}],
            "double_reward": False,
        }
        config = {
            "plan_list": [{"tab_name": "A", "category_name": "x", "extra": 1}],
            "double_reward": False,
        }
        with (
            patch.object(ZenlessZoneZeroConfig, "_load", return_value=config),
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=yaml.dump(template))),
            patch.object(ZenlessZoneZeroConfig, "_save") as mock_save,
        ):
            ZenlessZoneZeroConfig()
        mock_save.assert_not_called()

    def test_init_config_misaligned_saves(self):
        """config 与模板不对齐时 save 模板"""
        template = {
            "plan_list": [{"tab_name": "A", "category_name": "x"}],
            "double_reward": True,
        }
        config = {
            "plan_list": [{"tab_name": "B", "category_name": "y"}],
            "double_reward": False,
        }
        with (
            patch.object(ZenlessZoneZeroConfig, "_load", return_value=config),
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=yaml.dump(template))),
            patch.object(ZenlessZoneZeroConfig, "_save") as mock_save,
        ):
            ZenlessZoneZeroConfig()
        mock_save.assert_called_once_with(template)

    def test_set_dungeon_only_prints(self):
        """set_dungeon 应只 print 不做修改"""
        with (
            patch.object(ZenlessZoneZeroConfig, "_init_config"),
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data="{}")),
        ):
            cfg = ZenlessZoneZeroConfig()
        with (
            patch.object(cfg, "_load") as mock_load,
            patch.object(cfg, "_save") as mock_save,
        ):
            cfg.set_dungeon("任何副本", "任何序列")
        mock_load.assert_not_called()
        mock_save.assert_not_called()

    # ---- _is_aligned 单元测试 ----

    def _make_cfg(self):
        """创建一个跳过 _init_config 的 ZenlessZoneZeroConfig 实例"""
        with patch.object(ZenlessZoneZeroConfig, "_init_config"):
            return ZenlessZoneZeroConfig()

    def test_is_aligned_identical(self):
        template = {
            "plan_list": [{"tab_name": "A", "category_name": "x"}],
            "double_reward": False,
        }
        config = {
            "plan_list": [{"tab_name": "A", "category_name": "x"}],
            "double_reward": False,
        }
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
        config = {
            "plan_list": [
                {"tab_name": "A", "category_name": "x"},
                {"tab_name": "B", "category_name": "y"},
            ]
        }
        cfg = self._make_cfg()
        self.assertTrue(cfg._is_aligned(config, template))

    def test_is_aligned_order_mismatch_returns_false(self):
        """plan_list 顺序不一致应返回 False"""
        template = {
            "plan_list": [
                {"tab_name": "A", "category_name": "x"},
                {"tab_name": "B", "category_name": "y"},
            ]
        }
        config = {
            "plan_list": [
                {"tab_name": "B", "category_name": "y"},
                {"tab_name": "A", "category_name": "x"},
            ]
        }
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
        template = {
            "plan_list": [
                {"tab_name": "A", "category_name": "x"},
                {"tab_name": "B", "category_name": "y"},
            ]
        }
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
        with patch.object(StarRailConfig, "_init_config"):
            cfg = StarRailConfig()
            self.assertEqual(cfg.display_name, "崩铁")
            self.assertEqual(cfg._script_name, "March7th-Assistant")
            self.assertEqual(cfg._task_key, "instance_type")
            self.assertEqual(cfg._task_map, {})

    def test_update_task_direct_assign(self):
        with patch.object(StarRailConfig, "_init_config"):
            cfg = StarRailConfig()
            config = {"instance_type": "旧本"}
            changed = cfg._update_task(config, "新本")
            self.assertTrue(changed)
            self.assertEqual(config["instance_type"], "新本")

    def test_set_dungeon_changed_saves(self):
        with patch.object(StarRailConfig, "_init_config"):
            cfg = StarRailConfig()
            config = {"instance_type": "旧本"}
            with (
                patch.object(cfg, "_load", return_value=config),
                patch.object(cfg, "_save") as mock_save,
            ):
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
        self.assertEqual(self.cfg._script_name, "ok-nte")
        self.assertEqual(self.cfg._task_key, "任务类型")
        self.assertIn("空幕", self.cfg._seq_key_map)
        self.assertEqual(self.cfg._seq_key_map["空幕"], "空幕序号")
        self.assertEqual(
            self.cfg._config_rel_path,
            "data/apps/ok-nte/working/configs/DailyRoutineTaskConfigs.json",
        )
        self.assertEqual(self.cfg._daily_section, "daily_anomaly")

    def test_update_sequence_changes_value(self):
        config = {"daily_anomaly": {"空幕序号": 1}}
        changed = self.cfg._update_sequence(config, "空幕", 3)
        self.assertTrue(changed)
        self.assertEqual(config["daily_anomaly"]["空幕序号"], 3)

    def test_update_sequence_no_change(self):
        config = {"daily_anomaly": {"空幕序号": 2}}
        changed = self.cfg._update_sequence(config, "空幕", 2)
        self.assertFalse(changed)

    def test_update_sequence_none_raises(self):
        """异环要求 sequence 不能为 None"""
        config = {"daily_anomaly": {"空幕序号": 1}}
        with self.assertRaises(AssertionError):
            self.cfg._update_sequence(config, "空幕", None)

    def test_update_sequence_unknown_dungeon_raises(self):
        config = {"daily_anomaly": {"未知序号": 1}}
        with self.assertRaises(AssertionError):
            self.cfg._update_sequence(config, "不存在", "1")

    def test_update_sequence_all_mapped_dungeons(self):
        """测试 _seq_key_map 中所有副本都能正确更新"""
        for dungeon_name, seq_key in self.cfg._seq_key_map.items():
            config = {"daily_anomaly": {seq_key: 0}}
            changed = self.cfg._update_sequence(config, dungeon_name, 5)
            self.assertTrue(changed, f"{dungeon_name} 未正确更新")
            self.assertEqual(config["daily_anomaly"][seq_key], 5)

    def test_set_dungeon_with_sequence_saves(self):
        config = {"daily_anomaly": {"任务类型": "空幕", "空幕序号": 1}}
        with (
            patch.object(self.cfg, "_load", return_value=config),
            patch.object(self.cfg, "_save") as mock_save,
        ):
            self.cfg.set_dungeon("空幕", 3)
        mock_save.assert_called_once()
        saved = mock_save.call_args[0][0]
        self.assertEqual(saved["daily_anomaly"]["空幕序号"], 3)

    def test_update_task_writes_dungeon_name(self):
        """任务类型写入 daily_anomaly 子对象（值即中文副本名）"""
        config = {"daily_anomaly": {"任务类型": "空幕"}}
        changed = self.cfg._update_task(config, "异能升级材料")
        self.assertTrue(changed)
        self.assertEqual(config["daily_anomaly"]["任务类型"], "异能升级材料")

    def test_missing_daily_section_raises(self):
        """顶层缺 daily_anomaly（旧版 DailyTask.json 结构）→ assert"""
        config = {"任务类型": "空幕"}
        with self.assertRaises(AssertionError):
            self.cfg._update_task(config, "空幕")


# ============================================================
# 明日方舟 ArknightsConfig（粥）
# ============================================================


class TestArknightsConfig(unittest.TestCase):
    """测试粥的 _is_aligned / _init_config / set_dungeon"""

    def _make_cfg(self):
        """创建一个跳过 _init_config 的 ArknightsConfig 实例"""
        with patch.object(ArknightsConfig, "_init_config"):
            cfg = ArknightsConfig()
            cfg._task_map = {
                "剿灭": {"index": 1, "stage": "Annihilation"},
                "红票": {"index": 2, "stage": "AP-5"},
                "经验": {"index": 3, "stage": "LS-6"},
                "龙门币": {"index": 4, "stage": "CE-6"},
                "土": {"index": 5, "stage": "1-7"},
            }
            return cfg

    def test_init_attributes(self):
        cfg = self._make_cfg()
        self.assertEqual(cfg.display_name, "粥")
        self.assertEqual(cfg._script_name, "MAA")
        self.assertIn("剿灭", cfg._task_map)
        self.assertEqual(cfg._task_map["剿灭"]["index"], 1)
        self.assertEqual(cfg._task_map["土"]["index"], 5)

    # ---- _is_aligned ----

    def test_is_aligned_identical(self):
        cfg = self._make_cfg()
        template = {
            "Configurations": {
                "Default": {
                    "TaskQueue": [
                        {"Name": "开始唤醒", "$type": "StartUpTask"},
                        {
                            "Name": "剿灭",
                            "$type": "FightTask",
                            "StagePlan": ["Annihilation"],
                        },
                    ]
                }
            }
        }
        config = {
            "Configurations": {
                "Default": {
                    "TaskQueue": [
                        {"Name": "开始唤醒", "$type": "StartUpTask", "ExtraKey": 1},
                        {
                            "Name": "剿灭",
                            "$type": "FightTask",
                            "StagePlan": ["Annihilation"],
                            "IsEnable": True,
                        },
                    ]
                }
            }
        }
        self.assertTrue(cfg._is_aligned(config, template))

    def test_is_aligned_name_mismatch(self):
        cfg = self._make_cfg()
        template = {
            "Configurations": {
                "Default": {"TaskQueue": [{"Name": "剿灭", "$type": "FightTask"}]}
            }
        }
        config = {
            "Configurations": {
                "Default": {"TaskQueue": [{"Name": "红票", "$type": "FightTask"}]}
            }
        }
        self.assertFalse(cfg._is_aligned(config, template))

    def test_is_aligned_type_mismatch(self):
        cfg = self._make_cfg()
        template = {
            "Configurations": {
                "Default": {"TaskQueue": [{"Name": "剿灭", "$type": "FightTask"}]}
            }
        }
        config = {
            "Configurations": {
                "Default": {"TaskQueue": [{"Name": "剿灭", "$type": "StartUpTask"}]}
            }
        }
        self.assertFalse(cfg._is_aligned(config, template))

    def test_is_aligned_stageplan_mismatch(self):
        cfg = self._make_cfg()
        template = {
            "Configurations": {
                "Default": {
                    "TaskQueue": [
                        {
                            "Name": "剿灭",
                            "$type": "FightTask",
                            "StagePlan": ["Annihilation"],
                        }
                    ]
                }
            }
        }
        config = {
            "Configurations": {
                "Default": {
                    "TaskQueue": [
                        {"Name": "剿灭", "$type": "FightTask", "StagePlan": ["AP-5"]}
                    ]
                }
            }
        }
        self.assertFalse(cfg._is_aligned(config, template))

    def test_is_aligned_cur_shorter_returns_false(self):
        cfg = self._make_cfg()
        template = {
            "Configurations": {
                "Default": {
                    "TaskQueue": [
                        {"Name": "A", "$type": "X"},
                        {"Name": "B", "$type": "Y"},
                    ]
                }
            }
        }
        config = {
            "Configurations": {"Default": {"TaskQueue": [{"Name": "A", "$type": "X"}]}}
        }
        self.assertFalse(cfg._is_aligned(config, template))

    def test_is_aligned_cur_longer_ok(self):
        """cur 比 template 长是可以的"""
        cfg = self._make_cfg()
        template = {
            "Configurations": {"Default": {"TaskQueue": [{"Name": "A", "$type": "X"}]}}
        }
        config = {
            "Configurations": {
                "Default": {
                    "TaskQueue": [
                        {"Name": "A", "$type": "X"},
                        {"Name": "B", "$type": "Y"},
                    ]
                }
            }
        }
        self.assertTrue(cfg._is_aligned(config, template))

    def test_is_aligned_non_fight_task_skips_stageplan(self):
        """非 FightTask 不检查 StagePlan（因为模板中没写 StagePlan）"""
        cfg = self._make_cfg()
        template = {
            "Configurations": {
                "Default": {"TaskQueue": [{"Name": "自动公招", "$type": "RecruitTask"}]}
            }
        }
        config = {
            "Configurations": {
                "Default": {"TaskQueue": [{"Name": "自动公招", "$type": "RecruitTask"}]}
            }
        }
        self.assertTrue(cfg._is_aligned(config, template))

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
        template = {"Configurations": {"Default": {"TaskQueue": template_queue}}}

        config = {"Configurations": {"Default": {"TaskQueue": template_queue}}}
        with (
            patch.object(cfg, "_load", return_value=config),
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=json.dumps(template))),
            patch.object(cfg, "_save") as mock_save,
        ):
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
        template = {"Configurations": {"Default": {"TaskQueue": template_queue}}}
        cur_queue = [{"Name": "wrong", "$type": "Unknown"}]
        config = {"Configurations": {"Default": {"TaskQueue": cur_queue}}}
        with (
            patch.object(cfg, "_load", return_value=config),
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=json.dumps(template))),
            patch.object(cfg, "_save") as mock_save,
        ):
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
                "Name": name,
                "$type": "FightTask",
                "StagePlan": [info["stage"]],
                "IsEnable": True,
            }
        queue[6] = {"Name": "自动公招", "$type": "RecruitTask"}
        queue[7] = {"Name": "基建换班", "$type": "InfrastTask"}
        queue[8] = {"Name": "信用收支", "$type": "MallTask"}
        queue[9] = {"Name": "领取奖励", "$type": "AwardTask"}

        config = {"Configurations": {"Default": {"TaskQueue": queue}}}
        with (
            patch.object(cfg, "_load", return_value=config),
            patch.object(cfg, "_save") as mock_save,
        ):
            cfg.set_dungeon("红票")

        mock_save.assert_called_once()
        saved_queue = mock_save.call_args[0][0]["Configurations"]["Default"][
            "TaskQueue"
        ]
        # 红票启用
        self.assertTrue(saved_queue[2]["IsEnable"])
        # 土启用（清理剩余体力）
        self.assertTrue(saved_queue[5]["IsEnable"])
        # 剿灭始终启用（周常）
        self.assertTrue(saved_queue[1]["IsEnable"])  # 剿灭
        # 其他副本禁用
        self.assertFalse(saved_queue[3]["IsEnable"])  # 经验
        self.assertFalse(saved_queue[4]["IsEnable"])  # 龙门币

    def test_set_dungeon_unknown_raises(self):
        cfg = self._make_cfg()
        config = {"Configurations": {"Default": {"TaskQueue": []}}}
        with (
            patch.object(cfg, "_load", return_value=config),
            self.assertRaises(AssertionError),
        ):
            cfg.set_dungeon("不存在")

    def test_set_dungeon_elimination_only_enables_elimination_and_土(self):
        """选择剿灭时，只启用剿灭和土，其他副本禁用"""
        cfg = self._make_cfg()
        queue = [None] * 10
        queue[0] = {"Name": "开始唤醒", "$type": "StartUpTask"}
        for name, info in cfg._task_map.items():
            queue[info["index"]] = {
                "Name": name,
                "$type": "FightTask",
                "StagePlan": [info["stage"]],
                "IsEnable": True,
            }
        queue[6] = {"Name": "自动公招", "$type": "RecruitTask"}
        queue[7] = {"Name": "基建换班", "$type": "InfrastTask"}
        queue[8] = {"Name": "信用收支", "$type": "MallTask"}
        queue[9] = {"Name": "领取奖励", "$type": "AwardTask"}

        config = {"Configurations": {"Default": {"TaskQueue": queue}}}
        with (
            patch.object(cfg, "_load", return_value=config),
            patch.object(cfg, "_save") as mock_save,
        ):
            cfg.set_dungeon("剿灭")

        mock_save.assert_called_once()
        saved_queue = mock_save.call_args[0][0]["Configurations"]["Default"][
            "TaskQueue"
        ]
        # 剿灭启用
        self.assertTrue(saved_queue[1]["IsEnable"])  # 剿灭
        # 土启用（清理剩余体力）
        self.assertTrue(saved_queue[5]["IsEnable"])  # 土
        # 其他副本禁用
        self.assertFalse(saved_queue[2]["IsEnable"])  # 红票
        self.assertFalse(saved_queue[3]["IsEnable"])  # 经验
        self.assertFalse(saved_queue[4]["IsEnable"])  # 龙门币

    def test_set_dungeon_name_mismatch_raises(self):
        """TaskQueue 中 Name 不匹配应 assert"""
        cfg = self._make_cfg()
        queue = [None] * 10
        queue[1] = {
            "Name": "wrong",
            "$type": "FightTask",
            "StagePlan": ["Annihilation"],
            "IsEnable": True,
        }
        config = {"Configurations": {"Default": {"TaskQueue": queue}}}
        with (
            patch.object(cfg, "_load", return_value=config),
            self.assertRaises(AssertionError),
        ):
            cfg.set_dungeon("剿灭")


# ============================================================
# get_game_exe_path（打开游戏只读查询）
# ============================================================


class TestGetGameExePath(unittest.TestCase):
    """测试 ScriptConfig.get_game_exe_path：从各脚本游戏配置中提取游戏路径。"""

    def test_unadapted_base_returns_none(self):
        """基类未适配（_game_path_keys 为空）→ None，不触发任何读取"""
        with patch("src.config.set_config.load_game_config") as mock_load:
            got = ScriptConfig.get_game_exe_path("任意")
        self.assertIsNone(got)
        mock_load.assert_not_called()

    def test_ok_series_pc_full_path(self):
        """OK 系（ok-ww/ok-ef/ok-nte）读取 devices.json 的 pc_full_path"""
        cases = (
            (WutheringWavesConfig, "ok-ww"),
            (EndfieldConfig, "ok-ef"),
            (NTEConfig, "ok-nte"),
        )
        for cls, script_name in cases:
            with patch(
                "src.config.set_config.load_game_config",
                return_value={
                    "preferred": "pc_1",
                    "pc_full_path": "D:\\Game\\game.exe",
                },
            ):
                got = cls.get_game_exe_path(script_name)
            self.assertEqual(got, "D:\\Game\\game.exe")

    def test_genshin_nested_install_path(self):
        """原神（BetterGI）读取 config.json 的 genshinStartConfig.installPath（嵌套）"""
        with patch(
            "src.config.set_config.load_game_config",
            return_value={
                "genshinStartConfig": {
                    "installPath": "D:\\Genshin\\YuanShen.exe",
                }
            },
        ):
            got = GenshinConfig.get_game_exe_path("BetterGI")
        self.assertEqual(got, "D:\\Genshin\\YuanShen.exe")

    def test_game_path_top_level(self):
        """绝区零/崩铁读取顶层 game_path"""
        cases = (
            (ZenlessZoneZeroConfig, "OneDragon-Launcher"),
            (StarRailConfig, "March7th-Assistant"),
        )
        for cls, script_name in cases:
            with patch(
                "src.config.set_config.load_game_config",
                return_value={"game_path": "D:\\Game\\game.exe"},
            ):
                got = cls.get_game_exe_path(script_name)
            self.assertEqual(got, "D:\\Game\\game.exe")

    def test_arknights_nested_emulator_path(self):
        """粥（MAA）读取 gui.new.json 的 Configurations.Default.Gui.StartUpSettings.EmulatorPath（多级嵌套）"""
        with patch(
            "src.config.set_config.load_game_config",
            return_value={
                "Configurations": {
                    "Default": {
                        "Gui": {
                            "StartUpSettings": {
                                "EmulatorPath": "C:\\MuMu\\#0 MuMu安卓设备.lnk",
                            }
                        }
                    }
                }
            },
        ):
            got = ArknightsConfig.get_game_exe_path("MAA")
        self.assertEqual(got, "C:\\MuMu\\#0 MuMu安卓设备.lnk")

    def test_missing_config_returns_none(self):
        """游戏配置文件缺失（load_game_config 返回 None）→ None"""
        with patch("src.config.set_config.load_game_config", return_value=None):
            got = WutheringWavesConfig.get_game_exe_path("ok-ww")
        self.assertIsNone(got)

    def test_missing_field_returns_none(self):
        """配置中缺字段 → None"""
        with patch(
            "src.config.set_config.load_game_config",
            return_value={"other": "x"},
        ):
            got = WutheringWavesConfig.get_game_exe_path("ok-ww")
        self.assertIsNone(got)

    def test_empty_value_returns_none(self):
        """字段值为空字符串 → None"""
        with patch(
            "src.config.set_config.load_game_config",
            return_value={"pc_full_path": ""},
        ):
            got = WutheringWavesConfig.get_game_exe_path("ok-ww")
        self.assertIsNone(got)


class TestGetGameExePathFacade(unittest.TestCase):
    """测试外观接口 get_game_exe_path 的分发逻辑"""

    def test_unknown_process_returns_none(self):
        """未注册（自定义）进程 → None"""
        got = set_config.get_game_exe_path("不存在")
        self.assertIsNone(got)

    def test_known_process_dispatches(self):
        """已注册进程 → 走对应子类"""
        with patch(
            "src.config.set_config.load_game_config",
            return_value={"pc_full_path": "D:\\Game\\game.exe"},
        ):
            got = set_config.get_game_exe_path("ok-ww")
        self.assertEqual(got, "D:\\Game\\game.exe")


class TestSupportsWeekly(unittest.TestCase):
    """测试周常（周几以后开始执行）支持查询：supports_weekly"""

    def test_unknown_process_returns_false(self):
        """未注册（自定义）进程 → False"""
        self.assertFalse(set_config.supports_weekly("不存在"))

    def test_weekly_supported_scripts(self):
        """已适配周常的脚本：崩铁（货币战争）/ 鸣潮（每周花园）/ 绝区零（lost_void）"""
        for name in (
            "March7th-Assistant",
            "ok-ww",
            "OneDragon-Launcher",
        ):
            self.assertTrue(set_config.supports_weekly(name), f"{name} 应支持周常")

    def test_other_scripts_default_false(self):
        """其余脚本未适配周常 → False"""
        for name in set_config._CONFIGS:
            if name in ("March7th-Assistant", "ok-ww", "OneDragon-Launcher"):
                continue
            self.assertFalse(set_config.supports_weekly(name), f"{name} 不应支持周常")

    def test_dispatches_to_subclass_flag(self):
        """已注册脚本按子类 _weekly_task_name 非空返回"""
        cls = MagicMock()
        cls._weekly_task_name = "task"
        with patch.dict("src.config.set_config._CONFIGS", {"ok-ww": cls}):
            self.assertTrue(set_config.supports_weekly("ok-ww"))
        cls._weekly_task_name = ""
        with patch.dict("src.config.set_config._CONFIGS", {"ok-ww": cls}):
            self.assertFalse(set_config.supports_weekly("ok-ww"))


class TestSetWeekly(unittest.TestCase):
    """测试三个已适配脚本的 set_weekly（按周几起 start_day 判断写入）"""

    # ---- 基类：start_day 校验与 _write_weekly 钩子 ----

    def test_base_weekly_unsupported_raises(self):
        """未适配子类调用 set_weekly → assert（未声明 _weekly_task_name）"""
        cfg = ScriptConfig()
        cfg.display_name = "测试"
        with self.assertRaises(AssertionError):
            cfg.set_weekly(4)

    def test_invalid_start_day_raises(self):
        """start_day 越界（0 / 8）→ assert"""
        with patch.object(StarRailConfig, "_init_config"):
            cfg = StarRailConfig()
        for bad in (0, 8):
            with self.subTest(bad=bad), self.assertRaises(AssertionError):
                cfg.set_weekly(bad)

    def test_set_weekly_today_reached_enables(self):
        """今天周四（get_week_num=3），start_day=4 → _write_weekly(True)"""
        with patch.object(StarRailConfig, "_init_config"):
            cfg = StarRailConfig()
        with (
            patch("src.utils_weekly.get_week_num", return_value=3),
            patch.object(cfg, "_write_weekly") as mock_write,
        ):
            cfg.set_weekly(4)
        mock_write.assert_called_once_with(True)

    def test_set_weekly_today_before_disables(self):
        """今天周二（get_week_num=1），start_day=4 → _write_weekly(False)"""
        with patch.object(StarRailConfig, "_init_config"):
            cfg = StarRailConfig()
        with (
            patch("src.utils_weekly.get_week_num", return_value=1),
            patch.object(cfg, "_write_weekly") as mock_write,
        ):
            cfg.set_weekly(4)
        mock_write.assert_called_once_with(False)

    def test_set_weekly_enabled_false_short_circuits(self):
        """用户已拒绝（enabled=False）→ 直接跳过，不调 _write_weekly（同 set_dungeon）"""
        with patch.object(StarRailConfig, "_init_config"):
            cfg = StarRailConfig()
        cfg.enabled = False
        with patch.object(cfg, "_write_weekly") as mock_write:
            cfg.set_weekly(4)
        mock_write.assert_not_called()

    # ---- 崩铁：currencywars_enable ----

    def test_star_rail_enable_writes_true(self):
        """崩铁启用周常（今天已到起始日）→ currencywars_enable=True"""
        with patch.object(StarRailConfig, "_init_config"):
            cfg = StarRailConfig()
        config = {"currencywars_enable": False}
        with (
            patch("src.utils_weekly.get_week_num", return_value=3),
            patch.object(cfg, "_load", return_value=config),
            patch.object(cfg, "_save") as mock_save,
        ):
            cfg.set_weekly(4)
        self.assertTrue(config["currencywars_enable"])
        mock_save.assert_called_once()

    def test_star_rail_disable_writes_false(self):
        """崩铁停用周常（今天未到起始日）→ currencywars_enable=False"""
        with patch.object(StarRailConfig, "_init_config"):
            cfg = StarRailConfig()
        config = {"currencywars_enable": True}
        with (
            patch("src.utils_weekly.get_week_num", return_value=1),
            patch.object(cfg, "_load", return_value=config),
            patch.object(cfg, "_save") as mock_save,
        ):
            cfg.set_weekly(4)
        self.assertFalse(config["currencywars_enable"])
        mock_save.assert_called_once()

    # ---- 鸣潮：Additional Tasks 列表增删 Check Weekly Garden ----

    def test_ww_enable_appends_weekly_task(self):
        """鸣潮启用周常（今天已到起始日）→ Additional Tasks 列表追加 Check Weekly Garden"""
        cfg = WutheringWavesConfig()
        config = {
            "Additional Tasks to Run After Daily Task": [
                "Merge Echo If discarded > 1000",
            ]
        }
        with (
            patch("src.utils_weekly.get_week_num", return_value=3),
            patch.object(cfg, "_load", return_value=config),
            patch.object(cfg, "_save") as mock_save,
        ):
            cfg.set_weekly(4)
        self.assertIn(
            "Check Weekly Garden",
            config["Additional Tasks to Run After Daily Task"],
        )
        mock_save.assert_called_once()

    def test_ww_disable_removes_weekly_task(self):
        """鸣潮停用周常（今天未到起始日）→ Additional Tasks 列表移除 Check Weekly Garden"""
        cfg = WutheringWavesConfig()
        config = {
            "Additional Tasks to Run After Daily Task": [
                "Check Weekly Garden",
                "Merge Echo If discarded > 1000",
            ]
        }
        with (
            patch("src.utils_weekly.get_week_num", return_value=1),
            patch.object(cfg, "_load", return_value=config),
            patch.object(cfg, "_save") as mock_save,
        ):
            cfg.set_weekly(4)
        self.assertNotIn(
            "Check Weekly Garden",
            config["Additional Tasks to Run After Daily Task"],
        )
        mock_save.assert_called_once()

    def test_ww_no_change_skips_save(self):
        """鸣潮状态无变化（已启用再启用）→ 不落盘"""
        cfg = WutheringWavesConfig()
        config = {
            "Additional Tasks to Run After Daily Task": ["Check Weekly Garden"],
        }
        with (
            patch("src.utils_weekly.get_week_num", return_value=3),
            patch.object(cfg, "_load", return_value=config),
            patch.object(cfg, "_save") as mock_save,
        ):
            cfg.set_weekly(4)
        mock_save.assert_not_called()

    def test_ww_missing_tasks_key_raises(self):
        """鸣潮 config 缺 Additional Tasks 字段 → assert"""
        cfg = WutheringWavesConfig()
        with (
            patch("src.utils_weekly.get_week_num", return_value=3),
            patch.object(cfg, "_load", return_value={}),
            self.assertRaises(AssertionError),
        ):
            cfg.set_weekly(4)

    # ---- 绝区零：_group.yml 的 lost_void.enabled ----

    def _make_zzz_cfg(self):
        with patch.object(ZenlessZoneZeroConfig, "_init_config"):
            return ZenlessZoneZeroConfig()

    def test_zzz_enable_writes_lost_void_true(self):
        """绝区零启用周常（今天已到起始日）→ _group.yml 的 lost_void.enabled=True"""
        cfg = self._make_zzz_cfg()
        config = {
            "app_list": [
                {"app_id": "notorious_hunt", "enabled": True},
                {"app_id": "lost_void", "enabled": False},
            ]
        }
        with (
            patch("src.utils_weekly.get_week_num", return_value=3),
            patch("src.config.set_config.load_config", return_value=config),
            patch("src.config.set_config.save_config") as mock_save,
        ):
            cfg.set_weekly(4)
        lost = next(a for a in config["app_list"] if a["app_id"] == "lost_void")
        self.assertTrue(lost["enabled"])
        mock_save.assert_called_once()

    def test_zzz_disable_writes_lost_void_false(self):
        """绝区零停用周常（今天未到起始日）→ lost_void.enabled=False"""
        cfg = self._make_zzz_cfg()
        config = {
            "app_list": [
                {"app_id": "lost_void", "enabled": True},
            ]
        }
        with (
            patch("src.utils_weekly.get_week_num", return_value=1),
            patch("src.config.set_config.load_config", return_value=config),
            patch("src.config.set_config.save_config") as mock_save,
        ):
            cfg.set_weekly(4)
        lost = next(a for a in config["app_list"] if a["app_id"] == "lost_void")
        self.assertFalse(lost["enabled"])
        mock_save.assert_called_once()

    def test_zzz_missing_app_id_raises(self):
        """app_list 缺 lost_void → assert"""
        cfg = self._make_zzz_cfg()
        config = {"app_list": [{"app_id": "other", "enabled": True}]}
        with (
            patch("src.utils_weekly.get_week_num", return_value=3),
            patch("src.config.set_config.load_config", return_value=config),
            self.assertRaises(AssertionError),
        ):
            cfg.set_weekly(4)


class TestSetConfigFacade(unittest.TestCase):
    """测试外观接口 set_config() 的分发逻辑"""

    def test_skip_when_dungeon_name_none(self):
        """dungeon_name 为 None 时直接返回，不创建实例"""
        mock_instance = MagicMock()
        mock_cls = MagicMock(return_value=mock_instance)
        with patch.dict("src.config.set_config._CONFIGS", {"ok-ww": mock_cls}):
            set_config.set_config("ok-ww", None, None)
        mock_cls.assert_not_called()
        mock_instance.set_dungeon.assert_not_called()

    def test_skip_when_dungeon_name_empty(self):
        set_config.set_config("ok-ww", "", None)

    def test_skip_when_dungeon_name_unselected(self):
        set_config.set_config("ok-ww", "未选择", None)

    def test_unknown_process_skips_gracefully(self):
        """未注册（自定义）进程即使带副本也优雅跳过，不报错、不实例化任何子类"""
        # 不应抛异常
        set_config.set_config("不存在", "副本", "序列")

    def test_unknown_process_does_not_touch_registry(self):
        """未注册进程不会命中注册表中的任何子类"""
        mock_instance = MagicMock()
        mock_cls = MagicMock(return_value=mock_instance)
        with patch.dict("src.config.set_config._CONFIGS", {"ok-ww": mock_cls}):
            set_config.set_config("自定义脚本", "副本", None)
        mock_cls.assert_not_called()
        mock_instance.set_dungeon.assert_not_called()

    def test_dispatches_to_correct_subclass(self):
        """验证 set_config 正确分发到对应子类"""
        mock_instance = MagicMock()
        mock_cls = MagicMock(return_value=mock_instance)
        with patch.dict("src.config.set_config._CONFIGS", {"ok-ww": mock_cls}):
            set_config.set_config("ok-ww", "无音区", "1")
        mock_cls.assert_called_once()
        mock_instance.set_dungeon.assert_called_once_with("无音区", "1")
