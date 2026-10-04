"""周常落点（``src.config.weekly``）：声明校验、装配、支持查询与各周常的落点读写。

一条周常一个对象（崩铁三条各一个），故测试按「脚本 + 周常展示名」取对象。
"""

import os
import unittest
from copy import deepcopy
from functools import cache
from unittest.mock import patch

from src.config import set_config as config_mod
from src.config import weekly as weekly_mod
from src.config.daily_config import get_weekly_map
from src.config.set_config import _CONFIGS, ScriptConfig, weekly_names
from src.config.weekly import Weekly
from src.service.run_actions import apply_subscript_config
from src.utils.utils_weekly import DISABLED_START_DAY


def _weekly(script_name: str, weekly_name: str) -> Weekly:
    """按脚本 + 周常展示名取已装配的周常对象。"""
    for weekly in _CONFIGS[script_name]()._weeklies:
        if weekly.display_name == weekly_name:
            return weekly
    raise AssertionError(f"未找到周常: {script_name}/{weekly_name}")


class WeeklyTestCase(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(_CONFIGS))
        for name, factory in tuple(_CONFIGS.items()):
            _CONFIGS[name] = cache(factory.__wrapped__)
        # 只隔离构造期原生 I/O，每例使用全新的适配器与任务对象。
        self.enterContext(
            patch("src.config.daily.load_script_config", return_value=None)
        )


class TestWeeklyDeclaration(WeeklyTestCase):
    """声明的机制类与文件路径声明。"""

    def test_every_declaration_has_registered_class_and_config(self):
        """每条周常都必须声明已注册的 class 与带扩展名的 config。"""
        for script_name, declarations in config_mod.load_weekly_map().items():
            for declaration in declarations:
                with self.subTest(
                    script=script_name, weekly=declaration["display_name"]
                ):
                    self.assertIn(declaration["class"], weekly_mod.WEEKLY_CLASSES)
                    rel = declaration["config"]
                    self.assertIn(
                        os.path.splitext(rel)[1].lower(), (".json", ".yaml", ".yml")
                    )

    def test_registry_keys_are_class_names(self):
        """注册表键即类名（声明用类名引用）。"""
        for name, cls in weekly_mod.WEEKLY_CLASSES.items():
            self.assertEqual(name, cls.__name__)

    def test_menu_strips_code_fields(self):
        """物化后的周常菜单不含 class / config（代码耦合字段不入 UI 词汇）。"""
        # 隔离本地资源读取：CI 无 config.yml，不能走到真实脚本根目录解析。
        with patch("src.config.daily_config.read_task_source", return_value=[]):
            for script_name in config_mod.load_weekly_map():
                for menu in get_weekly_map(script_name):
                    with self.subTest(script=script_name):
                        self.assertNotIn("class", menu)
                        self.assertNotIn("config", menu)


