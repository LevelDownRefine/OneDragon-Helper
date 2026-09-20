"""周常落点（``src.config.weekly``）：声明校验、装配、支持查询与各周常的落点读写。

一条周常一个对象（崩铁两条各一个），故测试按「脚本 + 周常展示名」取对象。
"""

import os
import unittest
from unittest.mock import patch

from src.config import weekly as weekly_mod
from src.config.daily_config import get_weekly_map
from src.config.set_config import _CONFIGS, ScriptConfig
from src.config.weekly import Weekly, weeklies_of, weekly_names


def _weekly(script_name: str, weekly_name: str) -> Weekly:
    """按脚本 + 周常展示名取已装配的周常对象。"""
    for weekly in weeklies_of(script_name):
        if weekly.display_name == weekly_name:
            return weekly
    raise AssertionError(f"未找到周常: {script_name}/{weekly_name}")


class TestWeeklyDeclaration(unittest.TestCase):
    """声明的机制类与文件路径声明。"""

    def test_every_declaration_has_registered_class_and_config(self):
        """每条周常都必须声明已注册的 class 与带扩展名的 config。"""
        for script_name, declarations in weekly_mod.load_weekly_map().items():
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
            for script_name in weekly_mod.load_weekly_map():
                for menu in get_weekly_map(script_name):
                    with self.subTest(script=script_name):
                        self.assertNotIn("class", menu)
                        self.assertNotIn("config", menu)


