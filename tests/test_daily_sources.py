"""日常持有资源读取规则；周常复用通用键路径读取。"""

import unittest
from unittest.mock import patch

from src.config.daily_config import get_daily_map
from src.config.set_config import (
    _CONFIGS,
    EndfieldConfig,
    GenshinConfig,
    NTEConfig,
    StarRailConfig,
    WutheringWavesConfig,
    get_task_lists,
)
from src.config.task_config import get_daily_configs
from src.config.task_source import read_task_source


class TestWeeklySource(unittest.TestCase):
    """崩铁周常直接复用通用资源读取，不需要日常对象。"""

    _DATA = {
        "历战余响": {"无": "跳过", "铁骸的锈冢": "描述1", "晨昏的回眸": "描述2"},
        "其他周常": {"甲": "x"},
    }

    def test_reads_keys_of_weekly_entry(self):
        """正常读取：返回该任务条目的键列表（即副本名，含「无」占位）。"""
        with patch(
            "src.config.task_source.load_game_config", return_value=self._DATA
        ) as mock_load:
            names = read_task_source(
                "March7th-Launcher",
                {"path": "assets/config/instance_names.json", "key": ["历战余响"]},
            )
        self.assertEqual(names, ["无", "铁骸的锈冢", "晨昏的回眸"])
        mock_load.assert_called_once_with(
            "March7th-Launcher", "assets/config/instance_names.json"
        )

    def test_does_not_instantiate_or_init_config(self):
        """周常读资源不触发配置初始化。"""
        with (
            patch.object(StarRailConfig, "_init_config") as mock_init,
            patch("src.config.task_source.load_game_config", return_value=self._DATA),
        ):
            read_task_source(
                "March7th-Launcher",
                {"path": "assets/config/instance_names.json", "key": ["历战余响"]},
            )
        mock_init.assert_not_called()

    def test_source_is_used_as_rel_path(self):
        """source 即相对脚本根目录的路径，直接透传给 load_game_config（无额外白名单）。"""
        with patch(
            "src.config.task_source.load_game_config", return_value=None
        ) as mock_load:
            self.assertEqual(
                read_task_source(
                    "March7th-Launcher",
                    {"path": "some/other/path.json", "key": ["历战余响"]},
                ),
                [],
            )
        mock_load.assert_called_once_with("March7th-Launcher", "some/other/path.json")

    def test_script_not_installed_returns_empty(self):
        """M7A 未安装（load_game_config 软降级为 None）→ data 为空 → 返回 []。"""
        with patch("src.config.task_source.load_game_config", return_value=None):
            self.assertEqual(
                read_task_source(
                    "March7th-Launcher",
                    {"path": "assets/config/instance_names.json", "key": ["历战余响"]},
                ),
                [],
            )

    def test_missing_task_key_asserts(self):
        """data 不含该任务键 → assert 触发（不静默兜底）。"""
        with (
            patch("src.config.task_source.load_game_config", return_value=self._DATA),
            self.assertRaises(AssertionError),
        ):
            read_task_source(
                "March7th-Launcher",
                {"path": "assets/config/instance_names.json", "key": ["不存在的周常"]},
            )

    def test_malformed_entry_asserts(self):
        """该任务条目不是列表或字典（格式异常）→ assert 触发（不静默兜底）。"""
        with (
            patch(
                "src.config.task_source.load_game_config",
                return_value={"历战余响": 42},
            ),
            self.assertRaises(AssertionError),
        ):
            read_task_source(
                "March7th-Launcher",
                {"path": "assets/config/instance_names.json", "key": ["历战余响"]},
            )


class TestTaskSource(unittest.TestCase):
    """通用资源读取：键路径选择节点，叶子列表或字典提供选项名。"""

    def test_root_options_preserve_order_and_return_a_copy(self):
        for data in (["乙", "甲"], {"乙": "描述乙", "甲": "描述甲"}):
            for source in (
                {"path": "options.json"},
                {"path": "options.json", "key": []},
            ):
                with (
                    self.subTest(data=data, source=source),
                    patch("src.config.task_source.load_game_config", return_value=data),
                ):
                    names = read_task_source("test", source)
                self.assertEqual(names, ["乙", "甲"])
                self.assertIsNot(names, data)

    def test_subclass_inherits_nested_key_path_reader(self):
        for key in (["资源", "类别"], ("资源", "类别")):
            with (
                self.subTest(key=key),
                patch(
                    "src.config.task_source.load_game_config",
                    return_value={"资源": {"类别": {"乙": 2, "甲": 1}}},
                ) as load,
                patch.object(NTEConfig, "_init_config") as init,
            ):
                names = get_task_lists(
                    "ok-nte", "异象界域", {"path": "options.json", "key": key}
                )
            self.assertEqual(names, ["乙", "甲"])
            load.assert_called_once_with("ok-nte", "options.json")
            init.assert_not_called()

    def test_invalid_source_or_resource_asserts(self):
        for source, data in (
            ({"path": "a.json", "category": "类别"}, {"类别": []}),
            ({"path": "a.json", "key": "类别"}, {"类别": []}),
            ({"path": "a.json", "key": ["类别", "叶子"]}, {"类别": ["甲"]}),
            ({"path": "a.json"}, ["甲", 1]),
            ({"path": "a.json"}, {1: "甲"}),
        ):
            with (
                self.subTest(source=source, data=data),
                patch("src.config.task_source.load_game_config", return_value=data),
                self.assertRaises(AssertionError),
            ):
                read_task_source("test", source)