class TestWeeklyAssembly(WeeklyTestCase):
    """装配：构造函数按声明建对象，ScriptConfig 构造期持有。"""

    def test_one_object_per_declaration(self):
        """一个脚本的周常对象数 = 声明条数（崩铁两条各一个对象）。"""
        for script_name, declarations in config_mod.load_weekly_map().items():
            with self.subTest(script=script_name):
                built = _CONFIGS[script_name]()._weeklies
                self.assertEqual(len(built), len(declarations))
                self.assertEqual(
                    [w.display_name for w in built],
                    [d["display_name"] for d in declarations],
                )

    def test_scripts_without_declaration_build_empty(self):
        with patch.object(config_mod.GenshinConfig, "_init_config") as initialize:
            config = config_mod.GenshinConfig()
        self.assertEqual(config._weeklies, [])
        self.assertTrue(config._dailies)
        initialize.assert_called_once_with()
        self.assertEqual(weekly_names("BetterGI"), [])

    def test_daily_and_weekly_physical_names_are_independent(self):
        declarations = deepcopy(config_mod.load_weekly_map())
        daily_name = config_mod.WutheringWavesConfig()._dailies[0].physical_name
        declarations["ok-ww"][0]["physical_name"] = daily_name
        with patch.object(weekly_mod, "load_weekly_map", return_value=declarations):
            config = config_mod.WutheringWavesConfig()
        self.assertEqual(config._dailies[0].physical_name, daily_name)
        self.assertEqual(config._weeklies[0].physical_name, daily_name)
        self.assertEqual(config._weeklies[0].script_display_name, "鸣潮")

    def test_instances_own_independent_weeklies(self):
        first = config_mod.WutheringWavesConfig()
        second = config_mod.WutheringWavesConfig()
        self.assertIsNot(first._weeklies, second._weeklies)
        self.assertIsNot(first._weeklies[0], second._weeklies[0])
        self.assertEqual(first._weeklies[0].script_display_name, "鸣潮")
        self.assertIs(_CONFIGS["ok-ww"](), _CONFIGS["ok-ww"]())

    def test_config_holds_weeklies(self):
        """ScriptConfig 构造期装配并持有周常对象（与日常同一时机）。"""
        # 屏蔽模板对齐：CI 无 config.yml，未命中缓存的脚本不能走到真实读盘。
        with patch.object(ScriptConfig, "_init_config"):
            for script_name, factory in _CONFIGS.items():
                with self.subTest(script=script_name):
                    self.assertEqual(
                        [w.display_name for w in factory()._weeklies],
                        weekly_names(script_name),
                    )

    def test_unknown_class_raises(self):
        declarations = {
            "ok-ww": [{"display_name": "周常", "class": "没有的类", "config": "c.json"}]
        }
        with (
            patch.object(weekly_mod, "load_weekly_map", return_value=declarations),
            self.assertRaisesRegex(AssertionError, "未知的周常机制类"),
        ):
            config_mod.WutheringWavesConfig()

    def test_duplicate_physical_name_raises(self):
        declarations = {
            "ok-ww": [
                {
                    "display_name": "甲",
                    "physical_name": "X",
                    "class": "WutheringWavesWeekly",
                    "config": "c.json",
                    "key": "k",
                },
                {
                    "display_name": "乙",
                    "physical_name": "X",
                    "class": "WutheringWavesWeekly",
                    "config": "c.json",
                    "key": "k",
                },
            ]
        }
        with (
            patch.object(weekly_mod, "load_weekly_map", return_value=declarations),
            self.assertRaisesRegex(AssertionError, "周常物理名重复"),
        ):
            config_mod.WutheringWavesConfig()


class TestSupportsWeekly(WeeklyTestCase):
    """周常支持查询：supports_weekly"""

    def test_unknown_script_returns_false(self):
        """未声明周常的脚本 → False"""
        self.assertFalse(config_mod.supports_weekly("不存在"))
        self.assertFalse(config_mod.supports_weekly("BetterGI"))

    def test_metadata_queries_do_not_construct_configs(self):
        with patch.dict(
            _CONFIGS,
            {"ok-ww": lambda: self.fail("名称查询不能构造适配器")},
            clear=True,
        ):
            self.assertEqual(weekly_names("ok-ww"), ["幻梦游园"])
            self.assertTrue(config_mod.supports_weekly("ok-ww"))

    def test_supported_are_the_four_weekly_scripts(self):
        """适配周常的是鸣潮/绝区零/崩铁/粥四个。"""
        expected = {
            "ok-ww",
            "OneDragon-Launcher",
            "March7th-Launcher",
            "MAA",
        }
        self.assertEqual(set(config_mod.load_weekly_map()), expected)
        for name in expected:
            self.assertTrue(config_mod.supports_weekly(name), f"{name} 应支持周常")


