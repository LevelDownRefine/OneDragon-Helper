"""
测试 set_config.py 中各 ScriptConfig 子类的行为。

覆盖每个子类的 _update_task（含二级序列）/ set_daily_task / _init_config / _is_aligned 等方法。
所有文件 I/O 均通过 mock 隔离，不依赖真实 config 文件。
"""

import json
import os
import unittest
from contextlib import ExitStack
from unittest.mock import MagicMock, mock_open, patch

from src.config import set_config
from src.config.daily import Daily
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
from src.utils.utils_yaml import dump_yaml_str


def _update(cfg, config: dict, daily_name: str, task_name: str, sequence=None) -> bool:
    """写入：读盘打桩为 config、落盘吞掉——绝不写真实子脚本 config。"""
    daily = cfg._dispatch_daily(daily_name)
    with (
        patch.object(daily, "_load_daily_config", return_value=config),
        patch.object(daily, "_save_daily_config"),
    ):
        return daily.update(task_name, sequence)


def _read(cfg, daily_name: str) -> tuple[str | None, str | int | None]:
    """反读：经 Daily.read 的 I/O 闭环（读盘打桩由用例负责）。"""
    return cfg._dispatch_daily(daily_name).read()


# ============================================================
# 基类 ScriptConfig
# ============================================================


class TestScriptConfigBase(unittest.TestCase):
    """测试基类 _update_task / set_daily_task 的默认行为"""

    def test_set_daily_task_unknown_daily_raises(self):
        """日常展示名不在声明里 → assert（落点全部由声明推导，认不出即报）。"""
        cfg = WutheringWavesConfig()
        with (
            patch.object(Daily, "_load_daily_config", return_value={}),
            self.assertRaisesRegex(AssertionError, "未知日常"),
        ):
            cfg.set_daily_task("不存在的日常", "凝素领域", 3)

    def test_set_task_changed_saves(self):
        """set_daily_task 有修改时应（按声明落点）落盘"""
        cfg = WutheringWavesConfig()
        with (
            patch.object(
                Daily, "_load_daily_config", return_value={"Which to Farm": "old"}
            ),
            patch.object(Daily, "_save_daily_config") as mock_save,
        ):
            cfg.set_daily_task("每日任务", "凝素领域", 3)
        self.assertEqual(
            mock_save.call_args[0][0],
            {
                "Which to Farm": "Forgery Challenge",
                "Which Forgery Challenge to Farm": 3,
            },
        )

    def test_set_daily_task_unchanged_no_save(self):
        """set_daily_task 无修改时不调用 _save"""
        cfg = WutheringWavesConfig()
        current = {
            "Which to Farm": "Forgery Challenge",
            "Which Forgery Challenge to Farm": 3,
        }
        with (
            patch.object(Daily, "_load_daily_config", return_value=current),
            patch.object(Daily, "_save_daily_config") as mock_save,
        ):
            cfg.set_daily_task("每日任务", "凝素领域", 3)
        mock_save.assert_not_called()

    def test_daily_physical_name_available_on_base(self):
        """日常对象在基类可取（非异环专属）：单日常脚本亦然，物理名回落展示名。"""
        cfg = WutheringWavesConfig()
        self.assertEqual(cfg._dispatch_daily("每日任务").physical_name, "每日任务")
        with self.assertRaisesRegex(AssertionError, "未知日常"):
            cfg._dispatch_daily("不存在的日常")

    def test_set_daily_task_without_daily_raises(self):
        """写路径必须给出日常展示名（单日常脚本也不例外）。"""
        with patch("src.config.set_config.get_daily_configs", return_value=[]):
            cfg = ScriptConfig()
        cfg.display_name = "测试"
        with (
            patch.object(Daily, "_load_daily_config", return_value={"task": "old"}),
            self.assertRaisesRegex(AssertionError, "必须指定日常"),
        ):
            cfg.set_daily_task(None, "new")


# ============================================================
# _save / _verify_saved（保存后重读校验）
# ============================================================


# ============================================================
# 鸣潮 WutheringWavesConfig
# ============================================================


