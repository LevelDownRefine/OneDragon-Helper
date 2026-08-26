"""
测试 set_config.py 中各 ScriptConfig 子类的行为。

覆盖每个子类的 _update_task（含二级序列）/ set_dungeon / _init_config / _is_aligned 等方法。
所有文件 I/O 均通过 mock 隔离，不依赖真实 config 文件。
"""

import json
import os
import unittest
from unittest.mock import MagicMock, mock_open, patch

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
from src.utils_yaml import dump_yaml_str

# ============================================================
# 基类 ScriptConfig
# ============================================================


class TestScriptConfigBase(unittest.TestCase):
    """测试基类 _update_task / set_dungeon 的默认行为"""

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

    def test_update_task_rejects_sequence(self):
        """基类默认 _update_task 不接受非 None 的 sequence"""
        cfg = ScriptConfig()
        cfg.display_name = "测试"
        with self.assertRaises(AssertionError):
            cfg._update_task({}, "副本", "序列")

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
        config = {"Which to Farm": "old", "Which Tacet Suppression to Farm": 1}
        changed = self.cfg._update_task(config, "无音区", 3)
        self.assertTrue(changed)
        self.assertEqual(config["Which to Farm"], "Tacet Suppression")

    # ---- _update_task: 模拟领域 ----

    def test_update_sequence_simulation(self):
        config = {"Which to Farm": "Simulation Challenge", "Material Selection": "old"}
        changed = self.cfg._update_task(config, "模拟领域", "共鸣者经验")
        self.assertTrue(changed)
        self.assertEqual(config["Material Selection"], "Resonator EXP")

    def test_update_sequence_simulation_no_change(self):
        config = {
            "Which to Farm": "Simulation Challenge",
            "Material Selection": "Weapon EXP",
        }
        changed = self.cfg._update_task(config, "模拟领域", "武器经验")
        self.assertFalse(changed)

    def test_update_sequence_simulation_unknown_raises(self):
        config = {"Which to Farm": "Simulation Challenge", "Material Selection": "old"}
        with self.assertRaises(AssertionError):
            self.cfg._update_task(config, "模拟领域", "不存在")

    # ---- _update_task: 无音区 ----

    def test_update_sequence_tacet(self):
        config = {
            "Which to Farm": "Tacet Suppression",
            "Which Tacet Suppression to Farm": 1,
        }
        changed = self.cfg._update_task(config, "无音区", 3)
        self.assertTrue(changed)
        self.assertEqual(config["Which Tacet Suppression to Farm"], 3)

    def test_update_sequence_tacet_no_change(self):
        config = {
            "Which to Farm": "Tacet Suppression",
            "Which Tacet Suppression to Farm": 2,
        }
        changed = self.cfg._update_task(config, "无音区", 2)
        self.assertFalse(changed)

    # ---- _update_task: 凝素领域 ----

    def test_update_sequence_forgery(self):
        config = {
            "Which to Farm": "Forgery Challenge",
            "Which Forgery Challenge to Farm": 1,
        }
        changed = self.cfg._update_task(config, "凝素领域", 4)
        self.assertTrue(changed)
        self.assertEqual(config["Which Forgery Challenge to Farm"], 4)

    def test_update_sequence_forgery_no_change(self):
        config = {
            "Which to Farm": "Forgery Challenge",
            "Which Forgery Challenge to Farm": 2,
        }
        changed = self.cfg._update_task(config, "凝素领域", 2)
        self.assertFalse(changed)

    # ---- _update_task: None ----

    def test_update_sequence_none_raises(self):
        config = {"Which to Farm": "Simulation Challenge"}
        with self.assertRaises(AssertionError):
            self.cfg._update_task(config, "模拟领域", None)

    # ---- _update_task: 未知副本类型 ----

    def test_update_sequence_unknown_dungeon_type_raises(self):
        config = {"Which to Farm": "Unknown Type"}
        with self.assertRaises(AssertionError):
            self.cfg._update_task(config, "未知", "1")

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
            cfg = GenshinConfig()
            cfg._init_config()
        mock_save.assert_not_called()

    def test_init_config_misaligned_saves(self):
        """config 与模板不对齐时，用模板值 reconcile（覆盖不一致、补缺失、保留多余）并保存"""
        template = {
            "TaskEnabledList": {"领取邮件": True},
            "CompletionAction": "关闭游戏",
        }
        config = {
            "TaskEnabledList": {"领取邮件": False},  # 不一致 → 覆盖为模板值
            "CompletionAction": "不操作",  # 不一致 → 覆盖为模板值
            "ExtraKey": 1,  # 模板无 → 保留
        }
        with (
            patch.object(GenshinConfig, "_load", return_value=config),
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=json.dumps(template))),
            patch.object(GenshinConfig, "_save") as mock_save,
        ):
            cfg = GenshinConfig()
            cfg._init_config()
        mock_save.assert_called_once()
        saved = mock_save.call_args[0][0]
        # 不一致项被模板值覆盖
        self.assertEqual(saved["TaskEnabledList"], {"领取邮件": True})
        self.assertEqual(saved["CompletionAction"], "关闭游戏")
        # 多余项保留
        self.assertEqual(saved["ExtraKey"], 1)

    def test_init_config_missing_config_is_noop(self):
        """config 缺失（首次写入前）时 _init_config 不崩溃、不写盘。"""
        with (
            patch.object(GenshinConfig, "_load", return_value=None),
            patch.object(GenshinConfig, "_load_template") as mock_template,
            patch.object(GenshinConfig, "_save") as mock_save,
        ):
            cfg = GenshinConfig()
            cfg._init_config()
        mock_template.assert_not_called()
        mock_save.assert_not_called()

    def test_update_task_uses_dungeon_name_directly(self):
        """原神 _task_map 为空，直接用 dungeon_name"""
        with (
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
        with patch.object(EndfieldConfig, "_init_config"):
            cfg = EndfieldConfig()
        self.assertEqual(cfg.display_name, "终末地")
        self.assertEqual(cfg._script_name, "ok-ef")
        self.assertEqual(cfg._task_key, "体力本")
        self.assertEqual(cfg._task_map, {})
        self.assertEqual(cfg._template_rel_path, "okef一条龙.json")

    def test_update_task_direct_assign(self):
        """终末地 _task_map 为空，直接用 dungeon_name"""
        with patch.object(EndfieldConfig, "_init_config"):
            cfg = EndfieldConfig()
        config = {"体力本": "旧本"}
        changed = cfg._update_task(config, "新本")
        self.assertTrue(changed)
        self.assertEqual(config["体力本"], "新本")

    def test_set_dungeon_no_sequence(self):
        with patch.object(EndfieldConfig, "_init_config"):
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
        with patch.object(EndfieldConfig, "_init_config"):
            cfg = EndfieldConfig()
        config = {"体力本": "旧本"}
        with (
            patch.object(cfg, "_load", return_value=config),
            patch.object(cfg, "_save") as mock_save,
        ):
            cfg.set_dungeon("能量淤积点", sequence="枢纽区")
        mock_save.assert_called_once_with({"体力本": "枢纽区"})

    def test_write_weekly_inverts_buy_only_flag(self):
        """周常（卖出物资）enabled 与游戏「只买不卖」反相：开→false，关→true。"""
        with patch.object(EndfieldConfig, "_init_config"):
            cfg = EndfieldConfig()
        for enabled, expected in ((True, False), (False, True)):
            config = {"只买不卖": not expected}
            with (
                patch.object(cfg, "_load", return_value=config),
                patch.object(cfg, "_save") as mock_save,
            ):
                cfg._write_weekly(enabled)
            self.assertEqual(config["只买不卖"], expected)
            mock_save.assert_called_once_with(config)

    def test_init_config_aligned_no_save(self):
        """config 与模板对齐（含模板外的自定义 key）时不保存"""
        template = {"购物白名单": ["精锻"], "是否买礼物": False}
        config = {
            "购物白名单": ["精锻"],
            "是否买礼物": False,
            "体力本": "旧本",  # 模板外的用户自定义 key
        }
        with (
            patch.object(EndfieldConfig, "_load", return_value=config),
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=json.dumps(template))),
            patch.object(EndfieldConfig, "_save") as mock_save,
        ):
            cfg = EndfieldConfig()
            cfg._init_config()
        mock_save.assert_not_called()

    def test_init_config_misaligned_saves(self):
        """config 与模板不对齐时，用模板值 reconcile（覆盖不一致、补缺失、保留多余）并保存"""
        template = {"购物白名单": ["精锻"], "是否买礼物": False}
        config = {
            "购物白名单": ["碎矿"],  # 不一致 → 覆盖为模板值
            "是否买礼物": True,  # 不一致 → 覆盖为模板值
            "ExtraKey": 1,  # 模板无 → 保留
        }
        with (
            patch.object(EndfieldConfig, "_load", return_value=config),
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=json.dumps(template))),
            patch.object(EndfieldConfig, "_save") as mock_save,
        ):
            cfg = EndfieldConfig()
            cfg._init_config()
        mock_save.assert_called_once()
        saved = mock_save.call_args[0][0]
        self.assertEqual(saved["购物白名单"], ["精锻"])
        self.assertEqual(saved["是否买礼物"], False)
        self.assertEqual(saved["ExtraKey"], 1)


