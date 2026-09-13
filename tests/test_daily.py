"""Daily（声明规则层）：声明解析出的落点、读写规则、特殊日常的覆写点。

端到端等价（写入落点、反读、菜单内容）由 ``tests/test_golden_daily.py`` 的基线守；本文件
只测 ``Daily`` 自身的语义，不经过 ``ScriptConfig`` 的文件 I/O。
"""

import copy
import unittest

from src.config.daily import (
    AnomalyDaily,
    AnomalyHunterDaily,
    Daily,
    MaaDaily,
    NoopDaily,
)
from src.config.set_config import _CONFIGS
from src.config.task_config import load_daily_map

NO_OP_SCRIPTS = ("OneDragon-Launcher", "March7th-Launcher")


def daily_of(script_name: str, daily_name: str) -> Daily:
    """取某脚本某日常的对象（经 ScriptConfig 的类型分发）。"""
    return _CONFIGS[script_name]()._dispatch_daily(daily_name)


class TestDispatch(unittest.TestCase):
    """日常集合由声明推导，实现类按脚本/日常分发。"""

    def test_every_script_follows_its_declaration(self):
        for script_name in sorted(_CONFIGS):
            cfg = _CONFIGS[script_name]()
            dailies = cfg._dailies
            with self.subTest(script=script_name):
                self.assertEqual(
                    [daily.name for daily in dailies],
                    [decl["display_name"] for decl in load_daily_map()[script_name]],
                )
                # 日常对象懒加载一次后复用（同一实例），且可按展示名定位
                self.assertIs(cfg._dailies, dailies)
                for daily in dailies:
                    self.assertTrue(daily.physical_name)
                    self.assertIs(cfg._dispatch_daily(daily.name), daily)

    def test_unknown_daily_raises(self):
        with self.assertRaisesRegex(AssertionError, "未知日常"):
            _CONFIGS["ok-ww"]()._dispatch_daily("不存在的日常")

    def test_special_classes(self):
        for script_name in NO_OP_SCRIPTS:
            with self.subTest(script=script_name):
                daily = _CONFIGS[script_name]()._build_dailies()[0]
                self.assertIsInstance(daily, NoopDaily)
                self.assertTrue(daily.no_op)
        anomaly, hunter = _CONFIGS["ok-nte"]()._build_dailies()
        self.assertIsInstance(anomaly, AnomalyDaily)
        self.assertIsInstance(hunter, AnomalyHunterDaily)
        self.assertTrue(anomaly.enable_on_select and hunter.enable_on_select)
        self.assertIsInstance(_CONFIGS["MAA"]()._build_dailies()[0], MaaDaily)


class TestLandingPoints(unittest.TestCase):
    """落点由声明解析：一级/二级字段、两级同字段的合并。"""

    def test_two_level(self):
        daily = daily_of("ok-ww", "每日任务")
        self.assertEqual(daily.task_field, "Which to Farm")
        self.assertEqual(
            daily.fields("凝素领域", 1),
            {
                "Which to Farm": "Forgery Challenge",
                "Which Forgery Challenge to Farm": 1,
            },
        )
        self.assertEqual(
            daily.fields("无音区", 3),
            {
                "Which to Farm": "Tacet Suppression",
                "Which Tacet Suppression to Farm": 3,
            },
        )

    def test_two_level_sharing_one_field_takes_secondary(self):
        """原神两级写同一字段（DomainName）：二级覆盖一级，只留一个键。"""
        daily = daily_of("BetterGI", "每日任务")
        self.assertEqual(daily.task_field, "DomainName")
        self.assertEqual(daily.fields("圣遗物", "铭记之谷"), {"DomainName": "铭记之谷"})
        self.assertEqual(daily.fields("圣遗物"), {"DomainName": "圣遗物"})

    def test_single_level_uses_own_name(self):
        """单层日常（组内有 key）：整组自身即唯一一级项，展示名用日常名。"""
        daily = daily_of("ok-nte", "追猎目标")
        self.assertIsNone(daily.task_field)
        self.assertEqual(
            [option["display_name"] for option in daily.options], ["追猎目标"]
        )
        self.assertEqual(daily.fields("追猎目标", "音霸魔王"), {"追猎目标": "音霸魔王"})

    def test_secondary_display_name_is_accepted(self):
        """静态枚举的二级可直接传展示名（菜单给的是物理值）。"""
        daily = daily_of("ok-ww", "每日任务")
        self.assertEqual(
            daily.fields("模拟领域", "共鸣者经验")["Material Selection"],
            "Resonator EXP",
        )
        with self.assertRaisesRegex(AssertionError, "未适配的二级值"):
            daily.fields("模拟领域", "不存在的材料")

    def test_secondary_required_but_missing_raises(self):
        with self.assertRaisesRegex(AssertionError, "缺少二级选项"):
            daily_of("ok-ww", "每日任务").fields("模拟领域")