class TestWutheringWavesConfig(unittest.TestCase):
    def setUp(self):
        self.cfg = WutheringWavesConfig()

    def test_init_attributes(self):
        self.assertEqual(self.cfg.display_name, "鸣潮")
        self.assertEqual(self.cfg._script_name, "ok-ww")
        daily = self.cfg._dispatch_daily("每日任务")
        self.assertEqual(daily.task_field, "Which to Farm")
        self.assertIn("凝素领域", daily.task_map)
        self.assertIn("模拟领域", daily.task_map)
        self.assertIn("无音区", daily.task_map)

    def test_update_task_maps_task(self):
        config = {"Which to Farm": "old", "Which Tacet Suppression to Farm": 1}
        changed = _update(self.cfg, config, "每日任务", "无音区", 3)
        self.assertTrue(changed)
        self.assertEqual(config["Which to Farm"], "Tacet Suppression")

    # ---- _update_task: 模拟领域 ----

    def test_update_sequence_simulation(self):
        config = {"Which to Farm": "Simulation Challenge", "Material Selection": "old"}
        changed = _update(self.cfg, config, "每日任务", "模拟领域", "共鸣者经验")
        self.assertTrue(changed)
        self.assertEqual(config["Material Selection"], "Resonator EXP")

    def test_update_sequence_simulation_no_change(self):
        config = {
            "Which to Farm": "Simulation Challenge",
            "Material Selection": "Weapon EXP",
        }
        changed = _update(self.cfg, config, "每日任务", "模拟领域", "武器经验")
        self.assertFalse(changed)

    def test_update_sequence_simulation_unknown_raises(self):
        config = {"Which to Farm": "Simulation Challenge", "Material Selection": "old"}
        with self.assertRaises(AssertionError):
            _update(self.cfg, config, "每日任务", "模拟领域", "不存在")

    # ---- _update_task: 无音区 ----

    def test_update_sequence_tacet(self):
        config = {
            "Which to Farm": "Tacet Suppression",
            "Which Tacet Suppression to Farm": 1,
        }
        changed = _update(self.cfg, config, "每日任务", "无音区", 3)
        self.assertTrue(changed)
        self.assertEqual(config["Which Tacet Suppression to Farm"], 3)

    def test_update_sequence_tacet_no_change(self):
        config = {
            "Which to Farm": "Tacet Suppression",
            "Which Tacet Suppression to Farm": 2,
        }
        changed = _update(self.cfg, config, "每日任务", "无音区", 2)
        self.assertFalse(changed)

    # ---- _update_task: 凝素领域 ----

    def test_update_sequence_forgery(self):
        config = {
            "Which to Farm": "Forgery Challenge",
            "Which Forgery Challenge to Farm": 1,
        }
        changed = _update(self.cfg, config, "每日任务", "凝素领域", 4)
        self.assertTrue(changed)
        self.assertEqual(config["Which Forgery Challenge to Farm"], 4)

    def test_update_sequence_forgery_no_change(self):
        config = {
            "Which to Farm": "Forgery Challenge",
            "Which Forgery Challenge to Farm": 2,
        }
        changed = _update(self.cfg, config, "每日任务", "凝素领域", 2)
        self.assertFalse(changed)

    # ---- _update_task: None ----

    def test_update_sequence_none_raises(self):
        config = {"Which to Farm": "Simulation Challenge"}
        with self.assertRaises(AssertionError):
            _update(self.cfg, config, "每日任务", "模拟领域", None)

    # ---- _update_task: 未知副本类型 ----

    def test_update_sequence_unknown_daily_task_type_raises(self):
        config = {"Which to Farm": "Unknown Type"}
        with self.assertRaises(AssertionError):
            _update(self.cfg, config, "每日任务", "未知", "1")

    # ---- set_daily_task 集成 ----

    def test_set_daily_task_with_sequence_saves(self):
        config = {
            "Which to Farm": "Forgery Challenge",
            "Which Forgery Challenge to Farm": 1,
        }
        with (
            patch.object(Daily, "_load_daily_config", return_value=config),
            patch.object(Daily, "_save_daily_config") as mock_save,
        ):
            self.cfg.set_daily_task("每日任务", "凝素领域", 3)
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
        self.assertEqual(cfg._dispatch_daily("每日任务").task_field, "DomainName")

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
            patch.object(set_config, "load_config", return_value=config),
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=json.dumps(template))),
            patch("src.config.set_config.save_config") as mock_save,
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
            patch.object(set_config, "load_config", return_value=config),
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=json.dumps(template))),
            patch("src.config.set_config.save_config") as mock_save,
        ):
            cfg = GenshinConfig()
            cfg._init_config()
        mock_save.assert_called_once()
        saved = mock_save.call_args[0][2]
        # 不一致项被模板值覆盖
        self.assertEqual(saved["TaskEnabledList"], {"领取邮件": True})
        self.assertEqual(saved["CompletionAction"], "关闭游戏")
        # 多余项保留
        self.assertEqual(saved["ExtraKey"], 1)

    def test_init_config_missing_config_is_noop(self):
        """config 缺失（首次写入前）时 _init_config 不崩溃、不写盘。"""
        with (
            patch.object(set_config, "load_config", return_value=None),
            patch.object(GenshinConfig, "_load_template") as mock_template,
            patch("src.config.set_config.save_config") as mock_save,
        ):
            cfg = GenshinConfig()
            cfg._init_config()
        mock_template.assert_not_called()
        mock_save.assert_not_called()

    def test_update_task_writes_shared_field(self):
        """原神两级共用 DomainName：无二级时写入一级项名。"""
        with (
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data="{}")),
        ):
            cfg = GenshinConfig()
        config = {"DomainName": "旧本"}
        changed = _update(cfg, config, "每日任务", "圣遗物")
        self.assertTrue(changed)
        self.assertEqual(config["DomainName"], "圣遗物")