class TestWeeklyAssembly(unittest.TestCase):
    """装配：构造函数按声明建对象，ScriptConfig 构造期持有。"""

    def test_one_object_per_declaration(self):
        """一个脚本的周常对象数 = 声明条数（崩铁两条各一个对象）。"""
        for script_name, declarations in weekly_mod.load_weekly_map().items():
            with self.subTest(script=script_name):
                built = weeklies_of(script_name)
                self.assertEqual(len(built), len(declarations))
                self.assertEqual(
                    [w.display_name for w in built],
                    [d["display_name"] for d in declarations],
                )

    def test_scripts_without_declaration_build_empty(self):
        self.assertEqual(weeklies_of("BetterGI"), [])
        self.assertEqual(weekly_names("BetterGI"), [])

    def test_build_is_idempotent(self):
        """重复装配返回同一批对象（不重建）。"""
        self.assertIs(weekly_mod.build_weeklies("ok-ww", "鸣潮"), weeklies_of("ok-ww"))

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
            "测试": [{"display_name": "周常", "class": "没有的类", "config": "c.json"}]
        }
        with (
            patch.object(weekly_mod, "load_weekly_map", return_value=declarations),
            patch.dict(weekly_mod._BUILT, {}, clear=True),
            self.assertRaises(AssertionError),
        ):
            weekly_mod.build_weeklies("测试", "测试脚本")

    def test_duplicate_physical_name_raises(self):
        declarations = {
            "测试": [
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
            patch.dict(weekly_mod._BUILT, {}, clear=True),
            self.assertRaises(AssertionError),
        ):
            weekly_mod.build_weeklies("测试", "测试脚本")


class TestSupportsWeekly(unittest.TestCase):
    """周常支持查询：supports_weekly"""

    def test_unknown_script_returns_false(self):
        """未声明周常的脚本 → False"""
        self.assertFalse(weekly_mod.supports_weekly("不存在"))
        self.assertFalse(weekly_mod.supports_weekly("BetterGI"))

    def test_supported_are_the_five_weekly_scripts(self):
        """适配周常的是鸣潮/终末地/绝区零/崩铁/粥五个。"""
        expected = {
            "ok-ww",
            "ok-ef",
            "OneDragon-Launcher",
            "March7th-Launcher",
            "MAA",
        }
        self.assertEqual(set(weekly_mod.load_weekly_map()), expected)
        for name in expected:
            self.assertTrue(weekly_mod.supports_weekly(name), f"{name} 应支持周常")


class TestWeeklyStartDay(unittest.TestCase):
    """按周几起（start_day）写落点：六条周常各形态。"""

    # ---- 基类 ----

    def test_base_unsupported_raises(self):
        """基类无落点 → prepare_start_day assert"""
        base = Weekly("测试", {"display_name": "周常", "config": "c.json"}, "测试")
        with self.assertRaises(AssertionError):
            base.prepare_start_day(4)

    def test_invalid_start_day_raises(self):
        """start_day 越界（0 / 8）→ assert"""
        weekly = _weekly("March7th-Launcher", "货币战争")
        for bad in (0, 8):
            with self.subTest(bad=bad), self.assertRaises(AssertionError):
                weekly.prepare_start_day(bad)

    # ---- 崩铁·货币战争：布尔开关（按日期折算）----

    def test_currency_wars_enable_writes_true(self):
        """今天已到起始日 → currencywars_enable=True，且不碰历战余响的字面字段"""
        weekly = _weekly("March7th-Launcher", "货币战争")
        config = {"currencywars_enable": False, "echo_of_war_start_day_of_week": 1}
        with (
            patch("src.utils.utils_weekly.get_week_num", return_value=3),
            patch.object(weekly, "_load_config", return_value=config),
            patch.object(weekly, "_save_config") as mock_save,
        ):
            weekly.prepare_start_day(4)
        self.assertTrue(config["currencywars_enable"])
        self.assertEqual(config["echo_of_war_start_day_of_week"], 1)
        mock_save.assert_called_once()

    def test_currency_wars_disable_writes_false(self):
        """今天未到起始日 → currencywars_enable=False"""
        weekly = _weekly("March7th-Launcher", "货币战争")
        config = {"currencywars_enable": True, "echo_of_war_start_day_of_week": 1}
        with (
            patch("src.utils.utils_weekly.get_week_num", return_value=1),
            patch.object(weekly, "_load_config", return_value=config),
            patch.object(weekly, "_save_config") as mock_save,
        ):
            weekly.prepare_start_day(4)
        self.assertFalse(config["currencywars_enable"])
        self.assertEqual(config["echo_of_war_start_day_of_week"], 1)
        mock_save.assert_called_once()

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
        self.assertTrue(config["currencywars_enable"])
        mock_save.assert_called_once()

    # ---- 鸣潮：Additional Tasks 列表增删 ----

    def test_ww_enable_appends_weekly_task(self):
        """鸣潮启用周常（今天已到起始日）→ Additional Tasks 列表追加 Check Weekly Garden"""
        weekly = _weekly("ok-ww", "幻梦游园")
        config = {
            "Additional Tasks to Run After Daily Task": [
                "Merge Echo If discarded > 1000",
            ]
        }
        with (
            patch("src.utils.utils_weekly.get_week_num", return_value=3),
            patch.object(weekly, "_load_config", return_value=config),
            patch.object(weekly, "_save_config") as mock_save,
        ):
            weekly.prepare_start_day(4)
        self.assertIn(
            "Check Weekly Garden",
            config["Additional Tasks to Run After Daily Task"],
        )
        mock_save.assert_called_once()

    def test_ww_disable_removes_weekly_task(self):
        """鸣潮停用周常（今天未到起始日）→ Additional Tasks 列表移除 Check Weekly Garden"""
        weekly = _weekly("ok-ww", "幻梦游园")
        config = {
            "Additional Tasks to Run After Daily Task": [
                "Check Weekly Garden",
                "Merge Echo If discarded > 1000",
            ]
        }
        with (
            patch("src.utils.utils_weekly.get_week_num", return_value=1),
            patch.object(weekly, "_load_config", return_value=config),
            patch.object(weekly, "_save_config") as mock_save,
        ):
            weekly.prepare_start_day(4)
        self.assertNotIn(
            "Check Weekly Garden",
            config["Additional Tasks to Run After Daily Task"],
        )
        mock_save.assert_called_once()

    def test_ww_no_change_skips_save(self):
        """鸣潮状态无变化（已启用再启用）→ 不落盘"""
        weekly = _weekly("ok-ww", "幻梦游园")
        config = {
            "Additional Tasks to Run After Daily Task": ["Check Weekly Garden"],
        }
        with (
            patch("src.utils.utils_weekly.get_week_num", return_value=3),
            patch.object(weekly, "_load_config", return_value=config),
            patch.object(weekly, "_save_config") as mock_save,
        ):
            weekly.prepare_start_day(4)
        mock_save.assert_not_called()

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

    def test_zzz_enable_writes_lost_void_true(self):
        """绝区零启用周常（今天已到起始日）→ _group.yml 的 lost_void.enabled=True"""
        weekly = _weekly("OneDragon-Launcher", "迷失之地")
        config = {
            "app_list": [
                {"app_id": "notorious_hunt", "enabled": True},
                {"app_id": "lost_void", "enabled": False},
            ]
        }
        with (
            patch("src.utils.utils_weekly.get_week_num", return_value=3),
            patch.object(weekly, "_load_config", return_value=config),
            patch.object(weekly, "_save_config") as mock_save,
        ):
            weekly.prepare_start_day(4)
        lost = next(a for a in config["app_list"] if a["app_id"] == "lost_void")
        self.assertTrue(lost["enabled"])
        mock_save.assert_called_once()

    def test_zzz_disable_writes_lost_void_false(self):
        """绝区零停用周常（今天未到起始日）→ lost_void.enabled=False"""
        weekly = _weekly("OneDragon-Launcher", "迷失之地")
        config = {"app_list": [{"app_id": "lost_void", "enabled": True}]}
        with (
            patch("src.utils.utils_weekly.get_week_num", return_value=1),
            patch.object(weekly, "_load_config", return_value=config),
            patch.object(weekly, "_save_config") as mock_save,
        ):
            weekly.prepare_start_day(4)
        lost = next(a for a in config["app_list"] if a["app_id"] == "lost_void")
        self.assertFalse(lost["enabled"])
        mock_save.assert_called_once()

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


class TestEndfieldWeekly(unittest.TestCase):
    """终末地：周常开关是语义反相的布尔字段。"""

    def test_set_weekly_start_inverts_buy_only_flag(self):
        """周常（卖出物资）enabled 与游戏「只买不卖」反相：开→false，关→true。"""
        weekly = _weekly("ok-ef", "卖出物资")
        for enabled, expected in ((True, False), (False, True)):
            config = {"只买不卖": not expected}
            with (
                patch.object(weekly, "_load_config", return_value=config),
                patch.object(weekly, "_save_config") as mock_save,
                patch(
                    "src.config.weekly.is_weekly_start_reached",
                    return_value=enabled,
                ),
            ):
                weekly.prepare_start_day(1)
            self.assertEqual(config["只买不卖"], expected)
            mock_save.assert_called_once_with(config)


class TestEchoOfWarTasks(unittest.TestCase):
    """崩铁·历战余响：周常副本选型（instance_names）与编辑期字面起始日。"""

    def test_set_task_writes_instance_names(self):
        """set_task 写 config.yaml 的 instance_names[周常名]，容错建 dict。"""
        weekly = _weekly("March7th-Launcher", "历战余响")
        config: dict = {}
        with (
            patch.object(weekly, "_load_config", return_value=config),
            patch.object(weekly, "_save_config") as mock_save,
        ):
            weekly.set_task("铁骸的锈冢")
        mock_save.assert_called_once()
        self.assertEqual(config["instance_names"]["历战余响"], "铁骸的锈冢")

    def test_set_task_corrupt_instance_names_raises(self):
        """instance_names 已存在但非 dict → assert（与 read_task 对称，不静默重建）。"""
        weekly = _weekly("March7th-Launcher", "历战余响")
        config = {"instance_names": "不是dict"}
        with (
            patch.object(weekly, "_load_config", return_value=config),
            patch.object(weekly, "_save_config") as mock_save,
            self.assertRaises(AssertionError),
        ):
            weekly.set_task("铁骸的锈冢")
        mock_save.assert_not_called()

    def test_read_task_returns_stored_value(self):
        """read_task 读回已存副本值；未设置/无此段返回 None。"""
        weekly = _weekly("March7th-Launcher", "历战余响")
        config = {"instance_names": {"历战余响": "铁骸的锈冢"}}
        with patch.object(weekly, "_load_config", return_value=config):
            self.assertEqual(weekly.read_task(), "铁骸的锈冢")
        with patch.object(weekly, "_load_config", return_value={}):
            self.assertIsNone(weekly.read_task())

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


class TestWeeklyAdapter(unittest.TestCase):
    """模块级入口：按名分发、未适配 / 无此能力时优雅跳过。"""

    def test_unadapted_script_is_skipped(self):
        """未适配周常的脚本：写入口不做事，读入口返回 None。"""
        self.assertIsNone(weekly_mod.get_weekly_task("没有的脚本", "历战余响"))
        weekly_mod.prepare_weekly_start_days("没有的脚本", {"历战余响": 3})
        weekly_mod.set_weekly_start_day("没有的脚本", 3)
        weekly_mod.set_weekly_task("没有的脚本", "历战余响", "副本")

    def test_scripts_without_capability_are_skipped(self):
        """有周常但无该能力的脚本：无字面起始日/无副本选型时不做事。"""
        weekly_mod.set_weekly_start_day("ok-ww", 3)
        weekly_mod.set_weekly_task("ok-ww", "幻梦游园", "副本")
        self.assertIsNone(weekly_mod.get_weekly_task("ok-ww", "幻梦游园"))

    def test_prepare_dispatches_only_listed_weeklies(self):
        """运行期入口只写 start_days 里列出的周常。"""
        currency = _weekly("March7th-Launcher", "货币战争")
        echo = _weekly("March7th-Launcher", "历战余响")
        with (
            patch.object(currency, "prepare_start_day") as mock_currency,
            patch.object(echo, "prepare_start_day") as mock_echo,
        ):
            weekly_mod.prepare_weekly_start_days("March7th-Launcher", {"历战余响": 5})
        mock_currency.assert_not_called()
        mock_echo.assert_called_once_with(5)

    def test_set_start_day_is_script_wide(self):
        """编辑期入口是脚本级：写给该脚本所有覆写了该方法的周常。"""
        currency = _weekly("March7th-Launcher", "货币战争")
        echo = _weekly("March7th-Launcher", "历战余响")
        with (
            patch.object(currency, "set_start_day") as mock_currency,
            patch.object(echo, "set_start_day") as mock_echo,
        ):
            weekly_mod.set_weekly_start_day("March7th-Launcher", 4)
        mock_currency.assert_not_called()  # 货币战争未覆写 set_start_day
        mock_echo.assert_called_once_with(4)

    def test_task_entry_dispatches_by_name(self):
        """副本入口按周常展示名分发；无此周常时跳过。"""
        echo = _weekly("March7th-Launcher", "历战余响")
        with patch.object(echo, "set_task") as mock_set:
            weekly_mod.set_weekly_task("March7th-Launcher", "历战余响", "铁骸的锈冢")
            weekly_mod.set_weekly_task("March7th-Launcher", "没有的周常", "铁骸的锈冢")
        mock_set.assert_called_once_with("铁骸的锈冢")
