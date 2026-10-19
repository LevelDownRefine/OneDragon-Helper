"""任务对象解释菜单；覆盖机制分派、资源刷新和无原生配置副作用。"""

import unittest
from copy import deepcopy
from unittest.mock import Mock, patch

from src.config.set_config import ArknightsConfig, get_daily_map, get_weekly_map
from src.config.task.daily import Daily, MaaActivityDaily, SingleLayerDaily
from src.config.task.task_declarations import load_daily_map
from src.config.task.weekly import Weekly
from tests.support.task_menus import patch_daily_sources


class TestDailyMenus(unittest.TestCase):
    def setUp(self):
        self.declaration = {
            "display_name": "日常",
            "physical_name": "native_daily",
            "class": "Daily",
            "config": "config.json",
            "options": {
                "key": "kind",
                "values": [
                    {
                        "display_name": "材料",
                        "physical_name": "material",
                        "options": {
                            "key": "stage",
                            "values": [{"display_name": "别名", "physical_name": 2}],
                        },
                    }
                ],
            },
        }

    def test_static_menu_and_write_fields_share_names_and_values(self):
        daily = Daily("x", self.declaration, "脚本")
        with (
            patch.object(daily, "get_task_lists") as source,
            patch.object(daily, "_read_config") as read,
        ):
            menu = daily.menu()
        self.assertEqual(
            menu,
            {
                "display_name": "日常",
                "physical_name": "native_daily",
                "options": self.declaration["options"],
            },
        )
        choice = menu["options"]["values"][0]
        child = choice["options"]["values"][0]
        self.assertEqual(
            daily._fields(choice["display_name"], child["physical_name"]),
            {
                "kind": "material",
                "stage": 2,
            },
        )
        source.assert_not_called()
        read.assert_not_called()

    def test_default_physical_names_preserve_false_values_and_declaration(self):
        del self.declaration["options"]["values"][0]["physical_name"]
        children = self.declaration["options"]["values"][0]["options"]["values"]
        children[:] = [
            {"display_name": "默认"},
            {"display_name": "关闭", "physical_name": False},
        ]
        original = deepcopy(self.declaration)
        daily = Daily("x", self.declaration, "脚本")
        self.assertEqual(
            daily._fields("材料", "默认"), {"kind": "材料", "stage": "默认"}
        )
        self.assertEqual(daily._fields("材料", False), {"kind": "材料", "stage": False})
        daily.menu()
        self.assertEqual(self.declaration, original)

    def test_single_layer_menu_uses_the_mechanism_shape(self):
        declaration = {
            "display_name": "培养",
            "physical_name": "build",
            "class": "SingleLayerDaily",
            "config": "config.yml",
            "options": {
                "key": "enabled",
                "values": [
                    {"display_name": "启用", "physical_name": True},
                    {"display_name": "不启用", "physical_name": False},
                ],
            },
        }
        daily = SingleLayerDaily("x", declaration, "脚本")
        with patch(
            "src.config.set_config.load_daily_map", return_value={"x": [declaration]}
        ):
            menu = get_daily_map("x")["x"]["dailies"][0]
        self.assertEqual(menu, daily.menu())
        choice = menu["options"]["values"][0]
        self.assertEqual(choice["display_name"], "培养")
        self.assertEqual(choice["physical_name"], "build")
        for option in choice["options"]["values"]:
            self.assertEqual(
                daily._fields(choice["display_name"], option["physical_name"]),
                {"enabled": option["physical_name"]},
            )

    def test_filter_does_not_build_or_read_other_scripts(self):
        current = deepcopy(self.declaration)
        current["options"]["values"][0]["options"] = {
            "key": "stage",
            "source": {"path": "current.json"},
        }
        declarations = {"current": [current], "other": [{"class": "不存在的机制"}]}
        with (
            patch("src.config.set_config.load_daily_map", return_value=declarations),
            patch(
                "src.config.task.task_source.read_task_source", return_value=["副本"]
            ) as source,
        ):
            menus = get_daily_map("current")
            self.assertEqual(get_daily_map("custom"), {})
        self.assertEqual(list(menus), ["current"])
        self.assertEqual(
            menus["current"]["dailies"][0]["options"]["values"][0]["options"]["values"],
            [{"display_name": "副本", "physical_name": "副本"}],
        )
        source.assert_called_once_with("current", {"path": "current.json"})

    def test_declared_mechanism_controls_menu_without_script_registry(self):
        declaration = load_daily_map()["BetterGI"][0]
        with (
            patch(
                "src.config.set_config.load_daily_map",
                return_value={"custom": [declaration]},
            ),
            patch(
                "src.config.task.daily.load_game_config",
                return_value={
                    "data": [
                        {
                            "points": [
                                {"type": "BlessDomain", "name": "秘境甲"},
                                {"type": "MasteryDomain", "name": "秘境乙"},
                            ]
                        }
                    ]
                },
            ),
            patch("src.config.set_config._CONFIGS", {}),
        ):
            menu = get_daily_map("custom")["custom"]["dailies"][0]
        choices = menu["options"]["values"]
        self.assertEqual(
            choices[1]["options"]["values"],
            [{"display_name": "秘境甲", "physical_name": "秘境甲"}],
        )
        self.assertEqual(
            choices[3]["options"]["values"],
            [{"display_name": "秘境乙", "physical_name": "秘境乙"}],
        )

    def test_first_menu_access_never_initializes_or_writes_native_config(self):
        with (
            patch("src.config.set_config._CONFIGS", {}),
            patch.object(ArknightsConfig, "_init_config") as init,
            patch("src.config.task.daily.load_script_config") as read,
            patch("src.config.task.daily.save_script_config") as save,
            patch("src.config.task.weekly.load_script_config") as weekly_read,
            patch("src.config.task.weekly.save_script_config") as weekly_save,
            patch_daily_sources(lambda daily, source: []),
        ):
            menus = get_daily_map()
            weeklies = get_weekly_map("MAA")
        self.assertEqual(len(menus["MAA"]["dailies"]), 3)
        self.assertEqual(weeklies[0]["display_name"], "理智药剂")
        for operation in (init, read, save, weekly_read, weekly_save):
            operation.assert_not_called()

    def test_dynamic_options_refresh_and_missing_resources_are_empty(self):
        self.declaration["options"]["values"][0]["options"] = {
            "key": "stage",
            "source": {"path": "stages.json", "key": ["stages"]},
        }
        with patch("src.config.task.task_source.read_task_source") as source:
            daily = Daily("x", self.declaration, "脚本")
            source.assert_not_called()
            source.side_effect = [["甲"], [], ["乙"]]
            menus = [daily.menu() for _ in range(3)]
        self.assertEqual(
            [menu["options"]["values"][0]["options"]["values"] for menu in menus],
            [
                [{"display_name": "甲", "physical_name": "甲"}],
                [],
                [{"display_name": "乙", "physical_name": "乙"}],
            ],
        )
        self.assertEqual(source.call_count, 3)

    def test_menu_mutations_do_not_change_daily_rules(self):
        original = deepcopy(self.declaration)
        daily = Daily("x", self.declaration, "脚本")
        first = daily.menu()
        choice = first["options"]["values"][0]
        choice["display_name"] = "被改的菜单"
        choice["options"]["key"] = "被改的字段"
        choice["options"]["values"][0]["physical_name"] = 99
        choice["options"]["values"].append({"display_name": "新增选项"})
        self.assertEqual(self.declaration, original)
        self.assertEqual(daily.menu()["options"], original["options"])
        self.assertEqual(daily._fields("材料", 2), {"kind": "material", "stage": 2})

    def test_extra_daily_uses_its_declared_class(self):
        declarations = load_daily_map()
        declarations["ok-ww"].append(self.declaration)
        with patch("src.config.set_config.load_daily_map", return_value=declarations):
            menus = get_daily_map("ok-ww")["ok-ww"]["dailies"]
        self.assertEqual([menu["display_name"] for menu in menus], ["每日任务", "日常"])
        self.assertEqual(menus[1]["options"], self.declaration["options"])

    def test_activity_daily_uses_its_own_config_and_source(self):
        declaration = load_daily_map()["MAA"][0]
        declaration.update(display_name="别名", config="profiles/current.json")
        declaration["options"]["source"] = {"path": "resources/events.json"}
        with patch(
            "src.config.task.daily.read_activity_stages", return_value=["AT-8"]
        ) as reader:
            daily = MaaActivityDaily("MAA", declaration, "粥")
            reader.assert_not_called()
            menu = daily.menu()
        self.assertEqual(
            menu["options"]["values"],
            [{"display_name": "AT-8", "physical_name": "AT-8"}],
        )
        reader.assert_called_once_with(
            "MAA", "resources/events.json", "profiles/current.json"
        )

    def test_third_level_is_rejected(self):
        single_layer = deepcopy(self.declaration)
        child = self.declaration["options"]["values"][0]["options"]["values"][0]
        child["options"] = {"key": "third", "values": [{"display_name": "三级"}]}
        for cls, declaration in (
            (Daily, self.declaration),
            (SingleLayerDaily, single_layer),
        ):
            with self.subTest(mechanism=cls.__name__):
                daily = cls("x", declaration, "脚本")
                with self.assertRaisesRegex(AssertionError, "最多支持两级"):
                    daily.menu()

    def test_resource_dispatch_receives_the_owning_daily(self):
        reader = Mock(return_value=["原生副本"])
        with patch_daily_sources(reader):
            menu = get_daily_map("BetterGI")["BetterGI"]["dailies"][0]
        daily, source = reader.call_args_list[0].args
        self.assertEqual(daily.script_name, "BetterGI")
        self.assertEqual(daily.display_name, "每日任务")
        self.assertEqual(
            source,
            {
                "path": "GameTask/AutoTrackPath/Assets/tp.json",
                "category": "BlessDomain",
            },
        )
        self.assertEqual(
            menu["options"]["values"][1]["options"]["values"],
            [{"display_name": "原生副本", "physical_name": "原生副本"}],
        )

    def test_real_declarations_keep_one_menu_per_daily(self):
        with patch_daily_sources(lambda daily, source: []):
            menus = get_daily_map()
        self.assertEqual(set(menus), set(load_daily_map()))
        maa = menus["MAA"]["dailies"]
        self.assertEqual(
            [daily["display_name"] for daily in maa],
            ["活动关卡", "理智作战", "剩余理智"],
        )
        self.assertEqual(maa[0]["options"]["values"], [])
        values = maa[1]["options"]["values"]
        self.assertEqual(len(values), 16)
        self.assertEqual(values, maa[2]["options"]["values"])
        # 普通关卡的物理值就是关卡代码，叶子选项不带子选项组。
        self.assertTrue(all("physical_name" in option for option in values))
        self.assertTrue(all("options" not in option for option in values))
        # 异环两个日常各一份菜单（不再合并）
        nte = menus["ok-nte"]["dailies"]
        self.assertEqual(
            [daily["display_name"] for daily in nte], ["异象界域", "追猎目标"]
        )
        self.assertEqual(
            [option["display_name"] for option in nte[0]["options"]["values"]],
            ["空幕", "异能升级材料", "弧盘突破材料", "经验与甲硬币"],
        )
        # 单层带 key（追猎目标）：整组即唯一一级项，values 作二级
        hunter = nte[1]["options"]["values"]
        self.assertEqual([option["display_name"] for option in hunter], ["追猎目标"])
        self.assertEqual(
            [child["display_name"] for child in hunter[0]["options"]["values"]],
            ["音霸魔王", "无首铁驭", "塞润尼缇", "黑之书", "海囚", "围巢鸟", "斑蝶"],
        )
        self.assertEqual(
            menus["OneDragon-Launcher"]["dailies"],
            [
                {
                    "display_name": "培养方案",
                    "options": {
                        "values": [
                            {
                                "display_name": "培养方案",
                                "physical_name": "培养方案",
                                "options": {
                                    "key": "plan_list",
                                    "values": [
                                        {"display_name": "启用", "physical_name": True},
                                        {
                                            "display_name": "不启用",
                                            "physical_name": False,
                                        },
                                    ],
                                },
                            }
                        ]
                    },
                }
            ],
        )
        self.assertEqual(
            menus["March7th-Launcher"]["dailies"],
            [
                {
                    "display_name": "培养目标",
                    "options": {
                        "values": [
                            {
                                "display_name": "培养目标",
                                "physical_name": "培养目标",
                                "options": {
                                    "key": "build_target_enable",
                                    "values": [
                                        {
                                            "display_name": "启用",
                                            "physical_name": True,
                                        },
                                        {
                                            "display_name": "不启用",
                                            "physical_name": False,
                                        },
                                    ],
                                },
                            }
                        ]
                    },
                }
            ],
        )

    def test_yaml_option_groups_are_plain_dicts_for_qml(self):
        """YAML 的 CommentedMap 必须转为普通 dict，Qt 才能传成 QVariantMap。"""
        with patch_daily_sources(lambda daily, source: []):
            menus = get_daily_map()
        groups = [
            daily["options"] for script in menus.values() for daily in script["dailies"]
        ]
        declaration = load_daily_map()["March7th-Launcher"][0]
        groups.append(Weekly("x", declaration, "脚本").menu()["options"])
        while groups:
            group = groups.pop()
            self.assertIs(type(group), dict)
            for option in group["values"]:
                self.assertIs(type(option), dict)
                if "options" in option:
                    groups.append(option["options"])

    def test_secondary_menu_values_are_native(self):
        with patch_daily_sources(lambda daily, source: []):
            menus = get_daily_map()
        values = {
            option["display_name"]: option
            for option in menus["ok-ww"]["dailies"][0]["options"]["values"]
        }
        self.assertEqual(
            values["模拟领域"]["options"]["values"][0],
            {"display_name": "共鸣者经验", "physical_name": "Resonator EXP"},
        )
        self.assertEqual(
            values["凝素领域"]["options"]["values"][0],
            {"display_name": "梦州-迅刀", "physical_name": 1},
        )


