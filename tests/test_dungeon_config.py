"""新声明接入原有单副本菜单；资源 I/O 用 mock 隔离。"""

import unittest
from copy import deepcopy
from unittest.mock import patch

from src.config.dungeon_config import (
    get_display_name,
    get_dungeon_map,
    get_weekly_map,
    parse_dungeon_config,
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
                "src.config.dungeon_config.load_weekly_map", return_value={"x": [task]}
            ),
            patch("src.config.dungeon_config.get_dungeon_lists") as source,
        ):
            self.assertEqual(
                get_weekly_map("x"),
                [{"name": "历战余响", "dungeons": ["无", "别名"]}],
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
                    "src.config.dungeon_config.load_weekly_map",
                    return_value={"x": [task]},
                ),
                patch(
                    "src.config.dungeon_config.get_dungeon_lists", return_value=names
                ) as source,
            ):
                result = get_weekly_map("x")
            source.assert_called_once_with("x", "native", "resource/list.json")
            self.assertEqual(result, [{"name": "展示周常", "dungeons": names or []}])

    def test_source_category_defaults_to_physical_name(self):
        task = {
            "display_name": "展示周常",
            "physical_name": "native_weekly",
            "options": {"source": {"path": "resource/list.json"}},
        }
        with (
            patch(
                "src.config.dungeon_config.load_weekly_map", return_value={"x": [task]}
            ),
            patch(
                "src.config.dungeon_config.get_dungeon_lists", return_value=[]
            ) as source,
        ):
            get_weekly_map("x")
        source.assert_called_once_with("x", "native_weekly", "resource/list.json")

    def test_no_options_and_unknown_script(self):
        with patch(
            "src.config.dungeon_config.load_weekly_map",
            return_value={"x": [{"display_name": "开关周常"}]},
        ):
            self.assertEqual(get_weekly_map("x"), [{"name": "开关周常"}])
            self.assertEqual(get_weekly_map("unknown"), [])


class TestGetDungeonMap(unittest.TestCase):
    def test_real_declarations_keep_one_menu_per_script(self):
        with patch("src.config.dungeon_config.get_dungeon_lists", return_value=[]):
            menus = get_dungeon_map()
        self.assertEqual(set(menus), set(load_daily_map()))
        options, sequences, show = parse_dungeon_config(menus["MAA"])
        self.assertEqual(options, ["红票", "经验", "龙门币", "土"])
        self.assertEqual(sequences, {})
        self.assertFalse(show)
        self.assertEqual(
            [item["name"] for item in menus["ok-nte"]["dungeons"]],
            ["空幕", "异能升级材料", "弧盘突破材料", "经验与甲硬币", "追猎目标"],
        )
        self.assertEqual(
            menus["OneDragon-Launcher"], {"dungeons": [{"name": "培养方案"}]}
        )
        self.assertEqual(
            menus["March7th-Launcher"], {"dungeons": [{"name": "培养目标"}]}
        )

    def test_secondary_menu_values_are_native_and_labels_roundtrip(self):
        with patch("src.config.dungeon_config.get_dungeon_lists", return_value=[]):
            menus = get_dungeon_map()
        _, sequences, show = parse_dungeon_config(menus["ok-ww"])
        self.assertTrue(show)
        self.assertEqual(sequences["模拟领域"][0], ("共鸣者经验", "Resonator EXP"))
        self.assertEqual(
            get_display_name(sequences, "模拟领域", "Resonator EXP"), "共鸣者经验"
        )
        self.assertEqual(sequences["凝素领域"][0], ("梦州-迅刀", 1))

    def test_daily_source_categories_come_from_declaration(self):
        with patch(
            "src.config.dungeon_config.get_dungeon_lists", return_value=["原生副本"]
        ) as source:
            menus = get_dungeon_map()
        source.assert_any_call(
            "BetterGI", "BlessDomain", "GameTask/AutoTrackPath/Assets/tp.json"
        )
        source.assert_any_call(
            "ok-ef", "干员养成", "data/apps/ok-ef/working/assets/data/world_map.json"
        )
        _, sequences, show = parse_dungeon_config(menus["BetterGI"])
        self.assertTrue(show)
        self.assertEqual(sequences["圣遗物"], [("原生副本", "原生副本")])

    def test_missing_resource_gives_empty_secondary_menu(self):
        for names in ([], None):
            with (
                self.subTest(names=names),
                patch(
                    "src.config.dungeon_config.get_dungeon_lists", return_value=names
                ),
            ):
                result = get_dungeon_map()
            self.assertEqual(result["ok-ef"]["dungeons"][0]["sequences"], [])

    def test_menu_does_not_modify_declarations(self):
        declarations = load_daily_map()
        original = deepcopy(declarations)
        with (
            patch("src.config.task_config.load_daily_map", return_value=declarations),
            patch(
                "src.config.dungeon_config.get_dungeon_lists", return_value=["测试资源"]
            ),
        ):
            first = get_dungeon_map()
            second = get_dungeon_map()
        self.assertEqual(first, second)
        self.assertEqual(declarations, original)

    def test_extra_daily_requires_explicit_subclass_support(self):
        declarations = load_daily_map()
        declarations["ok-ww"].append({"display_name": "另一个日常"})
        with (
            patch("src.config.task_config.load_daily_map", return_value=declarations),
            self.assertRaisesRegex(AssertionError, "多个日常需由子类适配"),
        ):
            get_dungeon_map()

    def test_third_level_is_not_silently_dropped(self):
        options = [
            {
                "display_name": "一级",
                "options": {
                    "values": [
                        {
                            "display_name": "二级",
                            "options": {"values": [{"display_name": "三级"}]},
                        }
                    ]
                },
            }
        ]
        with (
            patch("src.config.dungeon_config.load_daily_map", return_value={"x": []}),
            patch(
                "src.config.dungeon_config.get_dungeon_options", return_value=options
            ),
            self.assertRaisesRegex(AssertionError, "最多支持两级"),
        ):
            get_dungeon_map()


if __name__ == "__main__":
    unittest.main()