class TestWeeklyStartDay(WeeklyTestCase):
    """按周几起（start_day）写落点：六条周常各形态。"""

    # ---- 基类 ----

    def test_base_unsupported_raises(self):
        """基类无落点 → prepare_start_day assert"""
        base = Weekly("测试", {"display_name": "周常", "config": "c.json"}, "测试")
        with self.assertRaises(AssertionError):
            base.prepare_start_day(4)

    def test_invalid_start_day_is_rejected_before_io(self):
        cases = (
            ("March7th-Launcher", "货币战争", "prepare_start_day"),
            ("March7th-Launcher", "历战余响", "set_start_day"),
            ("MAA", "理智药剂", "set_start_day"),
        )
        for script, name, method in cases:
            weekly = _weekly(script, name)
            for bad in (-1, 8, 99):
                with (
                    self.subTest(weekly=name, method=method, day=bad),
                    patch.object(weekly, "_load_config") as load,
                    patch.object(weekly, "_save_config") as save,
                ):
                    with self.assertRaisesRegex(AssertionError, "非法周常起始日"):
                        getattr(weekly, method)(bad)
                    load.assert_not_called()
                    save.assert_not_called()

    # ---- 崩铁布尔开关（按日期折算）----

    def test_star_rail_boolean_weeklies_follow_start_day(self):
        for name, key in (
            ("货币战争", "currencywars_enable"),
            ("模拟宇宙", "universe_enable"),
        ):
            weekly = _weekly("March7th-Launcher", name)
            for today, start_day, enabled in (
                (3, 4, True),
                (1, 4, False),
                (6, 0, False),
            ):
                for unchanged in (False, True):
                    with self.subTest(
                        weekly=name,
                        today=today,
                        start_day=start_day,
                        unchanged=unchanged,
                    ):
                        config = {
                            "currencywars_enable": True,
                            "universe_enable": True,
                            "echo_of_war_start_day_of_week": 1,
                        }
                        config[key] = enabled if unchanged else not enabled
                        expected = {**config, key: enabled}
                        with (
                            patch(
                                "src.utils.utils_weekly.get_week_num",
                                return_value=today,
                            ),
                            patch.object(weekly, "_load_config", return_value=config),
                            patch.object(weekly, "_save_config") as save,
                        ):
                            weekly.prepare_start_day(start_day)
                        self.assertEqual(config, expected)
                        save.assert_called_once_with(expected)

    # ---- 崩铁·历战余响：字面起始日（不按日期折算）----

    def test_echo_of_war_writes_literal_day(self):
        """无论今天周几都写字面起始日，且不碰 currencywars_enable"""
        weekly = _weekly("March7th-Launcher", "历战余响")
        config = {"currencywars_enable": True, "echo_of_war_start_day_of_week": 1}
        with (
            patch.object(weekly, "_load_config", return_value=config),
            patch.object(weekly, "_save_config") as mock_save,
        ):
            weekly.prepare_start_day(5)
        self.assertEqual(config["echo_of_war_start_day_of_week"], 5)
        self.assertTrue(config["echo_of_war_enable"])  # 选周几即开总开关
        self.assertTrue(config["currencywars_enable"])
        mock_save.assert_called_once()

    def test_echo_of_war_disabled_keeps_literal_day(self):
        """不启用（0）→ 只关总开关，字面起始日保留（便于再启用）"""
        weekly = _weekly("March7th-Launcher", "历战余响")
        config = {
            "currencywars_enable": True,
            "echo_of_war_enable": True,
            "echo_of_war_start_day_of_week": 5,
        }
        with (
            patch.object(weekly, "_load_config", return_value=config),
            patch.object(weekly, "_save_config") as mock_save,
        ):
            weekly.prepare_start_day(DISABLED_START_DAY)
        self.assertFalse(config["echo_of_war_enable"])
        self.assertEqual(config["echo_of_war_start_day_of_week"], 5)
        mock_save.assert_called_once()

    # ---- 鸣潮：Additional Tasks 列表增删 ----

    def test_ww_weekly_membership_changes_only_when_needed(self):
        task = "Check Weekly Garden"
        other = "Merge Echo If discarded > 1000"
        key = "Additional Tasks to Run After Daily Task"
        for name, day, before, after, changed in (
            ("enable", 3, [other], [other, task], True),
            ("disable", 1, [task, other], [other], True),
            ("unchanged", 3, [task], [task], False),
        ):
            with self.subTest(name=name):
                weekly = _weekly("ok-ww", "幻梦游园")
                config = {key: list(before)}
                with (
                    patch("src.utils.utils_weekly.get_week_num", return_value=day),
                    patch.object(weekly, "_load_config", return_value=config),
                    patch.object(weekly, "_save_config") as save,
                ):
                    weekly.prepare_start_day(4)
                self.assertEqual(config, {key: after})
                self.assertEqual(save.call_count, int(changed))

    def test_ww_missing_tasks_key_raises(self):
        """鸣潮 config 缺 Additional Tasks 字段 → assert"""
        weekly = _weekly("ok-ww", "幻梦游园")
        with (
            patch("src.utils.utils_weekly.get_week_num", return_value=3),
            patch.object(weekly, "_load_config", return_value={}),
            self.assertRaises(AssertionError),
        ):
            weekly.prepare_start_day(4)

    # ---- 绝区零：_group.yml 的 lost_void.enabled ----

    def test_zzz_weekly_switch_preserves_other_apps(self):
        for day, enabled in ((3, True), (1, False)):
            with self.subTest(day=day):
                weekly = _weekly("OneDragon-Launcher", "迷失之地")
                other = {"app_id": "notorious_hunt", "enabled": True}
                config = {
                    "app_list": [
                        dict(other),
                        {"app_id": "lost_void", "enabled": not enabled},
                    ]
                }
                with (
                    patch("src.utils.utils_weekly.get_week_num", return_value=day),
                    patch.object(weekly, "_load_config", return_value=config),
                    patch.object(weekly, "_save_config") as save,
                ):
                    weekly.prepare_start_day(4)
                self.assertEqual(
                    config,
                    {"app_list": [other, {"app_id": "lost_void", "enabled": enabled}]},
                )
                save.assert_called_once()

    def test_zzz_missing_app_id_raises(self):
        """app_list 缺 lost_void → assert"""
        weekly = _weekly("OneDragon-Launcher", "迷失之地")
        config = {"app_list": [{"app_id": "other", "enabled": True}]}
        with (
            patch("src.utils.utils_weekly.get_week_num", return_value=3),
            patch.object(weekly, "_load_config", return_value=config),
            self.assertRaises(AssertionError),
        ):
            weekly.prepare_start_day(4)

    # ---- 粥：理智药剂（UseExpiringMedicine + MedicineExpireDays）----

    def _maa_queue(self, enabled_names):
        """构造 gui.new.json 风格的 TaskQueue：FightTask 的 IsEnable 由 enabled_names 决定。"""
        names = ["剿灭", "红票", "经验", "土", "活动土"]
        tasks = [{"$type": "StartUpTask", "Name": "开始唤醒", "IsEnable": True}]
        for name in names:
            task = {"$type": "FightTask", "Name": name}
            task["IsEnable"] = name in enabled_names
            tasks.append(task)
        return tasks

    def _maa_config(self, enabled_names):
        return {
            "Configurations": {"Default": {"TaskQueue": self._maa_queue(enabled_names)}}
        }

    def test_arknights_weekly_syncs_use_expiring_medicine(self):
        """所有 FightTask 的临期药常开，不随任务启停变化。"""
        weekly = _weekly("MAA", "理智药剂")
        config = self._maa_config({"剿灭", "土", "活动土"})
        with (
            patch.object(weekly, "_load_config", return_value=config),
            patch.object(weekly, "_save_config") as mock_save,
        ):
            weekly.prepare_start_day(3)
        by_name = {
            t["Name"]: t
            for t in config["Configurations"]["Default"]["TaskQueue"]
            if t.get("$type") == "FightTask"
        }
        self.assertTrue(by_name["剿灭"]["UseExpiringMedicine"])
        self.assertTrue(by_name["土"]["UseExpiringMedicine"])
        self.assertTrue(by_name["活动土"]["UseExpiringMedicine"])
        self.assertTrue(by_name["红票"]["UseExpiringMedicine"])
        self.assertTrue(by_name["经验"]["UseExpiringMedicine"])
        mock_save.assert_called_once()

    def test_arknights_weekly_annihilation_uses_shared_medicine_window(self):
        """剿灭与普通战斗使用同一个临期窗口。"""
        weekly = _weekly("MAA", "理智药剂")
        config = self._maa_config({"剿灭"})
        with (
            patch.object(weekly, "_load_config", return_value=config),
            patch.object(weekly, "_save_config"),
        ):
            weekly.prepare_start_day(2)
        annih = next(
            t
            for t in config["Configurations"]["Default"]["TaskQueue"]
            if t["Name"] == "剿灭"
        )
        self.assertTrue(annih["IsEnable"], "剿灭应照常开启运行")
        self.assertTrue(annih["UseExpiringMedicine"])
        self.assertEqual(annih["MedicineExpireDays"], 6)  # 周几起=2 ⇒ 8-2

    def test_arknights_weekly_expire_days_from_start_day(self):
        """MedicineExpireDays = 8 - 周几起：周几起=1→7，周几起=7→1，周几起=3→5"""
        weekly = _weekly("MAA", "理智药剂")
        for start_day, expect in ((1, 7), (3, 5), (7, 1)):
            with self.subTest(start_day=start_day):
                config = self._maa_config({"土"})
                with (
                    patch.object(weekly, "_load_config", return_value=config),
                    patch.object(weekly, "_save_config"),
                ):
                    weekly.prepare_start_day(start_day)
                tasks = config["Configurations"]["Default"]["TaskQueue"]
                for t in tasks:
                    if t.get("$type") == "FightTask":
                        self.assertEqual(t["MedicineExpireDays"], expect)

    def test_arknights_weekly_ignores_non_fight_task(self):
        """StartUpTask 等非 FightTask 不受 UseExpiringMedicine/MedicineExpireDays 影响"""
        weekly = _weekly("MAA", "理智药剂")
        config = self._maa_config({"土"})
        with (
            patch.object(weekly, "_load_config", return_value=config),
            patch.object(weekly, "_save_config"),
        ):
            weekly.prepare_start_day(3)
        startup = next(
            t
            for t in config["Configurations"]["Default"]["TaskQueue"]
            if t.get("$type") != "FightTask"
        )
        self.assertNotIn("UseExpiringMedicine", startup)
        self.assertNotIn("MedicineExpireDays", startup)

    def test_arknights_weekly_no_change_skips_save(self):
        """临期药已常开且窗口一致时不重复落盘。"""
        weekly = _weekly("MAA", "理智药剂")
        config = self._maa_config({"剿灭", "土", "活动土"})
        for t in config["Configurations"]["Default"]["TaskQueue"]:
            if t.get("$type") == "FightTask":
                t["UseExpiringMedicine"] = True
                t["MedicineExpireDays"] = 8 - 3  # 周几起=3
        with (
            patch.object(weekly, "_load_config", return_value=config),
            patch.object(weekly, "_save_config") as mock_save,
        ):
            weekly.prepare_start_day(3)
        mock_save.assert_not_called()

    def test_arknights_start_day_writes_expire_days_only(self):
        """set_start_day 只写 MedicineExpireDays（= 8 - 周几起），不动 UseExpiringMedicine。"""
        weekly = _weekly("MAA", "理智药剂")
        config = self._maa_config({"土"})
        for t in config["Configurations"]["Default"]["TaskQueue"]:
            if t.get("$type") == "FightTask":
                t["UseExpiringMedicine"] = "SHOULD_NOT_CHANGE"
                t["MedicineExpireDays"] = 99
        with (
            patch.object(weekly, "_load_config", return_value=config),
            patch.object(weekly, "_save_config") as mock_save,
        ):
            weekly.set_start_day(3)  # 周几起=3 ⇒ MedicineExpireDays=5
        mock_save.assert_called_once()
        tasks = config["Configurations"]["Default"]["TaskQueue"]
        for t in tasks:
            if t.get("$type") == "FightTask":
                self.assertEqual(t["MedicineExpireDays"], 5)
                self.assertEqual(t["UseExpiringMedicine"], "SHOULD_NOT_CHANGE")