class TestEndfieldGetTaskLists(unittest.TestCase):
    """终末地 Daily 复用键路径读取 world_map.json 的 stages_dict。"""

    _DATA = {
        "stages_dict": {
            "能量淤积点": ["枢纽区", "源石研究园", "武陵城"],
            "干员养成": ["干员经验", "干员进阶"],
        }
    }
    _SRC = "data/apps/ok-ef/working/assets/data/world_map.json"

    def setUp(self):
        self.declaration = get_daily_configs("ok-ef")[0]
        self.daily = _CONFIGS["ok-ef"]._dispatch_daily(self.declaration["display_name"])

    def test_reads_stages_list(self):
        """正常读取：返回 stages_dict[task_name]（二级目录副本名列表）。"""
        with patch(
            "src.config.task_source.load_game_config", return_value=self._DATA
        ) as mock_load:
            names = self.daily.get_task_lists(
                {"path": self._SRC, "key": ["stages_dict", "能量淤积点"]}
            )
        self.assertEqual(names, ["枢纽区", "源石研究园", "武陵城"])
        mock_load.assert_called_once_with("ok-ef", self._SRC)

    def test_does_not_instantiate_or_init_config(self):
        """读取选项复用已有日常，不触发配置初始化。"""
        with (
            patch.object(EndfieldConfig, "_init_config") as mock_init,
            patch("src.config.task_source.load_game_config", return_value=self._DATA),
        ):
            get_task_lists(
                "ok-ef",
                self.declaration["display_name"],
                {"path": self._SRC, "key": ["stages_dict", "能量淤积点"]},
            )
        mock_init.assert_not_called()

    def test_source_is_used_as_rel_path(self):
        """source 即相对脚本根目录的路径，直接透传给 load_game_config（无额外白名单）。"""
        with patch(
            "src.config.task_source.load_game_config", return_value=None
        ) as mock_load:
            self.assertEqual(
                self.daily.get_task_lists(
                    {
                        "path": "some/other/path.json",
                        "key": ["stages_dict", "能量淤积点"],
                    }
                ),
                [],
            )
        mock_load.assert_called_once_with("ok-ef", "some/other/path.json")

    def test_script_not_installed_returns_empty(self):
        """ok-ef 未安装（load_game_config 软降级为 None）→ data 为空 → 返回 []。"""
        with patch("src.config.task_source.load_game_config", return_value=None):
            self.assertEqual(
                self.daily.get_task_lists(
                    {"path": self._SRC, "key": ["stages_dict", "能量淤积点"]}
                ),
                [],
            )

    def test_missing_stages_dict_asserts(self):
        """顶层不含 stages_dict → assert 触发（不静默兜底）。"""
        with (
            patch("src.config.task_source.load_game_config", return_value={"foo": 1}),
            self.assertRaises(AssertionError),
        ):
            self.daily.get_task_lists(
                {"path": self._SRC, "key": ["stages_dict", "能量淤积点"]}
            )

    def test_missing_task_key_asserts(self):
        """stages_dict 不含该类别 → assert 触发（不静默兜底）。"""
        with (
            patch("src.config.task_source.load_game_config", return_value=self._DATA),
            self.assertRaises(AssertionError),
        ):
            self.daily.get_task_lists(
                {"path": self._SRC, "key": ["stages_dict", "不存在的类别"]}
            )

    def test_malformed_entry_asserts(self):
        """stages_dict 中的选项不是列表或字典（格式异常）→ assert 触发（不静默兜底）。"""
        with (
            patch(
                "src.config.task_source.load_game_config",
                return_value={"stages_dict": {"能量淤积点": 42}},
            ),
            self.assertRaises(AssertionError),
        ):
            self.daily.get_task_lists(
                {"path": self._SRC, "key": ["stages_dict", "能量淤积点"]}
            )


