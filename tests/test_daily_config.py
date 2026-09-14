"""新声明接入原有单副本菜单；资源 I/O 用 mock 隔离。"""

import unittest
from copy import deepcopy
from unittest.mock import patch

from src.config.daily_config import (
    get_daily_map,
    get_weekly_map,
)
from src.config.task_config import load_daily_map


class TestGetWeeklyDefs(unittest.TestCase):
    def test_static_options_preserve_labels(self):
        task = {
            "display_name": "历战余响",
            "options": {
                "values": [
                    {"display_name": "无"},
                    {"display_name": "别名", "physical_name": "原生副本"},
                ]
            },
        }
        original = deepcopy(task)
        with (
            patch(
                "src.config.daily_config.load_weekly_map",
                return_value={"x": [task]},
            ),
            patch("src.config.daily_config.get_task_lists") as source,
        ):
            self.assertEqual(
                get_weekly_map("x"),
                [{"name": "历战余响", "tasks": ["无", "别名"]}],
            )
        self.assertEqual(task, original)
        source.assert_not_called()

    def test_local_source_uses_native_category_and_path(self):
        task = {
            "display_name": "展示周常",
            "options": {"source": {"path": "resource/list.json", "category": "native"}},
        }
        for names in (["甲", "乙"], [], None):
            with (
                self.subTest(names=names),
                patch(
                    "src.config.daily_config.load_weekly_map",
                    return_value={"x": [task]},
                ),
                patch(
                    "src.config.daily_config.get_task_lists", return_value=names
                ) as source,
            ):
                result = get_weekly_map("x")
            source.assert_called_once_with("x", "native", "resource/list.json")
            self.assertEqual(result, [{"name": "展示周常", "tasks": names or []}])

    def test_source_category_defaults_to_physical_name(self):
        task = {
            "display_name": "展示周常",
            "physical_name": "native_weekly",
            "options": {"source": {"path": "resource/list.json"}},
        }
        with (
            patch(
                "src.config.daily_config.load_weekly_map",
                return_value={"x": [task]},
            ),
            patch("src.config.daily_config.get_task_lists", return_value=[]) as source,
        ):
            get_weekly_map("x")
        source.assert_called_once_with("x", "native_weekly", "resource/list.json")

    def test_no_options_and_unknown_script(self):
        with patch(
            "src.config.daily_config.load_weekly_map",
            return_value={"x": [{"display_name": "开关周常"}]},
        ):
            self.assertEqual(get_weekly_map("x"), [{"name": "开关周常"}])
            self.assertEqual(get_weekly_map("unknown"), [])


class TestGetDailyMap(unittest.TestCase):
    def test_real_declarations_keep_one_menu_per_daily(self):
        with patch("src.config.daily_config.get_task_lists", return_value=[]):
            menus = get_daily_map()
        self.assertEqual(set(menus), set(load_daily_map()))
        maa = menus["MAA"]["dailies"][0]
        self.assertEqual(maa["display_name"], "每日任务")
        values = maa["options"]["values"]
        self.assertEqual(
            [option["display_name"] for option in values],
            ["红票", "经验", "龙门币", "土"],
        )
        # 物化补齐缺省物理名（MAA 声明自带关卡代码，原样保留）；叶子选项不带子选项组
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
                    "display_name": "每日任务",
                    "options": {
                        "values": [
                            {
                                "display_name": "培养方案",
                                "physical_name": "培养方案",
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
                    "display_name": "每日任务",
                    "options": {
                        "values": [
                            {
                                "display_name": "培养目标",
                                "physical_name": "培养目标",
                            }
                        ]
                    },
                }
            ],
        )

    def test_secondary_menu_values_are_native(self):
        with patch("src.config.daily_config.get_task_lists", return_value=[]):
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

    def test_daily_source_categories_come_from_declaration(self):
        with patch(
            "src.config.daily_config.get_task_lists", return_value=["原生副本"]
        ) as source:
            menus = get_daily_map()
        source.assert_any_call(
            "BetterGI", "BlessDomain", "GameTask/AutoTrackPath/Assets/tp.json"
        )
        source.assert_any_call(
            "ok-ef", "干员养成", "data/apps/ok-ef/working/assets/data/world_map.json"
        )
        values = {
            option["display_name"]: option
            for option in menus["BetterGI"]["dailies"][0]["options"]["values"]
        }
        self.assertEqual(
            values["圣遗物"]["options"]["values"],
            [{"display_name": "原生副本", "physical_name": "原生副本"}],
        )

    def test_missing_resource_gives_empty_secondary_menu(self):
        for names in ([], None):
            with (
                self.subTest(names=names),
                patch("src.config.daily_config.get_task_lists", return_value=names),
            ):
                result = get_daily_map()
            self.assertEqual(
                result["ok-ef"]["dailies"][0]["options"]["values"][0]["options"][
                    "values"
                ],
                [],
            )

    def test_menu_does_not_modify_declarations(self):
        declarations = load_daily_map()
        original = deepcopy(declarations)
        with (
            patch("src.config.daily_config.load_daily_map", return_value=declarations),
            patch("src.config.daily_config.get_task_lists", return_value=["测试资源"]),
        ):
            first = get_daily_map()
            second = get_daily_map()
        self.assertEqual(first, second)
        self.assertEqual(declarations, original)

    def test_extra_daily_is_grouped_generically(self):
        """任何脚本多声明一个日常，菜单按日常分组展开（基类通用，无需子类适配）。"""
        declarations = load_daily_map()
        declarations["ok-ww"].append(
            {
                "display_name": "另一个日常",
                "options": {"values": [{"display_name": "别的副本"}]},
            }
        )
        with (
            patch("src.config.daily_config.load_daily_map", return_value=declarations),
            patch("src.config.daily_config.get_task_lists", return_value=["测试资源"]),
        ):
            menus = get_daily_map()
        self.assertEqual(
            [daily["display_name"] for daily in menus["ok-ww"]["dailies"]],
            ["每日任务", "另一个日常"],
        )
        self.assertEqual(
            [
                option["display_name"]
                for option in menus["ok-ww"]["dailies"][1]["options"]["values"]
            ],
            ["别的副本"],
        )

    def test_third_level_is_not_silently_dropped(self):
        declarations = {
            "x": [
                {
                    "display_name": "日常",
                    "options": {
                        "key": "一级字段",
                        "values": [
                            {
                                "display_name": "一级",
                                "options": {
                                    "key": "二级字段",
                                    "values": [
                                        {
                                            "display_name": "二级",
                                            "options": {
                                                "key": "三级字段",
                                                "values": [{"display_name": "三级"}],
                                            },
                                        }
                                    ],
                                },
                            }
                        ],
                    },
                }
            ]
        }
        with (
            patch(
                "src.config.daily_config.load_daily_map",
                return_value=declarations,
            ),
            self.assertRaisesRegex(AssertionError, "最多支持两级"),
        ):
            get_daily_map()


if __name__ == "__main__":
    unittest.main()
