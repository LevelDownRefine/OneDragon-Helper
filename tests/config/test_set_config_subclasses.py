"""
测试 set_config.py 中各 ScriptConfig 子类的行为。

覆盖各脚本的日常更新、开关互不干扰、模板对齐和初始化。
所有文件 I/O 均通过 mock 隔离，不依赖真实 config 文件。
"""

import json
import unittest
from contextlib import ExitStack
from unittest.mock import MagicMock, mock_open, patch

from src.config import set_config
from src.config.daily import Daily, TemplateDaily
from src.config.set_config import (
    ArknightsConfig,
    EndfieldConfig,
    GenshinConfig,
    NTEConfig,
    StarRailConfig,
    WutheringWavesConfig,
    ZenlessZoneZeroConfig,
)


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

    def test_daily_update_and_repeat_are_idempotent(self):
        cases = (
            (
                "模拟领域",
                "共鸣者经验",
                "Simulation Challenge",
                "Material Selection",
                "Resonator EXP",
            ),
            (
                "模拟领域",
                "武器经验",
                "Simulation Challenge",
                "Material Selection",
                "Weapon EXP",
            ),
            ("无音区", 3, "Tacet Suppression", "Which Tacet Suppression to Farm", 3),
            ("无音区", 2, "Tacet Suppression", "Which Tacet Suppression to Farm", 2),
            ("凝素领域", 4, "Forgery Challenge", "Which Forgery Challenge to Farm", 4),
            ("凝素领域", 2, "Forgery Challenge", "Which Forgery Challenge to Farm", 2),
        )
        for task, sequence, physical_task, field, physical_sequence in cases:
            with self.subTest(task=task, sequence=sequence):
                config = {"Which to Farm": "old", "unrelated": {"keep": True}}
                expected = {
                    "Which to Farm": physical_task,
                    field: physical_sequence,
                    "unrelated": {"keep": True},
                }
                daily = self.cfg._dispatch_daily("每日任务")
                with (
                    patch.object(daily, "_load_daily_config", return_value=config),
                    patch.object(daily, "_save_daily_config") as save,
                ):
                    self.assertTrue(daily.update(task, sequence))
                    self.assertEqual(config, expected)
                    save.assert_called_once_with(expected)
                    save.reset_mock()
                    self.assertFalse(daily.update(task, sequence))
                    self.assertEqual(config, expected)
                    save.assert_not_called()

    def test_update_sequence_simulation_unknown_raises(self):
        config = {"Which to Farm": "Simulation Challenge", "Material Selection": "old"}
        with self.assertRaises(AssertionError):
            _update(self.cfg, config, "每日任务", "模拟领域", "不存在")

    def test_update_sequence_none_raises(self):
        config = {"Which to Farm": "Simulation Challenge"}
        with self.assertRaises(AssertionError):
            _update(self.cfg, config, "每日任务", "模拟领域", None)

    def test_update_sequence_unknown_daily_task_type_raises(self):
        config = {"Which to Farm": "Unknown Type"}
        with self.assertRaises(AssertionError):
            _update(self.cfg, config, "每日任务", "未知", "1")

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


class TestEndfieldConfig(unittest.TestCase):
    def test_init_attributes(self):
        with patch.object(EndfieldConfig, "_init_config"):
            cfg = EndfieldConfig()
        self.assertEqual(cfg.display_name, "终末地")
        self.assertEqual(cfg._script_name, "ok-ef")
        self.assertEqual(cfg._dispatch_daily("每日任务").task_field, "体力本")
        self.assertEqual(cfg._template_rel_path, "okef一条龙.json")

    def test_daily_selection_saves_leaf_and_preserves_enable_switch(self):
        for task, sequence, expected in (
            ("干员养成", None, "干员养成"),
            ("能量淤积点", "枢纽区", "枢纽区"),
        ):
            with self.subTest(task=task, sequence=sequence):
                with patch.object(EndfieldConfig, "_init_config"):
                    config = EndfieldConfig()
                current = {"体力本": "旧本", "⭐刷体力": True}
                with (
                    patch.object(Daily, "_load_daily_config", return_value=current),
                    patch.object(Daily, "_save_daily_config") as save,
                ):
                    config.set_daily_task("每日任务", task, sequence=sequence)
                save.assert_called_once_with({"体力本": expected, "⭐刷体力": True})

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