# ============================================================
# 终末地 EndfieldConfig
# ============================================================


class TestEndfieldConfig(unittest.TestCase):
    def test_init_attributes(self):
        with patch.object(EndfieldConfig, "_init_config"):
            cfg = EndfieldConfig()
        self.assertEqual(cfg.display_name, "终末地")
        self.assertEqual(cfg._script_name, "ok-ef")
        self.assertEqual(cfg._dispatch_daily("每日任务").task_field, "体力本")
        self.assertEqual(cfg._template_rel_path, "okef一条龙.json")

    def test_update_task_writes_shared_field(self):
        """终末地两级共用 体力本：无二级时写入一级项名。"""
        with patch.object(EndfieldConfig, "_init_config"):
            cfg = EndfieldConfig()
        config = {"体力本": "旧本"}
        changed = _update(cfg, config, "每日任务", "干员养成")
        self.assertTrue(changed)
        self.assertEqual(config["体力本"], "干员养成")

    def test_set_daily_task_no_sequence(self):
        with patch.object(EndfieldConfig, "_init_config"):
            cfg = EndfieldConfig()
        config = {"体力本": "旧本", "⭐刷体力": True}
        with (
            patch.object(Daily, "_load_daily_config", return_value=config),
            patch.object(Daily, "_save_daily_config") as mock_save,
        ):
            cfg.set_daily_task("每日任务", "干员养成")
        mock_save.assert_called_once_with({"体力本": "干员养成", "⭐刷体力": True})

    def test_set_daily_task_with_sequence_writes_second_level(self):
        """终末地副本按「类型 → 副本」两级组织（假一级目录）：写入的是二级副本名。"""
        with patch.object(EndfieldConfig, "_init_config"):
            cfg = EndfieldConfig()
        config = {"体力本": "旧本", "⭐刷体力": True}
        with (
            patch.object(Daily, "_load_daily_config", return_value=config),
            patch.object(Daily, "_save_daily_config") as mock_save,
        ):
            cfg.set_daily_task("每日任务", "能量淤积点", sequence="枢纽区")
        mock_save.assert_called_once_with({"体力本": "枢纽区", "⭐刷体力": True})

    def test_init_config_aligned_no_save(self):
        """config 与模板对齐（含模板外的自定义 key）时不保存"""
        template = {"购物白名单": ["精锻"], "是否买礼物": False}
        config = {
            "购物白名单": ["精锻"],
            "是否买礼物": False,
            "体力本": "旧本",  # 模板外的用户自定义 key
        }
        with (
            patch.object(set_config, "load_config", return_value=config),
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=json.dumps(template))),
            patch("src.config.set_config.save_config") as mock_save,
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
            patch.object(set_config, "load_config", return_value=config),
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=json.dumps(template))),
            patch("src.config.set_config.save_config") as mock_save,
        ):
            cfg = EndfieldConfig()
            cfg._init_config()
        mock_save.assert_called_once()
        saved = mock_save.call_args[0][2]
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
            patch.object(set_config, "load_config", return_value=template),
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=dump_yaml_str(template))),
            patch("src.config.set_config.save_config"),
        ):
            cfg = ZenlessZoneZeroConfig()
        self.assertEqual(cfg.display_name, "绝区零")
        self.assertEqual(cfg._script_name, "OneDragon-Launcher")
        self.assertFalse(cfg._dispatch_daily("每日任务").option_fields, "日常无落点")

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
            patch.object(set_config, "load_config", return_value=config),
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=dump_yaml_str(template))),
            patch("src.config.set_config.save_config") as mock_save,
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
            patch.object(set_config, "load_config", return_value=config),
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=dump_yaml_str(template))),
            patch("src.config.set_config.save_config") as mock_save,
        ):
            cfg = ZenlessZoneZeroConfig()
            cfg._init_config()
        mock_save.assert_called_once()
        saved = mock_save.call_args[0][2]
        self.assertEqual(saved["plan_list"], [{"tab_name": "A", "category_name": "x"}])
        self.assertEqual(saved["double_reward"], True)
        self.assertEqual(saved["ExtraKey"], 1)

    def test_set_daily_task_only_prints(self):
        """绝区零副本无需适配：NoopDaily.update 不读不写。"""
        with (
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data="{}")),
        ):
            cfg = ZenlessZoneZeroConfig()
        with (
            patch.object(Daily, "_load_daily_config") as mock_load,
            patch.object(Daily, "_save_daily_config") as mock_save,
        ):
            cfg.set_daily_task("每日任务", "任何副本", "任何序列")
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
            self.assertEqual(cfg._script_name, "March7th-Launcher")
            self.assertFalse(
                cfg._dispatch_daily("每日任务").option_fields, "日常无落点"
            )

    def test_set_daily_task_noop_does_not_save(self):
        """崩铁（M7A）副本无需适配：NoopDaily.update 不读不写。"""
        with patch.object(StarRailConfig, "_init_config"):
            cfg = StarRailConfig()
        with (
            patch.object(Daily, "_load_daily_config") as mock_load,
            patch.object(Daily, "_save_daily_config") as mock_save,
        ):
            cfg.set_daily_task("每日任务", "培养目标")
        mock_load.assert_not_called()
        mock_save.assert_not_called()


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
            self.cfg._dailies[0]._config_rel_path,
            "data/apps/ok-nte/working/configs/DailyRoutineTaskConfigs.json",
        )
        self.assertEqual(
            self.cfg._dailies[0]._routine_rel_path,
            "data/apps/ok-nte/working/configs/DailyRoutineTask.json",
        )
        # 日常对象按声明顺序给出（界面逐行呈现即按此顺序）
        self.assertEqual(
            tuple(d.physical_name for d in self.cfg._dailies),
            ("daily_anomaly", "daily_anomaly_hunter"),
        )

    def test_update_sequence_changes_value(self):
        config = {"daily_anomaly": {"空幕序号": 1}}
        changed = _update(self.cfg, config, "异象界域", "空幕", 3)
        self.assertTrue(changed)
        self.assertEqual(config["daily_anomaly"]["空幕序号"], 3)

    def test_update_task_no_change(self):
        """任务类型与序号均已对齐时返回 False（双通道都无改动）"""
        config = {"daily_anomaly": {"任务类型": "空幕", "空幕序号": 2}}
        changed = _update(self.cfg, config, "异象界域", "空幕", 2)
        self.assertFalse(changed)

    def test_update_task_none_raises(self):
        """异环要求 sequence 不能为 None"""
        config = {"daily_anomaly": {"空幕序号": 1}}
        with self.assertRaises(AssertionError):
            _update(self.cfg, config, "异象界域", "空幕", None)

    def test_update_task_unknown_daily_task_raises(self):
        config = {"daily_anomaly": {"未知序号": 1}}
        with self.assertRaisesRegex(AssertionError, "未声明的一级项"):
            _update(self.cfg, config, "异象界域", "不存在", "1")

    def test_update_task_all_mapped_tasks(self):
        """该日常声明里的每个副本都能正确更新（二级值取该副本声明的合法值）"""
        daily = self.cfg._dispatch_daily("异象界域")
        for task_name, seq_key in daily.option_fields.items():
            sequence = next(iter(daily._sequence_values[task_name].values()))
            config = {"daily_anomaly": {}}
            changed = _update(self.cfg, config, "异象界域", task_name, sequence)
            self.assertTrue(changed, f"{task_name} 未正确更新")
            self.assertEqual(config["daily_anomaly"][seq_key], sequence)

    def test_update_task_without_daily_raises(self):
        """异环两个日常分段，写路径必须显式给日常（不按副本名猜）。"""
        with self.assertRaisesRegex(AssertionError, "未知日常"):
            _update(self.cfg, {"daily_anomaly": {}}, None, "空幕", 3)

    def test_update_task_writes_own_daily_section(self):
        """写副本：落点由 daily_display_name 指定的日常决定。"""
        config = {"daily_anomaly": {"任务类型": "空幕", "空幕序号": 1}}
        changed = _update(self.cfg, config, "异象界域", "空幕", 5)
        self.assertTrue(changed)
        self.assertEqual(config["daily_anomaly"]["空幕序号"], 5)

    def _make_routine(self, anomaly_enabled=True, hunter_enabled=False):
        """构造 DailyRoutineTask.json 的 Routine Items（默认异象界域启用、追猎停用）。"""
        return {
            "Routine Items": [
                {"id": "daily_anomaly", "enabled": anomaly_enabled},
                {"id": "daily_anomaly_hunter", "enabled": hunter_enabled},
            ]
        }

    def _patch_load(self, main_config, routine):
        """主 config 返回 main_config，routine 开关文件返回 routine（模拟两份文件）。"""
        stack = ExitStack()
        stack.enter_context(
            patch.object(Daily, "_load_daily_config", return_value=main_config)
        )
        stack.enter_context(
            patch.object(Daily, "_load_routine_config", return_value=routine)
        )
        return stack

    def test_set_daily_task_with_sequence_saves(self):
        config = {"daily_anomaly": {"任务类型": "空幕", "空幕序号": 1}}
        routine = (
            self._make_routine()
        )  # 已对齐（异象界域启用、追猎停用）→ 不触发 routine 写盘
        mock_save = MagicMock()
        with (
            self._patch_load(config, routine),
            patch.object(Daily, "_save_daily_config", mock_save),
            patch.object(Daily, "_save_routine_config", mock_save),
        ):
            self.cfg.set_daily_task("异象界域", "空幕", 3)
        mock_save.assert_called_once()  # 仅主配置落盘，routine 已对齐无需更新
        saved = mock_save.call_args[0][0]
        self.assertEqual(saved["daily_anomaly"]["空幕序号"], 3)

    def test_set_daily_task_saves_and_enables_own_daily(self):
        """写副本：落到指定日常的段并启用它（无异动则不动第二份文件）。"""
        config = {"daily_anomaly": {"任务类型": "空幕", "空幕序号": 1}}
        routine = self._make_routine()
        mock_save = MagicMock()
        with (
            self._patch_load(config, routine),
            patch.object(Daily, "_save_daily_config", mock_save),
            patch.object(Daily, "_save_routine_config", mock_save),
        ):
            self.cfg.set_daily_task("异象界域", "空幕", 3)
        saved = mock_save.call_args[0][0]
        self.assertEqual(saved["daily_anomaly"]["空幕序号"], 3)

    def test_read_daily_task_explicit_daily_ignores_enabled_state(self):
        """指定日常时按该日常反读，不受 Routine Items 启用状态影响。"""
        config = {
            "daily_anomaly": {"任务类型": "空幕", "空幕序号": 3},
            "daily_anomaly_hunter": {"追猎目标": "音霸魔王"},
        }
        routine = self._make_routine(anomaly_enabled=True, hunter_enabled=False)
        with self._patch_load(config, routine):
            self.assertEqual(_read(self.cfg, "追猎目标"), ("追猎目标", "音霸魔王"))
            self.assertEqual(_read(self.cfg, "异象界域"), ("空幕", 3))
            # 是否启用不影响反读，走 _read_daily_tasks 记录里的 enabled
            enabled = {
                record["name"]: record["enabled"]
                for record in self.cfg._read_daily_tasks()
            }
            self.assertTrue(enabled["异象界域"])
            self.assertFalse(enabled["追猎目标"])

    def test_read_daily_tasks_returns_every_daily(self):
        """一次反读覆盖全部日常（副本/序列 + 开关），顺序与声明一致。"""
        config = {
            "daily_anomaly": {"任务类型": "空幕", "空幕序号": 6},
            "daily_anomaly_hunter": {"追猎目标": "围巢鸟"},
        }
        routine = self._make_routine(anomaly_enabled=True, hunter_enabled=False)
        with self._patch_load(config, routine):
            self.assertEqual(
                self.cfg._read_daily_tasks(),
                [
                    {
                        "name": "异象界域",
                        "task": "空幕",
                        "sequence": 6,
                        "enabled": True,
                    },
                    {
                        "name": "追猎目标",
                        "task": "追猎目标",
                        "sequence": "围巢鸟",
                        "enabled": False,
                    },
                ],
            )

    def test_read_daily_task_unknown_daily_raises(self):
        """未知日常展示名直接 assert，不静默回退。"""
        config = {"daily_anomaly": {"任务类型": "空幕", "空幕序号": 3}}
        with (
            self._patch_load(config, self._make_routine()),
            self.assertRaisesRegex(AssertionError, "未知日常"),
        ):
            _read(self.cfg, "不存在")

    def test_set_daily_task_hunt_writes_boss_and_enables_hunter(self):
        """选追猎目标（具体 boss）：在 daily_anomaly_hunter 写 追猎目标、启用 hunter，
        不改异象界域（任务类型与启用状态都保持原值）。"""
        config = {
            "daily_anomaly": {"任务类型": "空幕", "空幕序号": 1},
            "daily_anomaly_hunter": {"追猎目标": "音霸魔王"},
        }
        routine = self._make_routine()  # 当前异象界域启用、追猎停用
        mock_save = MagicMock()
        with (
            self._patch_load(config, routine),
            patch.object(Daily, "_save_daily_config", mock_save),
            patch.object(Daily, "_save_routine_config", mock_save),
        ):
            self.cfg.set_daily_task("追猎目标", "追猎目标", "无首铁驭")
        calls = mock_save.call_args_list
        self.assertEqual(len(calls), 2)  # 主配置 + routine 各一次
        saved = calls[0].args[0]
        self.assertEqual(saved["daily_anomaly_hunter"]["追猎目标"], "无首铁驭")
        self.assertEqual(saved["daily_anomaly"]["任务类型"], "空幕")  # 不写异象界域
        saved_routine = calls[1].args[0]
        enabled = {it["id"]: it["enabled"] for it in saved_routine["Routine Items"]}
        self.assertTrue(enabled["daily_anomaly_hunter"])
        self.assertTrue(enabled["daily_anomaly"])  # 另一个日常不动（互斥已取消）

    def test_set_daily_task_hunt_preserves_task_type(self):
        """选追猎目标后，daily_anomaly 的 任务类型 保持原值（不被写成追猎目标）。"""
        config = {
            "daily_anomaly": {"任务类型": "空幕"},
            "daily_anomaly_hunter": {"追猎目标": "音霸魔王"},
        }
        routine = self._make_routine()
        with (
            self._patch_load(config, routine),
            patch.object(Daily, "_save_daily_config"),
            patch.object(Daily, "_save_routine_config"),
        ):
            self.cfg.set_daily_task("追猎目标", "追猎目标", "音霸魔王")
        self.assertEqual(config["daily_anomaly"]["任务类型"], "空幕")

    def test_set_daily_task_anomaly_enables_without_touching_hunter(self):
        """选异象界域副本：启用 daily_anomaly；daily_anomaly_hunter 保持原启用状态。"""
        config = {"daily_anomaly": {"任务类型": "异能升级材料", "异能材料序号": 1}}
        routine = self._make_routine(anomaly_enabled=False, hunter_enabled=True)
        mock_save = MagicMock()
        with (
            self._patch_load(config, routine),
            patch.object(Daily, "_save_daily_config", mock_save),
            patch.object(Daily, "_save_routine_config", mock_save),
        ):
            self.cfg.set_daily_task("异象界域", "异能升级材料", 3)
        calls = mock_save.call_args_list
        self.assertEqual(len(calls), 2)  # 主配置 + routine 各一次
        saved_routine = calls[1].args[0]
        enabled = {it["id"]: it["enabled"] for it in saved_routine["Routine Items"]}
        self.assertTrue(enabled["daily_anomaly_hunter"])  # 另一个日常不动
        self.assertTrue(enabled["daily_anomaly"])
        saved_config = calls[0].args[0]
        self.assertEqual(saved_config["daily_anomaly"]["任务类型"], "异能升级材料")
        self.assertEqual(saved_config["daily_anomaly"]["异能材料序号"], 3)

    def test_set_daily_task_switch_and_sequence_writes_both(self):
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
        mock_save = MagicMock()
        with (
            self._patch_load(config, routine),
            patch.object(Daily, "_save_daily_config", mock_save),
            patch.object(Daily, "_save_routine_config", mock_save),
        ):
            self.cfg.set_daily_task("异象界域", "空幕", 3)
        mock_save.assert_called_once()  # 仅主配置落盘
        saved = mock_save.call_args[0][0]
        self.assertEqual(saved["daily_anomaly"]["任务类型"], "空幕")
        self.assertEqual(saved["daily_anomaly"]["空幕序号"], 3)  # 序号通道也被执行

    def test_update_task_writes_task_name(self):
        """任务类型写入 daily_anomaly 子对象（值即中文副本名）"""
        config = {"daily_anomaly": {"任务类型": "空幕"}}
        changed = _update(self.cfg, config, "异象界域", "异能升级材料", 1)
        self.assertTrue(changed)
        self.assertEqual(config["daily_anomaly"]["任务类型"], "异能升级材料")

    def test_missing_daily_section_raises(self):
        """顶层缺 daily_anomaly（旧版 DailyTask.json 结构）→ assert"""
        config = {"任务类型": "空幕"}
        with self.assertRaises(AssertionError):
            _update(self.cfg, config, "异象界域", "空幕", None)

    # ---- 日常开关（Routine Items）----

    def test_set_daily_enabled_turns_off_target_only(self):
        """停用某日常：只改它的 Routine Item，另一个保持原值，且不动副本选择。"""
        config = {"daily_anomaly": {"任务类型": "空幕", "空幕序号": 1}}
        routine = self._make_routine(anomaly_enabled=True, hunter_enabled=True)
        mock_save = MagicMock()
        with (
            self._patch_load(config, routine),
            patch.object(Daily, "_save_daily_config", mock_save),
            patch.object(Daily, "_save_routine_config", mock_save),
        ):
            self.cfg.set_daily_enabled("异象界域", False)
        saved_routine = mock_save.call_args[0][0]
        enabled = {it["id"]: it["enabled"] for it in saved_routine["Routine Items"]}
        self.assertFalse(enabled["daily_anomaly"])
        self.assertTrue(enabled["daily_anomaly_hunter"])  # 另一个不动
        self.assertEqual(config["daily_anomaly"]["空幕序号"], 1)  # 副本选择不动

    def test_set_daily_enabled_turns_back_on(self):
        """重新启用某日常：置 True 并落盘。"""
        routine = self._make_routine(anomaly_enabled=False, hunter_enabled=True)
        mock_save = MagicMock()
        with (
            self._patch_load({"daily_anomaly": {}}, routine),
            patch.object(Daily, "_save_daily_config", mock_save),
            patch.object(Daily, "_save_routine_config", mock_save),
        ):
            self.cfg.set_daily_enabled("异象界域", True)
        enabled = {
            it["id"]: it["enabled"] for it in mock_save.call_args[0][0]["Routine Items"]
        }
        self.assertTrue(enabled["daily_anomaly"])

    def test_set_daily_enabled_no_change_does_not_save(self):
        """已是目标状态时不落盘。"""
        routine = self._make_routine(anomaly_enabled=True)
        mock_save = MagicMock()
        with (
            self._patch_load({"daily_anomaly": {}}, routine),
            patch.object(Daily, "_save_daily_config", mock_save),
            patch.object(Daily, "_save_routine_config", mock_save),
        ):
            self.cfg.set_daily_enabled("异象界域", True)
        mock_save.assert_not_called()

    def test_set_daily_enabled_missing_routine_items_raises(self):
        with (
            self._patch_load({"daily_anomaly": {}}, {}),
            self.assertRaisesRegex(AssertionError, "缺少 Routine Items 字段"),
        ):
            self.cfg.set_daily_enabled("异象界域", False)

    def test_set_daily_enabled_unknown_daily_raises(self):
        """未知日常展示名直接 assert，不静默回退。"""
        with (
            self._patch_load({"daily_anomaly": {}}, self._make_routine()),
            self.assertRaisesRegex(AssertionError, "未知日常"),
        ):
            self.cfg.set_daily_enabled("不存在", False)

    def test_read_daily_tasks_reads_enabled_per_daily(self):
        """一次反读覆盖全部日常的启用状态（不看副本选择）。"""
        routine = self._make_routine(anomaly_enabled=False, hunter_enabled=True)
        with self._patch_load(
            {"daily_anomaly": {}, "daily_anomaly_hunter": {}}, routine
        ):
            enabled = {
                record["name"]: record["enabled"]
                for record in self.cfg._read_daily_tasks()
            }
            self.assertFalse(enabled["异象界域"])
            self.assertTrue(enabled["追猎目标"])

    def test_read_daily_tasks_without_routine_reports_none(self):
        """脚本未安装（routine 缺失）→ enabled None：无真相，不谎报「已停用」。"""
        with self._patch_load({"daily_anomaly": {}, "daily_anomaly_hunter": {}}, None):
            enabled = {
                record["name"]: record["enabled"]
                for record in self.cfg._read_daily_tasks()
            }
            self.assertIsNone(enabled["异象界域"])
            self.assertIsNone(enabled["追猎目标"])

    def test_update_sequence_hunt_writes_boss(self):
        """追猎目标经 _update_task 在 daily_anomaly_hunter 写 追猎目标（boss），不依赖 _bind_section。"""
        config = {"daily_anomaly_hunter": {"追猎目标": "音霸魔王"}}
        changed = _update(self.cfg, config, "追猎目标", "追猎目标", "海囚")
        self.assertTrue(changed)
        self.assertEqual(config["daily_anomaly_hunter"]["追猎目标"], "海囚")

    def test_update_task_skips_hunt(self):
        """追猎目标不写任务类型字段（仅写 boss 序号、不写 任务类型），不依赖 _bind_section。"""
        config = {
            "daily_anomaly": {"任务类型": "空幕"},
            "daily_anomaly_hunter": {"追猎目标": "音霸魔王"},
        }
        changed = _update(self.cfg, config, "追猎目标", "追猎目标", "海囚")
        self.assertTrue(changed)
        self.assertEqual(config["daily_anomaly"]["任务类型"], "空幕")

    def test_update_sequence_hunt_no_boss_raises(self):
        """未选具体 boss（sequence=None）→ assert。"""
        with self.assertRaises(AssertionError):
            _update(self.cfg, {}, "追猎目标", "追猎目标", None)