class TestWeeklyMenus(unittest.TestCase):
    def test_weekly_value_mapping_handles_optional_and_dynamic_groups(self):
        declaration = {
            "display_name": "周常",
            "config": "config.json",
        }
        for group, expected in (
            (None, {}),
            ({"source": {"path": "stages.json"}}, {}),
            (
                {
                    "values": [
                        {"display_name": "默认"},
                        {"display_name": "关闭", "physical_name": False},
                    ]
                },
                {"默认": "默认", "关闭": False},
            ),
        ):
            with self.subTest(group=group):
                current = deepcopy(declaration)
                if group is not None:
                    current["options"] = group
                original = deepcopy(current)
                weekly = Weekly("x", current, "脚本")
                self.assertEqual(weekly._task_values, expected)
                self.assertEqual(current, original)

    def test_static_options_and_empty_weeklies(self):
        declarations = [
            {
                "display_name": "周常",
                "class": "SwitchWeekly",
                "config": "config.json",
                "options": {
                    "values": [
                        {"display_name": "无"},
                        {"display_name": "别名", "physical_name": "原生值"},
                    ]
                },
            },
            {"display_name": "开关", "class": "SwitchWeekly", "config": "config.json"},
        ]
        original = deepcopy(declarations)
        with (
            patch(
                "src.config.task.weekly.load_weekly_map",
                return_value={"x": declarations},
            ),
            patch("src.config.task.task_source.read_task_source") as source,
        ):
            menus = get_weekly_map("x")
            self.assertEqual(get_weekly_map("unknown"), [])
        self.assertEqual(
            menus,
            [
                {
                    "display_name": "周常",
                    "options": {
                        "values": [
                            {"display_name": "无", "physical_name": "无"},
                            {"display_name": "别名", "physical_name": "原生值"},
                        ]
                    },
                },
                {"display_name": "开关"},
            ],
        )
        menus[0]["options"]["values"][0]["display_name"] = "变更"
        self.assertEqual(declarations, original)
        source.assert_not_called()

    def test_resources_use_declared_paths_and_refresh(self):
        for source in (
            {"path": "resource.json"},
            {"path": "resource.json", "key": ["stages"]},
        ):
            with self.subTest(source=source):
                declaration = {
                    "display_name": "别名",
                    "config": "config.json",
                    "options": {"source": source},
                }
                weekly = Weekly("x", declaration, "脚本")
                with patch(
                    "src.config.task.task_source.read_task_source",
                    side_effect=[["甲"], []],
                ) as reader:
                    menus = [weekly.menu(), weekly.menu()]
                self.assertEqual(
                    menus[0]["options"]["values"],
                    [{"display_name": "甲", "physical_name": "甲"}],
                )
                self.assertEqual(menus[1]["options"]["values"], [])
                reader.assert_called_with("x", source)

    def test_second_level_is_rejected(self):
        weekly = Weekly(
            "x",
            {
                "display_name": "周常",
                "config": "config.json",
                "options": {
                    "values": [
                        {
                            "display_name": "一级",
                            "options": {"values": [{"display_name": "二级"}]},
                        }
                    ]
                },
            },
            "脚本",
        )
        with self.assertRaisesRegex(AssertionError, "只支持一级"):
            weekly.menu()