class TestEchoOfWarEditTime(WeeklyTestCase):
    """崩铁·历战余响的编辑期落盘（总开关 + 字面起始日）。"""

    def test_set_start_day_writes_echo_field_only(self):
        """set_start_day 只写 echo 起始日字段，不动货币战争的开关字段。"""
        weekly = _weekly("March7th-Launcher", "历战余响")
        config: dict = {"currencywars_enable": True}
        with (
            patch.object(weekly, "_load_config", return_value=config),
            patch.object(weekly, "_save_config") as mock_save,
        ):
            weekly.set_start_day(4)
        mock_save.assert_called_once()
        self.assertEqual(config["echo_of_war_start_day_of_week"], 4)
        self.assertTrue(config["currencywars_enable"])

    def test_set_start_day_reads_strictly(self):
        """写路径须按 load_script_config 的写路径契约读取（allow_missing=False）。"""
        weekly = _weekly("March7th-Launcher", "历战余响")
        seen = {}

        def fake_load(script_name, display_name, rel_path, *, allow_missing=False):
            seen["allow_missing"] = allow_missing
            return {"currencywars_enable": True}

        with (
            patch.object(weekly_mod, "load_script_config", fake_load),
            patch.object(weekly, "_save_config"),
        ):
            weekly.set_start_day(4)
        self.assertFalse(seen["allow_missing"], "写路径不得按「未设置」语义读 config")

    def test_set_start_day_refuses_unreadable_config(self):
        """config 读不出来（缺失/损坏）→ 直接报错且不写盘。

        回归：曾用 allow_missing 读，读不出来时会把整份 config 覆盖成只剩起始日字段的
        存根，静默毁掉游戏侧配置。
        """
        weekly = _weekly("March7th-Launcher", "历战余响")
        with (
            patch.object(
                weekly_mod,
                "load_script_config",
                side_effect=AssertionError("config 文件不存在"),
            ),
            patch.object(weekly, "_save_config") as mock_save,
            self.assertRaises(AssertionError),
        ):
            weekly.set_start_day(4)
        mock_save.assert_not_called()