# ============================================================
# 明日方舟 ArknightsConfig（粥）
# ============================================================


class TestArknightsConfig(unittest.TestCase):
    """测试粥的 _is_aligned / _init_config / set_daily_task"""

    def _make_cfg(self):
        return ArknightsConfig()

    def test_init_attributes(self):
        cfg = self._make_cfg()
        self.assertEqual(cfg.display_name, "粥")
        self.assertEqual(
            [d.display_name for d in cfg._dailies], ["活动关卡", "理智作战", "剩余理智"]
        )

    def test_init_without_native_config_does_not_write(self):
        with (
            patch.object(Daily, "_load_daily_config", return_value=None),
            patch.object(Daily, "_save_daily_config") as save,
        ):
            ArknightsConfig()._init_config()
        save.assert_not_called()

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

    # ---- set_daily_task ----


class TestGetGameExePath(unittest.TestCase):
    """测试 ScriptConfig.get_game_exe_path：从各脚本游戏配置中提取游戏路径。"""

    def test_unadapted_base_returns_none(self):
        """基类未适配（_game_path_keys 为空）→ None，不触发任何读取"""
        with patch("src.config.set_config.get_daily_configs", return_value=[]):
            cfg = ScriptConfig()
        with patch("src.config.set_config.load_game_config") as mock_load:
            got = cfg.get_game_exe_path()
        self.assertIsNone(got)
        mock_load.assert_not_called()

    def test_ok_series_pc_full_path(self):
        """OK 系（ok-ww/ok-ef）读取 devices.json 的 pc_full_path。

        异环（ok-nte）已重写 get_game_exe_path 返回启动器路径，不在此列（见专项测试）。
        """
        for script_name in ("ok-ww", "ok-ef"):
            with patch(
                "src.config.set_config.load_game_config",
                return_value={
                    "preferred": "pc_1",
                    "pc_full_path": "D:\\Game\\game.exe",
                },
            ):
                got = set_config._CONFIGS[script_name]().get_game_exe_path()
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
            got = set_config.get_game_exe_path("ok-nte")
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
            got = set_config.get_game_exe_path("ok-nte")
        self.assertIsNone(got)

    def test_nte_game_exe_missing_returns_none(self):
        """异环游戏本体路径读不到（devices.json 缺失）→ None"""
        with patch("src.config.set_config.load_game_config", return_value=None):
            got = set_config.get_game_exe_path("ok-nte")
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
            got = set_config.get_game_exe_path("BetterGI")
        self.assertEqual(got, "D:\\Genshin\\YuanShen.exe")

    def test_game_path_top_level(self):
        """绝区零/崩铁读取顶层 game_path"""
        for script_name in ("OneDragon-Launcher", "March7th-Launcher"):
            with patch(
                "src.config.set_config.load_game_config",
                return_value={"game_path": "D:\\Game\\game.exe"},
            ):
                got = set_config._CONFIGS[script_name]().get_game_exe_path()
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
            got = set_config.get_game_exe_path("MAA")
        self.assertEqual(got, "C:\\MuMu\\#0 MuMu安卓设备.lnk")

    def test_missing_config_returns_none(self):
        """游戏配置文件缺失（load_game_config 返回 None）→ None"""
        with patch("src.config.set_config.load_game_config", return_value=None):
            got = set_config.get_game_exe_path("ok-ww")
        self.assertIsNone(got)

    def test_missing_field_returns_none(self):
        """配置中缺字段 → None"""
        with patch(
            "src.config.set_config.load_game_config",
            return_value={"other": "x"},
        ):
            got = set_config.get_game_exe_path("ok-ww")
        self.assertIsNone(got)

    def test_empty_value_returns_none(self):
        """字段值为空字符串 → None"""
        with patch(
            "src.config.set_config.load_game_config",
            return_value={"pc_full_path": ""},
        ):
            got = set_config.get_game_exe_path("ok-ww")
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