# ============================================================
# 绝区零 ZenlessZoneZeroConfig
# ============================================================


class TestZenlessZoneZeroConfig(unittest.TestCase):
    def test_init_attributes(self):
        template = {"plan_list": [], "double_reward": False}
        with (
            patch.object(ZenlessZoneZeroConfig, "_load", return_value=template),
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=dump_yaml_str(template))),
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
            patch("builtins.open", mock_open(read_data=dump_yaml_str(template))),
            patch.object(ZenlessZoneZeroConfig, "_save") as mock_save,
        ):
            cfg = ZenlessZoneZeroConfig()
            cfg._init_config()
        mock_save.assert_not_called()

    def test_init_config_misaligned_saves(self):
        """config 与模板不对齐时，用模板值 reconcile（覆盖不一致、补缺失、保留多余）并保存"""
        template = {
            "plan_list": [{"tab_name": "A", "category_name": "x"}],
            "double_reward": True,
        }
        config = {
            "plan_list": [{"tab_name": "B", "category_name": "y"}],  # 不一致 → 覆盖
            "double_reward": False,  # 不一致 → 覆盖
            "ExtraKey": 1,  # 模板无 → 保留
        }
        with (
            patch.object(ZenlessZoneZeroConfig, "_load", return_value=config),
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=dump_yaml_str(template))),
            patch.object(ZenlessZoneZeroConfig, "_save") as mock_save,
        ):
            cfg = ZenlessZoneZeroConfig()
            cfg._init_config()
        mock_save.assert_called_once()
        saved = mock_save.call_args[0][0]
        self.assertEqual(saved["plan_list"], [{"tab_name": "A", "category_name": "x"}])
        self.assertEqual(saved["double_reward"], True)
        self.assertEqual(saved["ExtraKey"], 1)

    def test_set_dungeon_only_prints(self):
        """set_dungeon 应只 print 不做修改"""
        with (
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
            self.assertEqual(cfg._task_key, "")
            self.assertEqual(cfg._task_map, {})

    def test_set_dungeon_noop_does_not_save(self):
        """崩铁（M7A）副本无需适配：set_dungeon 是 no-op，不读不写。"""
        with patch.object(StarRailConfig, "_init_config"):
            cfg = StarRailConfig()
        with (
            patch.object(cfg, "_load") as mock_load,
            patch.object(cfg, "_save") as mock_save,
        ):
            cfg.set_dungeon("培养目标")
        mock_load.assert_not_called()
        mock_save.assert_not_called()

    def test_set_weekly_dungeon_writes_instance_names(self):
        """set_weekly_dungeon 写 config.yaml 的 instance_names[周常名]，容错建 dict。"""
        with patch.object(StarRailConfig, "_init_config"):
            cfg = StarRailConfig()
            config: dict = {}
            with (
                patch.object(cfg, "_load", return_value=config),
                patch.object(cfg, "_save") as mock_save,
            ):
                cfg.set_weekly_dungeon("历战余响", "铁骸的锈冢")
            mock_save.assert_called_once()
            self.assertEqual(config["instance_names"]["历战余响"], "铁骸的锈冢")

    def test_set_weekly_start_day_writes_echo_field_only(self):
        """set_weekly_start_day 只写 echo_of_war_start_day_of_week，不动 currencywars_enable。

        编辑期改周几起即应落盘起始日，无需等链运行；开关型周本的运行期门控
        （currencywars_enable）由链生成时另行计算，不在编辑期落盘。
        """
        with patch.object(StarRailConfig, "_init_config"):
            cfg = StarRailConfig()
            config: dict = {"currencywars_enable": True}
            with (
                patch.object(cfg, "_load", return_value=config),
                patch.object(cfg, "_save") as mock_save,
            ):
                cfg.set_weekly_start_day(4)
            mock_save.assert_called_once()
            self.assertEqual(config["echo_of_war_start_day_of_week"], 4)
            self.assertTrue(config["currencywars_enable"])


class TestStarRailGetDungeonLists(unittest.TestCase):
    """崩铁 get_dungeon_lists：从 instance_names.json 读副本清单（类方法，不实例化）。"""

    _DATA = {
        "历战余响": {"无": "跳过", "铁骸的锈冢": "描述1", "晨昏的回眸": "描述2"},
        "其他周常": {"甲": "x"},
    }

    def test_reads_keys_of_weekly_entry(self):
        """正常读取：返回该任务条目的键列表（即副本名，含「无」占位）。"""
        with patch(
            "src.config.set_config.load_game_config", return_value=self._DATA
        ) as mock_load:
            names = StarRailConfig.get_dungeon_lists(
                "历战余响", "assets/config/instance_names.json"
            )
        self.assertEqual(names, ["无", "铁骸的锈冢", "晨昏的回眸"])
        mock_load.assert_called_once_with(
            "March7th-Assistant", "assets/config/instance_names.json"
        )

    def test_does_not_instantiate_or_init_config(self):
        """类方法调用不触发 _init_config（否则纯读会写盘/弹确认框）。"""
        with (
            patch.object(StarRailConfig, "_init_config") as mock_init,
            patch("src.config.set_config.load_game_config", return_value=self._DATA),
        ):
            StarRailConfig.get_dungeon_lists(
                "历战余响", "assets/config/instance_names.json"
            )
        mock_init.assert_not_called()

    def test_source_is_used_as_rel_path(self):
        """source 即相对脚本根目录的路径，直接透传给 load_game_config（无额外白名单）。"""
        with patch(
            "src.config.set_config.load_game_config", return_value=None
        ) as mock_load:
            self.assertEqual(
                StarRailConfig.get_dungeon_lists("历战余响", "some/other/path.json"),
                [],
            )
        mock_load.assert_called_once_with("March7th-Assistant", "some/other/path.json")

    def test_script_not_installed_returns_empty(self):
        """M7A 未安装（load_game_config 软降级为 None）→ data 为空 → 返回 []。"""
        with patch("src.config.set_config.load_game_config", return_value=None):
            self.assertEqual(
                StarRailConfig.get_dungeon_lists(
                    "历战余响", "assets/config/instance_names.json"
                ),
                [],
            )

    def test_missing_task_key_asserts(self):
        """data 不含该任务键 → assert 触发（不静默兜底）。"""
        with (
            patch("src.config.set_config.load_game_config", return_value=self._DATA),
            self.assertRaises(AssertionError),
        ):
            StarRailConfig.get_dungeon_lists(
                "不存在的周常", "assets/config/instance_names.json"
            )

    def test_malformed_entry_asserts(self):
        """该任务条目不是 dict（格式异常）→ assert 触发（不静默兜底）。"""
        with (
            patch(
                "src.config.set_config.load_game_config",
                return_value={"历战余响": ["铁骸的锈冢"]},
            ),
            self.assertRaises(AssertionError),
        ):
            StarRailConfig.get_dungeon_lists(
                "历战余响", "assets/config/instance_names.json"
            )


class TestBaseGetDungeonLists(unittest.TestCase):
    """基类默认未适配副本清单读取 → None（调用方降级为无可选副本）。"""

    def test_base_default_returns_none(self):
        self.assertIsNone(
            ScriptConfig.get_dungeon_lists("历战余响", "instance_names.json")
        )

    def test_unadapted_subclass_returns_none(self):
        """未覆写的子类（如异环）走基类默认实现。"""
        self.assertIsNone(NTEConfig.get_dungeon_lists("任意周常", "any.json"))


class TestEndfieldGetDungeonLists(unittest.TestCase):
    """EndfieldConfig.get_dungeon_lists：读 world_map.json 的 stages_dict（二级目录）。"""

    _DATA = {
        "stages_dict": {
            "能量淤积点": ["枢纽区", "源石研究园", "武陵城"],
            "干员养成": ["干员经验", "干员进阶"],
        }
    }
    _SRC = "data/apps/ok-ef/working/assets/data/world_map.json"

    def test_reads_stages_list(self):
        """正常读取：返回 stages_dict[task_name]（二级目录副本名列表）。"""
        with patch(
            "src.config.set_config.load_game_config", return_value=self._DATA
        ) as mock_load:
            names = EndfieldConfig.get_dungeon_lists("能量淤积点", self._SRC)
        self.assertEqual(names, ["枢纽区", "源石研究园", "武陵城"])
        mock_load.assert_called_once_with("ok-ef", self._SRC)

    def test_does_not_instantiate_or_init_config(self):
        """类方法调用不触发 _init_config（否则纯读会写盘/弹确认框）。"""
        with (
            patch.object(EndfieldConfig, "_init_config") as mock_init,
            patch("src.config.set_config.load_game_config", return_value=self._DATA),
        ):
            EndfieldConfig.get_dungeon_lists("能量淤积点", self._SRC)
        mock_init.assert_not_called()

    def test_source_is_used_as_rel_path(self):
        """source 即相对脚本根目录的路径，直接透传给 load_game_config（无额外白名单）。"""
        with patch(
            "src.config.set_config.load_game_config", return_value=None
        ) as mock_load:
            self.assertEqual(
                EndfieldConfig.get_dungeon_lists("能量淤积点", "some/other/path.json"),
                [],
            )
        mock_load.assert_called_once_with("ok-ef", "some/other/path.json")

    def test_script_not_installed_returns_empty(self):
        """ok-ef 未安装（load_game_config 软降级为 None）→ data 为空 → 返回 []。"""
        with patch("src.config.set_config.load_game_config", return_value=None):
            self.assertEqual(
                EndfieldConfig.get_dungeon_lists("能量淤积点", self._SRC), []
            )

    def test_missing_stages_dict_asserts(self):
        """顶层不含 stages_dict → assert 触发（不静默兜底）。"""
        with (
            patch("src.config.set_config.load_game_config", return_value={"foo": 1}),
            self.assertRaises(AssertionError),
        ):
            EndfieldConfig.get_dungeon_lists("能量淤积点", self._SRC)

    def test_missing_task_key_asserts(self):
        """stages_dict 不含该类别 → assert 触发（不静默兜底）。"""
        with (
            patch("src.config.set_config.load_game_config", return_value=self._DATA),
            self.assertRaises(AssertionError),
        ):
            EndfieldConfig.get_dungeon_lists("不存在的类别", self._SRC)

    def test_malformed_entry_asserts(self):
        """stages_dict[task_name] 不是 list（格式异常）→ assert 触发（不静默兜底）。"""
        with (
            patch(
                "src.config.set_config.load_game_config",
                return_value={"stages_dict": {"能量淤积点": {"枢纽区": "x"}}},
            ),
            self.assertRaises(AssertionError),
        ):
            EndfieldConfig.get_dungeon_lists("能量淤积点", self._SRC)


class TestGenshinGetDungeonLists(unittest.TestCase):
    """GenshinConfig.get_dungeon_lists：遍历 tp.json 的 points 收集秘境分类副本名。"""

    _DATA = {
        "data": [
            {
                "mapName": "Teyvat",
                "points": [
                    {"type": "BlessDomain", "name": "仲夏庭园"},
                    {"type": "BlessDomain", "name": "铭记之谷"},
                    {"type": "ForgeryDomain", "name": "塞西莉亚苗圃"},
                    {"type": "TeleportWaypoint", "name": "传送锚点"},
                ],
            },
            {
                "mapName": "Enkanomiya",
                "points": [
                    {"type": "BlessDomain", "name": "芬德尼尔之顶"},
                    {"type": "MasteryDomain", "name": "太山府"},
                ],
            },
        ]
    }
    _SRC = "GameTask/AutoTrackPath/Assets/tp.json"

    def test_reads_bless_domain_across_scenes(self):
        """圣遗物 → BlessDomain：跨多个地图场景收集副本名。"""
        with patch(
            "src.config.set_config.load_game_config", return_value=self._DATA
        ) as mock_load:
            names = GenshinConfig.get_dungeon_lists("圣遗物", self._SRC)
        self.assertEqual(names, ["仲夏庭园", "铭记之谷", "芬德尼尔之顶"])
        mock_load.assert_called_once_with("BetterGI", self._SRC)

    def test_reads_forgery_domain(self):
        """武器 → ForgeryDomain：仅收集该 type 的副本名。"""
        with patch("src.config.set_config.load_game_config", return_value=self._DATA):
            names = GenshinConfig.get_dungeon_lists("武器", self._SRC)
        self.assertEqual(names, ["塞西莉亚苗圃"])

    def test_reads_mastery_domain(self):
        """天赋 → MasteryDomain。"""
        with patch("src.config.set_config.load_game_config", return_value=self._DATA):
            names = GenshinConfig.get_dungeon_lists("天赋", self._SRC)
        self.assertEqual(names, ["太山府"])

    def test_ignores_other_types(self):
        """TeleportWaypoint / 未命中 type 的 point 不计入清单。"""
        with patch("src.config.set_config.load_game_config", return_value=self._DATA):
            names = GenshinConfig.get_dungeon_lists("圣遗物", self._SRC)
        self.assertNotIn("传送锚点", names)

    def test_does_not_instantiate_or_init_config(self):
        """类方法调用不触发 _init_config（否则纯读会写盘/弹确认框）。"""
        with (
            patch.object(GenshinConfig, "_init_config") as mock_init,
            patch("src.config.set_config.load_game_config", return_value=self._DATA),
        ):
            GenshinConfig.get_dungeon_lists("圣遗物", self._SRC)
        mock_init.assert_not_called()

    def test_source_is_used_as_rel_path(self):
        """source 即相对脚本根目录的路径，直接透传给 load_game_config（无额外白名单）。"""
        with patch(
            "src.config.set_config.load_game_config", return_value=None
        ) as mock_load:
            self.assertEqual(
                GenshinConfig.get_dungeon_lists("圣遗物", "some/other/path.json"), []
            )
        mock_load.assert_called_once_with("BetterGI", "some/other/path.json")

    def test_script_not_installed_returns_empty(self):
        """BetterGI 未安装（load_game_config 软降级为 None）→ data 为空 → 返回 []。"""
        with patch("src.config.set_config.load_game_config", return_value=None):
            self.assertEqual(GenshinConfig.get_dungeon_lists("圣遗物", self._SRC), [])

    def test_unknown_category_asserts(self):
        """yml 配了未适配映射的秘境分类 → assert 触发（不静默兜底）。"""
        with (
            patch("src.config.set_config.load_game_config", return_value=self._DATA),
            self.assertRaises(AssertionError),
        ):
            GenshinConfig.get_dungeon_lists("周本", self._SRC)

    def test_top_level_not_dict_asserts(self):
        """tp.json 顶层非 dict（格式异常）→ assert 触发（不静默兜底）。"""
        with (
            patch("src.config.set_config.load_game_config", return_value=[1, 2]),
            self.assertRaises(AssertionError),
        ):
            GenshinConfig.get_dungeon_lists("圣遗物", self._SRC)


# ============================================================
# 异环 NTEConfig
# ============================================================


class TestNTEConfig(unittest.TestCase):
    def setUp(self):
        self.cfg = NTEConfig()

    def test_init_attributes(self):
        self.assertEqual(self.cfg.display_name, "异环")
        self.assertEqual(self.cfg._script_name, "ok-nte")
        self.assertEqual(
            self.cfg._config_rel_path,
            "data/apps/ok-nte/working/configs/DailyRoutineTaskConfigs.json",
        )
        self.assertEqual(
            self.cfg._routine_config_rel_path,
            "data/apps/ok-nte/working/configs/DailyRoutineTask.json",
        )
        self.assertEqual(
            self.cfg._exclusive_routine_items,
            ("daily_anomaly", "daily_anomaly_hunter"),
        )

    def test_update_sequence_changes_value(self):
        config = {"daily_anomaly": {"空幕序号": 1}}
        changed = self.cfg._update_task(config, "空幕", 3)
        self.assertTrue(changed)
        self.assertEqual(config["daily_anomaly"]["空幕序号"], 3)

    def test_update_task_no_change(self):
        """任务类型与序号均已对齐时返回 False（双通道都无改动）"""
        config = {"daily_anomaly": {"任务类型": "空幕", "空幕序号": 2}}
        changed = self.cfg._update_task(config, "空幕", 2)
        self.assertFalse(changed)

    def test_update_task_none_raises(self):
        """异环要求 sequence 不能为 None"""
        config = {"daily_anomaly": {"空幕序号": 1}}
        with self.assertRaises(AssertionError):
            self.cfg._update_task(config, "空幕", None)

    def test_update_task_unknown_dungeon_raises(self):
        config = {"daily_anomaly": {"未知序号": 1}}
        with self.assertRaises(AssertionError):
            self.cfg._update_task(config, "不存在", "1")

    def test_update_task_all_mapped_dungeons(self):
        """测试 _mode_specs[daily_anomaly].seq_fields 中所有副本都能正确更新"""
        for dungeon_name, seq_key in self.cfg._mode_specs["daily_anomaly"][
            "seq_fields"
        ].items():
            config = {"daily_anomaly": {seq_key: 0}}
            changed = self.cfg._update_task(config, dungeon_name, 5)
            self.assertTrue(changed, f"{dungeon_name} 未正确更新")
            self.assertEqual(config["daily_anomaly"][seq_key], 5)

    def _make_routine(self, anomaly_enabled=True, hunter_enabled=False):
        """构造 DailyRoutineTask.json 的 Routine Items（默认异象界域启用、追猎停用）。"""
        return {
            "Routine Items": [
                {"id": "daily_anomaly", "enabled": anomaly_enabled},
                {"id": "daily_anomaly_hunter", "enabled": hunter_enabled},
            ]
        }

    def _patch_load(self, main_config, routine):
        """按路径区分：主配置返回 main_config，routine 配置返回 routine（模拟两份文件）。"""

        def side_effect(rel_path=None, **_k):
            if rel_path == self.cfg._routine_config_rel_path:
                return routine
            return main_config

        return patch.object(self.cfg, "_load", side_effect=side_effect)

    def test_set_dungeon_with_sequence_saves(self):
        config = {"daily_anomaly": {"任务类型": "空幕", "空幕序号": 1}}
        routine = (
            self._make_routine()
        )  # 已对齐（异象界域启用、追猎停用）→ 不触发 routine 写盘
        with (
            self._patch_load(config, routine),
            patch.object(self.cfg, "_save") as mock_save,
        ):
            self.cfg.set_dungeon("空幕", 3)
        mock_save.assert_called_once()  # 仅主配置落盘，routine 已对齐无需更新
        saved = mock_save.call_args[0][0]
        self.assertEqual(saved["daily_anomaly"]["空幕序号"], 3)

    def test_set_dungeon_hunt_writes_boss_and_excludes_anomaly(self):
        """选追猎目标（具体 boss）：在 daily_anomaly_hunter 写 追猎目标、启用 hunter、
        停用 anomaly，且不写异象界域的 任务类型。"""
        config = {
            "daily_anomaly": {"任务类型": "空幕", "空幕序号": 1},
            "daily_anomaly_hunter": {"追猎目标": "音霸魔王"},
        }
        routine = self._make_routine()  # 当前异象界域启用、追猎停用
        with (
            self._patch_load(config, routine),
            patch.object(self.cfg, "_save") as mock_save,
        ):
            self.cfg.set_dungeon("追猎目标", "无首铁驭")
        calls = mock_save.call_args_list
        self.assertEqual(len(calls), 2)  # 主配置 + routine 各一次
        saved = calls[0].args[0]
        self.assertEqual(saved["daily_anomaly_hunter"]["追猎目标"], "无首铁驭")
        self.assertEqual(saved["daily_anomaly"]["任务类型"], "空幕")  # 不写异象界域
        saved_routine = calls[1].args[0]
        enabled = {it["id"]: it["enabled"] for it in saved_routine["Routine Items"]}
        self.assertTrue(enabled["daily_anomaly_hunter"])
        self.assertFalse(enabled["daily_anomaly"])

    def test_set_dungeon_hunt_preserves_task_type(self):
        """选追猎目标后，daily_anomaly 的 任务类型 保持原值（不被写成追猎目标）。"""
        config = {
            "daily_anomaly": {"任务类型": "空幕"},
            "daily_anomaly_hunter": {"追猎目标": "音霸魔王"},
        }
        routine = self._make_routine()
        with (
            self._patch_load(config, routine),
            patch.object(self.cfg, "_save"),
        ):
            self.cfg.set_dungeon("追猎目标", "音霸魔王")
        self.assertEqual(config["daily_anomaly"]["任务类型"], "空幕")

    def test_set_dungeon_anomaly_disables_hunter(self):
        """从追猎目标切回异象界域副本：启用 daily_anomaly、停用 daily_anomaly_hunter。"""
        config = {"daily_anomaly": {"任务类型": "异能升级材料", "异能材料序号": 1}}
        routine = self._make_routine(anomaly_enabled=False, hunter_enabled=True)
        with (
            self._patch_load(config, routine),
            patch.object(self.cfg, "_save") as mock_save,
        ):
            self.cfg.set_dungeon("异能升级材料", 3)
        calls = mock_save.call_args_list
        self.assertEqual(len(calls), 2)  # 主配置 + routine 各一次
        saved_routine = calls[1].args[0]
        enabled = {it["id"]: it["enabled"] for it in saved_routine["Routine Items"]}
        self.assertFalse(enabled["daily_anomaly_hunter"])
        self.assertTrue(enabled["daily_anomaly"])
        saved_config = calls[0].args[0]
        self.assertEqual(saved_config["daily_anomaly"]["任务类型"], "异能升级材料")
        self.assertEqual(saved_config["daily_anomaly"]["异能材料序号"], 3)

    def test_set_dungeon_switch_and_sequence_writes_both(self):
        """从异能升级材料切到空幕并选序号：任务类型与序号两通道都必须写入。

        _update_task 合并后内部同时写任务类型与序号两通道，本断言钉死双通道都执行。
        """
        config = {
            "daily_anomaly": {
                "任务类型": "异能升级材料",
                "异能材料序号": 1,
                "空幕序号": 1,
            }
        }
        routine = self._make_routine()  # 已对齐，不触发 routine 写盘
        with (
            self._patch_load(config, routine),
            patch.object(self.cfg, "_save") as mock_save,
        ):
            self.cfg.set_dungeon("空幕", 3)
        mock_save.assert_called_once()  # 仅主配置落盘
        saved = mock_save.call_args[0][0]
        self.assertEqual(saved["daily_anomaly"]["任务类型"], "空幕")
        self.assertEqual(saved["daily_anomaly"]["空幕序号"], 3)  # 序号通道也被执行

    def test_update_task_writes_dungeon_name(self):
        """任务类型写入 daily_anomaly 子对象（值即中文副本名）"""
        config = {"daily_anomaly": {"任务类型": "空幕"}}
        changed = self.cfg._update_task(config, "异能升级材料", 1)
        self.assertTrue(changed)
        self.assertEqual(config["daily_anomaly"]["任务类型"], "异能升级材料")

    def test_missing_daily_section_raises(self):
        """顶层缺 daily_anomaly（旧版 DailyTask.json 结构）→ assert"""
        config = {"任务类型": "空幕"}
        with self.assertRaises(AssertionError):
            self.cfg._update_task(config, "空幕")

    # ---- 追猎目标 / 异象界域 互斥 ----

    def test_update_routine_exclusion_flips_to_hunter(self):
        """追猎目标：启用 hunter、停用 anomaly，返回已修改。"""
        routine = self._make_routine()
        changed = self.cfg._update_routine_exclusion(routine, "daily_anomaly_hunter")
        self.assertTrue(changed)
        enabled = {it["id"]: it["enabled"] for it in routine["Routine Items"]}
        self.assertTrue(enabled["daily_anomaly_hunter"])
        self.assertFalse(enabled["daily_anomaly"])

    def test_update_routine_exclusion_flips_to_anomaly(self):
        """异象界域副本：启用 anomaly、停用 hunter，返回已修改。"""
        routine = self._make_routine(anomaly_enabled=False, hunter_enabled=True)
        changed = self.cfg._update_routine_exclusion(routine, "daily_anomaly")
        self.assertTrue(changed)
        enabled = {it["id"]: it["enabled"] for it in routine["Routine Items"]}
        self.assertTrue(enabled["daily_anomaly"])
        self.assertFalse(enabled["daily_anomaly_hunter"])

    def test_update_routine_exclusion_no_change(self):
        """已对齐时返回 False（无写盘）。"""
        routine = self._make_routine()
        self.assertFalse(self.cfg._update_routine_exclusion(routine, "daily_anomaly"))
        routine = self._make_routine(anomaly_enabled=False, hunter_enabled=True)
        self.assertFalse(
            self.cfg._update_routine_exclusion(routine, "daily_anomaly_hunter")
        )

    def test_update_routine_exclusion_missing_routine_items_raises(self):
        with self.assertRaises(AssertionError):
            self.cfg._update_routine_exclusion({}, "daily_anomaly")

    def test_update_routine_exclusion_missing_target_raises(self):
        """Routine Items 缺目标 item（无法启用所选玩法）→ assert。"""
        routine = {"Routine Items": [{"id": "daily_anomaly", "enabled": True}]}
        with self.assertRaises(AssertionError):
            self.cfg._update_routine_exclusion(routine, "daily_anomaly_hunter")

    def test_dungeon_to_mode_mapping(self):
        """副本中文名经 _dungeon_to_mode 正确反查模式（异象界域副本→daily_anomaly，追猎目标→daily_anomaly_hunter）。"""
        for dungeon in self.cfg._mode_specs["daily_anomaly"]["seq_fields"]:
            self.assertEqual(self.cfg._dungeon_to_mode[dungeon], "daily_anomaly")
        self.assertEqual(self.cfg._dungeon_to_mode["追猎目标"], "daily_anomaly_hunter")

    def test_update_sequence_hunt_writes_boss(self):
        """追猎目标经 _update_task 在 daily_anomaly_hunter 写 追猎目标（boss），不依赖 _bind_section。"""
        config = {"daily_anomaly_hunter": {"追猎目标": "音霸魔王"}}
        changed = self.cfg._update_task(config, "追猎目标", "海囚")
        self.assertTrue(changed)
        self.assertEqual(config["daily_anomaly_hunter"]["追猎目标"], "海囚")

    def test_update_task_skips_hunt(self):
        """追猎目标不写任务类型字段（仅写 boss 序号、不写 任务类型），不依赖 _bind_section。"""
        config = {
            "daily_anomaly": {"任务类型": "空幕"},
            "daily_anomaly_hunter": {"追猎目标": "音霸魔王"},
        }
        changed = self.cfg._update_task(config, "追猎目标", "海囚")
        self.assertTrue(changed)
        self.assertEqual(config["daily_anomaly"]["任务类型"], "空幕")

    def test_update_sequence_hunt_no_boss_raises(self):
        """未选具体 boss（sequence=None）→ assert。"""
        with self.assertRaises(AssertionError):
            self.cfg._update_task({}, "追猎目标", None)


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
                "Annihilation": "剿灭",
                "AP-5": "红票",
                "LS-6": "经验",
                "CE-6": "龙门币",
                "1-7": "土",
            }
            return cfg

    def test_init_attributes(self):
        cfg = self._make_cfg()
        self.assertEqual(cfg.display_name, "粥")
        self.assertEqual(cfg._script_name, "MAA")
        self.assertIn("Annihilation", cfg._task_map)
        self.assertEqual(cfg._task_map["Annihilation"], "剿灭")
        self.assertEqual(cfg._task_map["1-7"], "土")

    def test_init_config_no_template_is_noop(self):
        """粥无模板（_template_rel_path 为空）：_init_config 不应加载模板或写盘。"""
        cfg = ArknightsConfig()
        with (
            patch.object(ArknightsConfig, "_load_template") as mock_template,
            patch.object(ArknightsConfig, "_save") as mock_save,
        ):
            cfg._init_config()
        mock_template.assert_not_called()
        mock_save.assert_not_called()

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

    # ---- set_dungeon ----

    def test_set_dungeon_disables_all_enables_selected_and_土(self):
        cfg = self._make_cfg()
        # 构造合法的 TaskQueue（顺序任意，通过 StagePlan[0] 识别）
        queue = [
            {"Name": "开始唤醒", "$type": "StartUpTask"},
            {
                "Name": "剿灭",
                "$type": "FightTask",
                "StagePlan": ["Annihilation"],
                "IsEnable": True,
            },
            {
                "Name": "红票",
                "$type": "FightTask",
                "StagePlan": ["AP-5"],
                "IsEnable": True,
            },
            {
                "Name": "经验",
                "$type": "FightTask",
                "StagePlan": ["LS-6"],
                "IsEnable": True,
            },
            {
                "Name": "龙门币",
                "$type": "FightTask",
                "StagePlan": ["CE-6"],
                "IsEnable": True,
            },
            {
                "Name": "活动土",
                "$type": "FightTask",
                "StagePlan": [""],
                "IsEnable": True,
            },
            {
                "Name": "土",
                "$type": "FightTask",
                "StagePlan": ["1-7"],
                "IsEnable": True,
            },
        ]

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
        by_name = {t["Name"]: t for t in saved_queue}
        # 红票启用
        self.assertTrue(by_name["红票"]["IsEnable"])
        # 土启用（清理剩余体力）
        self.assertTrue(by_name["土"]["IsEnable"])
        # 剿灭始终启用（周常）
        self.assertTrue(by_name["剿灭"]["IsEnable"])
        # 活动土不动（未维护）
        self.assertTrue(by_name["活动土"]["IsEnable"])
        # 其他副本禁用
        self.assertFalse(by_name["经验"]["IsEnable"])
        self.assertFalse(by_name["龙门币"]["IsEnable"])

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
        queue = [
            {"Name": "开始唤醒", "$type": "StartUpTask"},
            {
                "Name": "剿灭",
                "$type": "FightTask",
                "StagePlan": ["Annihilation"],
                "IsEnable": True,
            },
            {
                "Name": "红票",
                "$type": "FightTask",
                "StagePlan": ["AP-5"],
                "IsEnable": True,
            },
            {
                "Name": "经验",
                "$type": "FightTask",
                "StagePlan": ["LS-6"],
                "IsEnable": True,
            },
            {
                "Name": "龙门币",
                "$type": "FightTask",
                "StagePlan": ["CE-6"],
                "IsEnable": True,
            },
            {
                "Name": "活动土",
                "$type": "FightTask",
                "StagePlan": [""],
                "IsEnable": True,
            },
            {
                "Name": "土",
                "$type": "FightTask",
                "StagePlan": ["1-7"],
                "IsEnable": True,
            },
        ]

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
        by_name = {t["Name"]: t for t in saved_queue}
        # 剿灭启用
        self.assertTrue(by_name["剿灭"]["IsEnable"])
        # 土启用（清理剩余体力）
        self.assertTrue(by_name["土"]["IsEnable"])
        # 活动土不动（未维护）
        self.assertTrue(by_name["活动土"]["IsEnable"])
        # 其他副本禁用
        self.assertFalse(by_name["红票"]["IsEnable"])
        self.assertFalse(by_name["经验"]["IsEnable"])
        self.assertFalse(by_name["龙门币"]["IsEnable"])

    def test_set_dungeon_unknown_stage_skipped(self):
        """未维护的关卡（StagePlan[0] 不在 _task_map）应跳过，不改 IsEnable"""
        cfg = self._make_cfg()
        queue = [
            {"Name": "开始唤醒", "$type": "StartUpTask"},
            {
                "Name": "未知关卡",
                "$type": "FightTask",
                "StagePlan": ["unknown"],
                "IsEnable": True,
            },
            {
                "Name": "剿灭",
                "$type": "FightTask",
                "StagePlan": ["Annihilation"],
                "IsEnable": True,
            },
        ]
        config = {"Configurations": {"Default": {"TaskQueue": queue}}}
        with (
            patch.object(cfg, "_load", return_value=config),
            patch.object(cfg, "_save"),
        ):
            cfg.set_dungeon("剿灭")
        unknown = [t for t in queue if t.get("StagePlan") == ["unknown"]][0]
        self.assertTrue(unknown["IsEnable"])


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
        """OK 系（ok-ww/ok-ef）读取 devices.json 的 pc_full_path。

        异环（ok-nte）已重写 get_game_exe_path 返回启动器路径，不在此列（见专项测试）。
        """
        cases = (
            (WutheringWavesConfig, "ok-ww"),
            (EndfieldConfig, "ok-ef"),
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

    def test_nte_launcher_found_upward(self):
        """异环启动器在游戏安装根目录（从游戏本体逐级上溯）→ 返回 NTELauncher.exe 路径"""
        game_exe = os.path.join(
            "D:/Neverness To Everness",
            "Client",
            "WindowsNoEditor",
            "HT",
            "Binaries",
            "Win64",
            "HTGame.exe",
        )
        launcher = os.path.join("D:/Neverness To Everness", "NTELauncher.exe")
        with (
            patch(
                "src.config.set_config.load_game_config",
                return_value={"pc_full_path": game_exe},
            ),
            patch("os.path.isfile", side_effect=lambda p: p == launcher),
        ):
            got = NTEConfig.get_game_exe_path("ok-nte")
        self.assertEqual(got, launcher)

    def test_nte_launcher_missing_returns_none(self):
        """异环启动器不存在（上溯到盘符根也找不到）→ None，GUI 提示「未找到游戏路径」"""
        game_exe = os.path.join(
            "D:/Neverness To Everness",
            "Client",
            "WindowsNoEditor",
            "HT",
            "Binaries",
            "Win64",
            "HTGame.exe",
        )
        with (
            patch(
                "src.config.set_config.load_game_config",
                return_value={"pc_full_path": game_exe},
            ),
            patch("os.path.isfile", return_value=False),
        ):
            got = NTEConfig.get_game_exe_path("ok-nte")
        self.assertIsNone(got)

    def test_nte_game_exe_missing_returns_none(self):
        """异环游戏本体路径读不到（devices.json 缺失）→ None"""
        with patch("src.config.set_config.load_game_config", return_value=None):
            got = NTEConfig.get_game_exe_path("ok-nte")
        self.assertIsNone(got)

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


class TestGetGameExePathAdapter(unittest.TestCase):
    """测试适配器接口 get_game_exe_path 的分发逻辑"""

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
        """已适配周常的脚本：崩铁（货币战争）/ 鸣潮（每周花园）/ 绝区零（lost_void）/ 终末地（卖出物资）/ 明日方舟（理智药剂）"""
        for name in (
            "March7th-Assistant",
            "ok-ww",
            "OneDragon-Launcher",
            "ok-ef",
            "MAA",
        ):
            self.assertTrue(set_config.supports_weekly(name), f"{name} 应支持周常")

    def test_other_scripts_default_false(self):
        """其余脚本未适配周常 → False"""
        supported = (
            "March7th-Assistant",
            "ok-ww",
            "OneDragon-Launcher",
            "ok-ef",
            "MAA",
        )
        for name in set_config._CONFIGS:
            if name in supported:
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

    def test_set_weekly_enabled_false_short_circuits(self):
        """用户已拒绝（enabled=False）→ 直接跳过，不落盘（同 set_dungeon）"""
        with patch.object(StarRailConfig, "_init_config"):
            cfg = StarRailConfig()
        cfg._enabled = False
        with patch.object(cfg, "_save") as mock_save:
            cfg.set_weekly(4)
        mock_save.assert_not_called()

    # ---- 崩铁：currencywars_enable ----

    def test_star_rail_enable_writes_true(self):
        """崩铁今天已到起始日 → currencywars_enable=True 且 echo_of_war_start_day_of_week=起始日（历战余响）"""
        with patch.object(StarRailConfig, "_init_config"):
            cfg = StarRailConfig()
        config = {"currencywars_enable": False, "echo_of_war_start_day_of_week": 1}
        with (
            patch("src.utils_weekly.get_week_num", return_value=3),
            patch.object(cfg, "_load", return_value=config),
            patch.object(cfg, "_save") as mock_save,
        ):
            cfg.set_weekly(4)
        self.assertTrue(config["currencywars_enable"])
        self.assertEqual(config["echo_of_war_start_day_of_week"], 4)
        mock_save.assert_called_once()

    def test_star_rail_disable_writes_false(self):
        """崩铁今天未到起始日 → currencywars_enable=False，但 echo_of_war_start_day_of_week 仍写起始日（由 M7A 自身门控）"""
        with patch.object(StarRailConfig, "_init_config"):
            cfg = StarRailConfig()
        config = {"currencywars_enable": True, "echo_of_war_start_day_of_week": 1}
        with (
            patch("src.utils_weekly.get_week_num", return_value=1),
            patch.object(cfg, "_load", return_value=config),
            patch.object(cfg, "_save") as mock_save,
        ):
            cfg.set_weekly(4)
        self.assertFalse(config["currencywars_enable"])
        self.assertEqual(config["echo_of_war_start_day_of_week"], 4)
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

    # ---- 明日方舟：理智药剂（UseExpiringMedicine + MedicineExpireDays）----

    def _make_maa_cfg(self):
        with patch.object(ArknightsConfig, "_init_config"):
            return ArknightsConfig()

    def _maa_queue(self, enabled_names):
        """构造 gui.new.json 风格的 TaskQueue：FightTask 的 IsEnable 由 enabled_names 决定。"""
        names = ["剿灭", "红票", "经验", "土", "活动土"]
        tasks = [{"$type": "StartUpTask", "Name": "开始唤醒", "IsEnable": True}]
        for name in names:
            task = {"$type": "FightTask", "Name": name}
            if name in enabled_names:
                task["IsEnable"] = True
            else:
                task["IsEnable"] = False
            tasks.append(task)
        return tasks

    def _maa_config(self, enabled_names):
        return {
            "Configurations": {"Default": {"TaskQueue": self._maa_queue(enabled_names)}}
        }

    def test_arknights_weekly_syncs_use_expiring_medicine(self):
        """开启的 FightTask → UseExpiringMedicine=true，其余 false（随 IsEnable 同步）；剿灭不吃药强制 false"""
        cfg = self._make_maa_cfg()
        config = self._maa_config({"剿灭", "土", "活动土"})
        with (
            patch("src.config.set_config.load_config", return_value=config),
            patch("src.config.set_config.save_config") as mock_save,
        ):
            cfg.set_weekly(3)
        by_name = {
            t["Name"]: t
            for t in config["Configurations"]["Default"]["TaskQueue"]
            if t.get("$type") == "FightTask"
        }
        # 剿灭开启但强制不吃药
        self.assertFalse(by_name["剿灭"]["UseExpiringMedicine"])
        self.assertTrue(by_name["土"]["UseExpiringMedicine"])
        self.assertTrue(by_name["活动土"]["UseExpiringMedicine"])
        self.assertFalse(by_name["红票"]["UseExpiringMedicine"])
        self.assertFalse(by_name["经验"]["UseExpiringMedicine"])
        mock_save.assert_called_once()

    def test_arknights_weekly_annihilation_no_medicine(self):
        """剿灭不吃理智药：即便 IsEnable=true，UseExpiringMedicine 强制 false，但照常运行"""
        cfg = self._make_maa_cfg()
        # 仅开启剿灭
        config = self._maa_config({"剿灭"})
        with (
            patch("src.config.set_config.load_config", return_value=config),
            patch("src.config.set_config.save_config"),
        ):
            cfg.set_weekly(2)
        annih = next(
            t
            for t in config["Configurations"]["Default"]["TaskQueue"]
            if t["Name"] == "剿灭"
        )
        self.assertTrue(annih["IsEnable"], "剿灭应照常开启运行")
        self.assertFalse(annih["UseExpiringMedicine"], "剿灭不吃理智药")
        self.assertEqual(annih["MedicineExpireDays"], 6)  # 周几起=2 ⇒ 8-2

    def test_arknights_weekly_expire_days_from_start_day(self):
        """MedicineExpireDays = 8 - 周几起：周几起=1→7，周几起=7→1，周几起=3→5"""
        cfg = self._make_maa_cfg()
        for start_day, expect in ((1, 7), (3, 5), (7, 1)):
            with self.subTest(start_day=start_day):
                config = self._maa_config({"土"})
                with (
                    patch("src.config.set_config.load_config", return_value=config),
                    patch("src.config.set_config.save_config"),
                ):
                    cfg.set_weekly(start_day)
                tasks = config["Configurations"]["Default"]["TaskQueue"]
                for t in tasks:
                    if t.get("$type") == "FightTask":
                        self.assertEqual(t["MedicineExpireDays"], expect)

    def test_arknights_weekly_ignores_non_fight_task(self):
        """StartUpTask 等非 FightTask 不受 UseExpiringMedicine/MedicineExpireDays 影响"""
        cfg = self._make_maa_cfg()
        config = self._maa_config({"土"})
        with (
            patch("src.config.set_config.load_config", return_value=config),
            patch("src.config.set_config.save_config"),
        ):
            cfg.set_weekly(3)
        startup = next(
            t
            for t in config["Configurations"]["Default"]["TaskQueue"]
            if t.get("$type") != "FightTask"
        )
        self.assertNotIn("UseExpiringMedicine", startup)
        self.assertNotIn("MedicineExpireDays", startup)

    def test_arknights_weekly_no_change_skips_save(self):
        """配置已符合预期（开启项 true、关闭项 false、剿灭强制 false、MedicineExpireDays 一致）→ 不落盘"""
        cfg = self._make_maa_cfg()
        config = self._maa_config({"剿灭", "土", "活动土"})
        for t in config["Configurations"]["Default"]["TaskQueue"]:
            if t.get("$type") == "FightTask":
                enabled = t["IsEnable"]
                # 剿灭不吃药，即便开启也强制 false
                use_medicine = enabled and t["Name"] != "剿灭"
                t["UseExpiringMedicine"] = use_medicine
                t["MedicineExpireDays"] = 8 - 3  # 周几起=3
        with (
            patch("src.config.set_config.load_config", return_value=config),
            patch("src.config.set_config.save_config") as mock_save,
        ):
            cfg.set_weekly(3)
        mock_save.assert_not_called()

    def test_arknights_weekly_start_day_writes_expire_days_only(self):
        """set_weekly_start_day 只写 MedicineExpireDays（= 8 - 周几起），不动 UseExpiringMedicine。

        编辑期改周几起即应落盘过期窗口，无需等链运行；是否吃药的开关依赖各任务的
        启用状态，由运行期 set_weekly 另行计算，不在编辑期落盘。
        """
        cfg = self._make_maa_cfg()
        config = self._maa_config({"土"})
        # 给各 FightTask 预设假的 UseExpiringMedicine 与不同 MedicineExpireDays，验证前者不动、后者被改写
        for t in config["Configurations"]["Default"]["TaskQueue"]:
            if t.get("$type") == "FightTask":
                t["UseExpiringMedicine"] = "SHOULD_NOT_CHANGE"
                t["MedicineExpireDays"] = 99
        with (
            patch("src.config.set_config.load_config", return_value=config),
            patch("src.config.set_config.save_config") as mock_save,
        ):
            cfg.set_weekly_start_day(3)  # 周几起=3 ⇒ MedicineExpireDays=5
        mock_save.assert_called_once()
        tasks = config["Configurations"]["Default"]["TaskQueue"]
        for t in tasks:
            if t.get("$type") == "FightTask":
                self.assertEqual(t["MedicineExpireDays"], 5)
                self.assertEqual(t["UseExpiringMedicine"], "SHOULD_NOT_CHANGE")


class TestSetConfigAdapter(unittest.TestCase):
    """测试适配器接口 set_config() 的分发逻辑"""

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