class TestZenlessZoneZeroConfig(unittest.TestCase):
    """绝区零不再走模板初始化：模板写入改由「每日任务」在保存配置时驱动。"""

    def test_init_attributes(self):
        cfg = ZenlessZoneZeroConfig()
        self.assertEqual(cfg.display_name, "绝区零")
        self.assertEqual(cfg._script_name, "OneDragon-Launcher")
        self.assertFalse(cfg._template_rel_path)
        daily = cfg._dispatch_daily("每日任务")
        self.assertIsInstance(daily, TemplateDaily)
        self.assertFalse(daily.option_fields, "日常无字段落点")


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

    def test_selection_saves_config_and_enables_only_its_own_routine_item(self):
        for already_enabled in (False, True):
            with self.subTest(already_enabled=already_enabled):
                config = {"daily_anomaly": {"任务类型": "空幕", "空幕序号": 1}}
                routine = self._make_routine(anomaly_enabled=already_enabled)
                with (
                    self._patch_load(config, routine),
                    patch.object(Daily, "_save_daily_config") as save_config,
                    patch.object(Daily, "_save_routine_config") as save_routine,
                ):
                    self.cfg.set_daily_task("异象界域", "空幕", 3)
                save_config.assert_called_once_with(
                    {"daily_anomaly": {"任务类型": "空幕", "空幕序号": 3}}
                )
                expected = self._make_routine(
                    anomaly_enabled=True, hunter_enabled=False
                )
                self.assertEqual(routine, expected)
                if already_enabled:
                    save_routine.assert_not_called()
                else:
                    save_routine.assert_called_once_with(expected)

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

    def test_hunter_update_preserves_the_other_daily_section(self):
        for anomaly in (None, {"任务类型": "空幕"}):
            with self.subTest(anomaly=anomaly):
                config = {"daily_anomaly_hunter": {"追猎目标": "音霸魔王"}}
                if anomaly is not None:
                    config["daily_anomaly"] = anomaly.copy()
                expected = {"daily_anomaly_hunter": {"追猎目标": "海囚"}}
                if anomaly is not None:
                    expected["daily_anomaly"] = anomaly.copy()
                self.assertTrue(
                    _update(self.cfg, config, "追猎目标", "追猎目标", "海囚")
                )
                self.assertEqual(config, expected)

    def test_update_sequence_hunt_no_boss_raises(self):
        """未选具体 boss（sequence=None）→ assert。"""
        with self.assertRaises(AssertionError):
            _update(self.cfg, {}, "追猎目标", "追猎目标", None)


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

    def test_template_alignment_cases(self):
        cases = (
            (
                "identical",
                {
                    "Configurations": {
                        "Default": {
                            "TaskQueue": [
                                {
                                    "Name": "开始唤醒",
                                    "$type": "StartUpTask",
                                    "ExtraKey": 1,
                                },
                                {
                                    "Name": "剿灭",
                                    "$type": "FightTask",
                                    "StagePlan": ["Annihilation"],
                                    "IsEnable": True,
                                },
                            ]
                        }
                    }
                },
                {
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
                },
                True,
            ),
            (
                "name_mismatch",
                {
                    "Configurations": {
                        "Default": {
                            "TaskQueue": [{"Name": "红票", "$type": "FightTask"}]
                        }
                    }
                },
                {
                    "Configurations": {
                        "Default": {
                            "TaskQueue": [{"Name": "剿灭", "$type": "FightTask"}]
                        }
                    }
                },
                False,
            ),
            (
                "type_mismatch",
                {
                    "Configurations": {
                        "Default": {
                            "TaskQueue": [{"Name": "剿灭", "$type": "StartUpTask"}]
                        }
                    }
                },
                {
                    "Configurations": {
                        "Default": {
                            "TaskQueue": [{"Name": "剿灭", "$type": "FightTask"}]
                        }
                    }
                },
                False,
            ),
            (
                "stageplan_mismatch",
                {
                    "Configurations": {
                        "Default": {
                            "TaskQueue": [
                                {
                                    "Name": "剿灭",
                                    "$type": "FightTask",
                                    "StagePlan": ["AP-5"],
                                }
                            ]
                        }
                    }
                },
                {
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
                },
                False,
            ),
            (
                "cur_shorter_returns_false",
                {
                    "Configurations": {
                        "Default": {"TaskQueue": [{"Name": "A", "$type": "X"}]}
                    }
                },
                {
                    "Configurations": {
                        "Default": {
                            "TaskQueue": [
                                {"Name": "A", "$type": "X"},
                                {"Name": "B", "$type": "Y"},
                            ]
                        }
                    }
                },
                False,
            ),
            (
                "cur_longer_ok",
                {
                    "Configurations": {
                        "Default": {
                            "TaskQueue": [
                                {"Name": "A", "$type": "X"},
                                {"Name": "B", "$type": "Y"},
                            ]
                        }
                    }
                },
                {
                    "Configurations": {
                        "Default": {"TaskQueue": [{"Name": "A", "$type": "X"}]}
                    }
                },
                True,
            ),
            (
                "non_fight_task_skips_stageplan",
                {
                    "Configurations": {
                        "Default": {
                            "TaskQueue": [{"Name": "自动公招", "$type": "RecruitTask"}]
                        }
                    }
                },
                {
                    "Configurations": {
                        "Default": {
                            "TaskQueue": [{"Name": "自动公招", "$type": "RecruitTask"}]
                        }
                    }
                },
                True,
            ),
        )
        cfg = self._make_cfg()
        for case, config, template, expected in cases:
            with self.subTest(case=case):
                self.assertIs(cfg._is_aligned(config, template), expected)