class TestSetConfigAdapter(unittest.TestCase):
    """测试适配器接口 set_config() 的分发逻辑"""

    def test_skip_when_task_name_none(self):
        """task_name 为 None 时直接返回，不调用适配器"""
        mock_instance = MagicMock()
        mock_factory = MagicMock(return_value=mock_instance)
        with patch.dict("src.config.set_config._CONFIGS", {"ok-ww": mock_factory}):
            set_config.set_config("ok-ww", task_name=None)
        mock_factory.assert_not_called()
        mock_instance.set_daily_task.assert_not_called()

    def test_skip_when_task_name_empty(self):
        """task_name 为空串时直接返回，不调用适配器"""
        mock_instance = MagicMock()
        mock_factory = MagicMock(return_value=mock_instance)
        with patch.dict("src.config.set_config._CONFIGS", {"ok-ww": mock_factory}):
            set_config.set_config("ok-ww", task_name="")
        mock_factory.assert_not_called()
        mock_instance.set_daily_task.assert_not_called()

    def test_skip_when_task_name_unselected(self):
        """task_name 为「未选择」时直接返回，不调用适配器"""
        mock_instance = MagicMock()
        mock_factory = MagicMock(return_value=mock_instance)
        with patch.dict("src.config.set_config._CONFIGS", {"ok-ww": mock_factory}):
            set_config.set_config("ok-ww", task_name="未选择")
        mock_factory.assert_not_called()
        mock_instance.set_daily_task.assert_not_called()

    def test_unknown_process_skips_gracefully(self):
        """未注册（自定义）进程即使带副本也优雅跳过，不报错、不实例化任何子类"""
        mock_instance = MagicMock()
        mock_factory = MagicMock(return_value=mock_instance)
        # 已注册脚本作为「无关脚本」在场：未知标识不得命中任何子类
        with patch.dict("src.config.set_config._CONFIGS", {"ok-ww": mock_factory}):
            set_config.set_config("不存在", task_name="副本", sequence="序列")
        mock_factory.assert_not_called()
        mock_instance.set_daily_task.assert_not_called()

    def test_unknown_process_does_not_touch_registry(self):
        """未注册进程不会命中注册表中的任何子类"""
        mock_instance = MagicMock()
        mock_factory = MagicMock(return_value=mock_instance)
        with patch.dict("src.config.set_config._CONFIGS", {"ok-ww": mock_factory}):
            set_config.set_config("自定义脚本", task_name="副本")
        mock_factory.assert_not_called()
        mock_instance.set_daily_task.assert_not_called()

    def test_dispatches_to_correct_subclass(self):
        """验证 set_config 正确分发到对应子类（日常名一并透传，顺序为日常→副本→序列）"""
        mock_instance = MagicMock()
        mock_factory = MagicMock(return_value=mock_instance)
        with patch.dict("src.config.set_config._CONFIGS", {"ok-ww": mock_factory}):
            set_config.set_config(
                "ok-ww",
                daily_display_name="每日任务",
                task_name="无音区",
                sequence="1",
            )
        mock_factory.assert_called_once()
        mock_instance.set_daily_task.assert_called_once_with("每日任务", "无音区", "1")
