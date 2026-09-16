"""MAA 活动缓存和声明菜单的契约测试，不访问真实安装目录。"""

import unittest
from copy import deepcopy
from datetime import UTC, datetime
from unittest.mock import patch

from src.config.daily_config import get_daily_map
from src.config.maa_activity import read_activity_stages
from src.config.set_config import ArknightsConfig
from src.config.task_config import get_daily_configs


class TestMaaActivityResource(unittest.TestCase):
    def setUp(self):
        self.config = {
            "Configurations": {
                "Default": {"Gui": {"RuntimeSettings": {"ClientType": 0}}}
            }
        }
        self.group = {
            "Activity": {
                "UtcStartTime": "2026/09/01 04:00:00",
                "UtcExpireTime": "2026/09/20 04:00:00",
                "TimeZone": 8,
            },
            "Stages": [
                {"Display": "复刻导航", "Value": "SSReopen-AT"},
                {"Display": "活动材料", "Value": "AT-8"},
                {"Display": "SSReopen 字样不决定类型", "Value": "AT-7"},
                {"Value": "AT-8"},
                {"Value": ""},
            ],
        }
        self.data = {"Official": {"sideStoryStage": {"event": self.group}}}

    def read(self, now=None):
        now = now or datetime(2026, 9, 16, tzinfo=UTC)
        with (
            patch(
                "src.config.maa_activity.load_game_config",
                side_effect=[self.config, self.data],
            ),
            patch("src.config.maa_activity.datetime") as clock,
        ):
            clock.now.return_value = now
            clock.strptime.side_effect = datetime.strptime
            return read_activity_stages(
                "MAA", "cache/events.json", "config/gui.new.json"
            )

    def test_values_are_ordered_unique_single_stages(self):
        self.assertEqual(self.read(), ["AT-8", "AT-7"])

    def test_bilibili_uses_official_and_japan_uses_its_resource(self):
        runtime = self.config["Configurations"]["Default"]["Gui"]["RuntimeSettings"]
        runtime["ClientType"] = 1
        self.assertEqual(self.read(), ["AT-8", "AT-7"])
        self.data["YoStarJP"] = {"sideStoryStage": {"event": deepcopy(self.group)}}
        self.data["YoStarJP"]["sideStoryStage"]["event"]["Stages"] = [{"Value": "JP-8"}]
        runtime["ClientType"] = 3
        self.assertEqual(self.read(), ["JP-8"])

    def test_native_time_boundaries_and_resource_timezone(self):
        self.group["Activity"].update(
            UtcStartTime="2026/09/16 04:00:00",
            UtcExpireTime="2026/09/17 04:00:00",
            TimeZone=9,
        )
        self.assertEqual(self.read(datetime(2026, 9, 15, 19, tzinfo=UTC)), [])
        self.assertEqual(
            self.read(datetime(2026, 9, 15, 19, 0, 1, tzinfo=UTC)), ["AT-8", "AT-7"]
        )
        self.assertEqual(self.read(datetime(2026, 9, 16, 19, tzinfo=UTC)), [])

    def test_old_resource_without_timezone_defaults_to_eight(self):
        del self.group["Activity"]["TimeZone"]
        self.assertEqual(self.read(), ["AT-8", "AT-7"])

    def test_missing_installation_has_no_choices(self):
        with patch("src.config.maa_activity.load_game_config", return_value=None):
            self.assertEqual(
                read_activity_stages("MAA", "cache/events.json", "config/gui.new.json"),
                [],
            )


class TestMaaDeclaredMenus(unittest.TestCase):
    def test_activity_source_and_static_stage_lists_materialize_independently(self):
        declarations = get_daily_configs("MAA")
        with (
            patch(
                "src.config.daily_config.load_daily_map",
                return_value={"MAA": declarations},
            ),
            patch(
                "src.config.daily.read_activity_stages",
                return_value=["AT-8", "AT-7"],
            ) as reader,
        ):
            menus = get_daily_map()["MAA"]["dailies"]
        self.assertEqual(
            [menu["display_name"] for menu in menus],
            ["活动关卡", "理智作战", "剩余理智"],
        )
        self.assertEqual(
            [v["physical_name"] for v in menus[0]["options"]["values"]],
            ["AT-8", "AT-7"],
        )
        self.assertEqual(menus[1]["options"]["values"], menus[2]["options"]["values"])
        self.assertEqual(len(menus[1]["options"]["values"]), 16)
        reader.assert_called_once_with(
            "MAA", "cache/gui/StageActivityV2.json", "config/gui.new.json"
        )

    def test_source_dispatch_uses_declared_paths_not_display_name(self):
        declarations = get_daily_configs("MAA")
        activity = declarations[0]
        activity.update(display_name="别名", config="profiles/custom.json")
        activity["options"]["source"] = {"path": "resources/events.json"}
        with (
            patch(
                "src.config.set_config.get_daily_configs",
                side_effect=AssertionError("不应反查声明"),
            ),
            patch(
                "src.config.daily.read_activity_stages", return_value=["AT-8"]
            ) as reader,
        ):
            self.assertEqual(
                ArknightsConfig.get_task_lists(activity, activity["options"]["source"]),
                ["AT-8"],
            )
        reader.assert_called_once_with(
            "MAA", "resources/events.json", "profiles/custom.json"
        )

    def test_menu_uses_current_daily_config_without_reverse_lookup(self):
        declarations = get_daily_configs("MAA")
        activity = declarations[0]
        activity["config"] = "profiles/current.json"
        with (
            patch(
                "src.config.daily_config.load_daily_map",
                return_value={"MAA": declarations},
            ),
            patch(
                "src.config.set_config.get_daily_configs",
                side_effect=AssertionError("菜单已持有声明，不应重新读取"),
            ),
            patch.object(ArknightsConfig, "_init_config") as init,
            patch("src.config.daily.save_config") as save,
            patch(
                "src.config.daily.read_activity_stages", return_value=["AT-8"]
            ) as reader,
        ):
            menu = get_daily_map()["MAA"]["dailies"][0]
        self.assertEqual(
            menu["options"]["values"],
            [{"display_name": "AT-8", "physical_name": "AT-8"}],
        )
        reader.assert_called_once_with(
            "MAA", "cache/gui/StageActivityV2.json", "profiles/current.json"
        )
        init.assert_not_called()
        save.assert_not_called()