class TestBgiGetTaskLists(unittest.TestCase):
    """BgiDaily 遍历 tp.json 的 points 收集秘境分类副本名。"""

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

    def setUp(self):
        self.declaration = get_daily_configs("BetterGI")[0]
        self.daily = _CONFIGS["BetterGI"]._dispatch_daily(
            self.declaration["display_name"]
        )

    def test_reads_bless_domain_across_scenes(self):
        """圣遗物 → BlessDomain：跨多个地图场景收集副本名。"""
        with patch(
            "src.config.daily.load_game_config", return_value=self._DATA
        ) as mock_load:
            names = self.daily.get_task_lists(
                {"path": self._SRC, "category": "BlessDomain"}
            )
        self.assertEqual(names, ["仲夏庭园", "铭记之谷", "芬德尼尔之顶"])
        mock_load.assert_called_once_with("BetterGI", self._SRC)

    def test_reads_forgery_domain(self):
        """武器 → ForgeryDomain：仅收集该 type 的副本名。"""
        with patch("src.config.daily.load_game_config", return_value=self._DATA):
            names = self.daily.get_task_lists(
                {"path": self._SRC, "category": "ForgeryDomain"}
            )
        self.assertEqual(names, ["塞西莉亚苗圃"])

    def test_reads_mastery_domain(self):
        """天赋 → MasteryDomain。"""
        with patch("src.config.daily.load_game_config", return_value=self._DATA):
            names = self.daily.get_task_lists(
                {"path": self._SRC, "category": "MasteryDomain"}
            )
        self.assertEqual(names, ["太山府"])

    def test_ignores_other_types(self):
        """TeleportWaypoint / 未命中 type 的 point 不计入清单。"""
        with patch("src.config.daily.load_game_config", return_value=self._DATA):
            names = self.daily.get_task_lists(
                {"path": self._SRC, "category": "BlessDomain"}
            )
        self.assertNotIn("传送锚点", names)

    def test_does_not_instantiate_or_init_config(self):
        """读取选项复用已有日常，不触发配置初始化。"""
        with (
            patch.object(GenshinConfig, "_init_config") as mock_init,
            patch("src.config.daily.load_game_config", return_value=self._DATA),
        ):
            get_task_lists(
                "BetterGI",
                self.declaration["display_name"],
                {"path": self._SRC, "category": "BlessDomain"},
            )
        mock_init.assert_not_called()

    def test_source_is_used_as_rel_path(self):
        """source 即相对脚本根目录的路径，直接透传给 load_game_config（无额外白名单）。"""
        with patch("src.config.daily.load_game_config", return_value=None) as mock_load:
            self.assertEqual(
                self.daily.get_task_lists(
                    {"path": "some/other/path.json", "category": "BlessDomain"}
                ),
                [],
            )
        mock_load.assert_called_once_with("BetterGI", "some/other/path.json")

    def test_script_not_installed_returns_empty(self):
        """BetterGI 未安装（load_game_config 软降级为 None）→ data 为空 → 返回 []。"""
        with patch("src.config.daily.load_game_config", return_value=None):
            self.assertEqual(
                self.daily.get_task_lists(
                    {"path": self._SRC, "category": "BlessDomain"}
                ),
                [],
            )

    def test_category_without_native_entries_returns_empty(self):
        """不维护类别白名单；资源中没有匹配类别时返回空列表。"""
        with patch("src.config.daily.load_game_config", return_value=self._DATA):
            self.assertEqual(
                self.daily.get_task_lists(
                    {"path": self._SRC, "category": "WeeklyDomain"}
                ),
                [],
            )

    def test_top_level_not_dict_asserts(self):
        """tp.json 顶层非 dict（格式异常）→ assert 触发（不静默兜底）。"""
        with (
            patch("src.config.daily.load_game_config", return_value=[1, 2]),
            self.assertRaises(AssertionError),
        ):
            self.daily.get_task_lists({"path": self._SRC, "category": "BlessDomain"})

    def test_nested_menu_uses_bgi_daily_for_each_category(self):
        with (
            patch(
                "src.config.daily_config.load_daily_map",
                return_value={"BetterGI": [self.declaration]},
            ),
            patch("src.config.daily.load_game_config", return_value=self._DATA),
            patch(
                "src.config.set_config.get_daily_configs",
                side_effect=AssertionError("不应反查声明"),
            ),
        ):
            menu = get_daily_map()["BetterGI"]["dailies"][0]
        self.assertEqual(
            [
                [v["physical_name"] for v in option["options"]["values"]]
                for option in menu["options"]["values"]
            ],
            [["仲夏庭园", "铭记之谷", "芬德尼尔之顶"], ["塞西莉亚苗圃"], ["太山府"]],
        )

    def test_adapter_uses_declared_mechanism_instead_of_script_type(self):
        source = {"path": self._SRC, "category": "BlessDomain"}
        with patch(
            "src.config.set_config.get_daily_configs", return_value=[self.declaration]
        ):
            cfg = WutheringWavesConfig()
        with (
            patch.dict(_CONFIGS, {"ok-ww": cfg}),
            patch("src.config.daily.load_game_config", return_value=self._DATA) as load,
        ):
            names = get_task_lists("ok-ww", self.declaration["display_name"], source)
        self.assertEqual(names, ["仲夏庭园", "铭记之谷", "芬德尼尔之顶"])
        load.assert_called_once_with("ok-ww", self._SRC)