class TestWeeklyAdapter(WeeklyTestCase):
    """模块级入口：按名分发、未适配 / 无此能力时优雅跳过。"""

    def test_all_entries_use_the_cached_script_owned_objects(self):
        class SelectableWeekly(Weekly):
            def set_task(self, task_name):
                self.task = task_name

            def read_task(self):
                return self.task

            def set_start_day(self, start_day):
                self.start_day = start_day

            def prepare_start_day(self, start_day):
                self.prepared_day = start_day

        owner = _CONFIGS["ok-ww"]()
        owned = SelectableWeekly(
            "ok-ww", {"display_name": "独有周常", "config": "weekly.json"}, "鸣潮"
        )
        owner._weeklies = [owned]
        daily = owner._dailies[0]
        with (
            patch.object(daily, "update") as update,
            patch.object(daily, "set_enabled") as enable,
        ):
            config_mod.set_config("ok-ww", daily.display_name, "材料", 1)
            config_mod.set_weekly_task("ok-ww", "独有周常", "副本")
            config_mod.set_weekly_start_day("ok-ww", "独有周常", 4)
            apply_subscript_config({"ok-ww"}, {"ok-ww": {"独有周常": 0}})
            self.assertEqual(config_mod.get_weekly_task("ok-ww", "独有周常"), "副本")
        update.assert_called_once_with("材料", 1)
        enable.assert_called_once_with(True)
        self.assertEqual(owned.start_day, 4)
        self.assertEqual(owned.prepared_day, 0)
        self.assertIs(owner._weeklies[0], owned)

    def test_two_script_instances_dispatch_to_their_own_weeklies(self):
        first = config_mod.StarRailConfig()
        second = config_mod.StarRailConfig()
        first_echo = first._weekly_named("历战余响")
        second_echo = second._weekly_named("历战余响")
        with (
            patch.object(first_echo, "set_start_day") as first_write,
            patch.object(second_echo, "set_start_day") as second_write,
        ):
            first.set_weekly_start_day("历战余响", 4)
        first_write.assert_called_once_with(4)
        second_write.assert_not_called()

    def test_unadapted_script_is_skipped(self):
        """未适配周常的脚本：写入口不做事，读入口返回 None。"""
        self.assertIsNone(config_mod.get_weekly_task("没有的脚本", "历战余响"))
        config_mod.prepare_weekly_start_days("没有的脚本", {"历战余响": 3})
        config_mod.set_weekly_start_day("没有的脚本", "历战余响", 3)
        config_mod.set_weekly_task("没有的脚本", "历战余响", "副本")

    def test_scripts_without_capability_are_skipped(self):
        """有周常但无该能力的脚本：无字面起始日/无副本选型时不做事。"""
        config_mod.set_weekly_start_day("ok-ww", "幻梦游园", 3)
        config_mod.set_weekly_task("ok-ww", "幻梦游园", "副本")
        self.assertIsNone(config_mod.get_weekly_task("ok-ww", "幻梦游园"))

    def test_unknown_weekly_name_is_skipped(self):
        """周常名不存在时编辑期入口不做事（不误落到同脚本其它周常）。"""
        self.assertIsNone(config_mod.get_weekly_task("March7th-Launcher", "没有的周常"))
        config_mod.set_weekly_start_day("March7th-Launcher", "没有的周常", 3)

    def test_prepare_dispatches_only_listed_weeklies(self):
        """运行期入口只写 start_days 里列出的周常。"""
        currency = _weekly("March7th-Launcher", "货币战争")
        echo = _weekly("March7th-Launcher", "历战余响")
        with (
            patch.object(currency, "prepare_start_day") as mock_currency,
            patch.object(echo, "prepare_start_day") as mock_echo,
        ):
            config_mod.prepare_weekly_start_days("March7th-Launcher", {"历战余响": 5})
        mock_currency.assert_not_called()
        mock_echo.assert_called_once_with(5)

    def test_set_start_day_dispatches_by_name(self):
        """编辑期入口按周常展示名分发：只有覆写了该方法的周常动作。"""
        currency = _weekly("March7th-Launcher", "货币战争")
        echo = _weekly("March7th-Launcher", "历战余响")
        with (
            patch.object(currency, "set_start_day") as mock_currency,
            patch.object(echo, "set_start_day") as mock_echo,
        ):
            config_mod.set_weekly_start_day("March7th-Launcher", "货币战争", 4)
            config_mod.set_weekly_start_day("March7th-Launcher", "历战余响", 4)
        mock_currency.assert_not_called()  # 货币战争未覆写 set_start_day
        mock_echo.assert_called_once_with(4)