class TestRead(unittest.TestCase):
    """从数据段反读：标准反转、同字段不反转、无落点无真相。"""

    def test_reverse_lookup(self):
        daily = daily_of("ok-ww", "每日任务")
        section = {
            "Which to Farm": "Forgery Challenge",
            "Which Forgery Challenge to Farm": 3,
        }
        self.assertEqual(daily.read(section), ("凝素领域", 3))
        with self.assertRaisesRegex(AssertionError, "未知副本值"):
            daily.read({"Which to Farm": "不存在的值"})

    def test_shared_field_is_not_reversed(self):
        daily = daily_of("BetterGI", "每日任务")
        self.assertEqual(daily.read({"DomainName": "铭记之谷"}), ("铭记之谷", None))

    def test_unset_returns_none(self):
        daily = daily_of("ok-ww", "每日任务")
        self.assertEqual(daily.read({}), (None, None))
        self.assertEqual(daily.read({"Which to Farm": ""}), (None, None))

    def test_without_landing_point_has_no_truth(self):
        for script_name in NO_OP_SCRIPTS:
            with self.subTest(script=script_name):
                daily = _CONFIGS[script_name]()._build_dailies()[0]
                self.assertEqual(daily.read({}), (None, None))
                with self.assertRaisesRegex(AssertionError, "无选项落点"):
                    daily.write({}, "任何副本", None, "测试")


class TestEnabled(unittest.TestCase):
    """日常开关：只有分段脚本有第二份文件，只动自己那一条。"""

    def test_without_routine_file_it_is_unsupported(self):
        daily = daily_of("ok-ww", "每日任务")
        self.assertIsNone(daily.read_enabled(None))
        with self.assertRaisesRegex(AssertionError, "未支持停用日常"):
            daily.set_enabled({}, True)

    def test_anomaly_toggles_only_its_own_item(self):
        routine = {
            "Routine Items": [
                {"id": "daily_anomaly", "enabled": False},
                {"id": "daily_anomaly_hunter", "enabled": True},
            ]
        }
        for daily_name, item_id in (
            ("异象界域", "daily_anomaly"),
            ("追猎目标", "daily_anomaly_hunter"),
        ):
            with self.subTest(daily=daily_name):
                target = copy.deepcopy(routine)
                daily = daily_of("ok-nte", daily_name)
                own = next(i for i in target["Routine Items"] if i["id"] == item_id)
                seed_enabled = own["enabled"]
                self.assertEqual(daily.read_enabled(target), seed_enabled)
                # 置反必然有改变、且只动自己那条；对同值再置一次则无改变
                self.assertTrue(daily.set_enabled(target, not seed_enabled))
                self.assertEqual(own["enabled"], not seed_enabled)
                self.assertFalse(daily.set_enabled(target, not seed_enabled))
                other = next(i for i in target["Routine Items"] if i["id"] != item_id)
                self.assertEqual(
                    other["enabled"],
                    next(i for i in routine["Routine Items"] if i["id"] != item_id)[
                        "enabled"
                    ],
                    "另一个日常的开关不应被动到",
                )

    def test_read_enabled_without_file_has_no_truth(self):
        for daily_name in ("异象界域", "追猎目标"):
            with self.subTest(daily=daily_name):
                self.assertIsNone(daily_of("ok-nte", daily_name).read_enabled(None))

    def test_section_is_the_daily_own_segment(self):
        config = {"daily_anomaly": {"a": 1}, "daily_anomaly_hunter": {"b": 2}}
        anomaly = daily_of("ok-nte", "异象界域")
        hunter = daily_of("ok-nte", "追猎目标")
        self.assertEqual(anomaly.section(config), {"a": 1})
        self.assertEqual(hunter.section(config), {"b": 2})
        self.assertTrue(anomaly.section_exists(config))
        self.assertFalse(anomaly.section_exists({}))
        self.assertEqual(anomaly.section({}), {})


class TestDeclarationErrors(unittest.TestCase):
    """声明本身的约束：必须有选项，且不能混用单层与两层。"""

    def test_empty_options_rejected(self):
        with self.assertRaisesRegex(AssertionError, "必须声明选项"):
            Daily("脚本", {"display_name": "日常", "options": {"values": []}})

    def test_mixed_layers_rejected(self):
        declaration = {
            "display_name": "日常",
            "options": {
                "values": [
                    {"display_name": "两层", "options": {"key": "k", "values": []}},
                    {"display_name": "单层"},
                ]
            },
        }
        with self.assertRaisesRegex(AssertionError, "不能混用单层与两层"):
            Daily("脚本", declaration)


if __name__ == "__main__":
    unittest.main()
