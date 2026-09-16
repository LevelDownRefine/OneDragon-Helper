"""MAA 本地活动缓存的服务器、开放时间和缺失回退。"""

import copy
import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from src.config.daily_config import get_daily_map
from src.config.maa_stages import load_activity_stages
from src.config.set_config import ArknightsConfig
from src.config.task_config import get_daily_configs
from tests.test_arknights_config_safety import load_fixture


def activity(start, end, values, offset=8):
    return {
        "Activity": {"UtcStartTime": start, "UtcExpireTime": end, "TimeZone": offset},
        "Stages": [{"Value": value, "Display": value} for value in values],
    }


class TestMaaLocalStages(unittest.TestCase):
    def setUp(self):
        self.config = load_fixture()
        self.data = {
            "Official": {
                "sideStoryStage": {
                    "old": activity(
                        "2026/08/01 00:00:00", "2026/09/15 03:59:59", ["OLD-8"]
                    ),
                    "live": activity(
                        "2026/09/15 04:00:00",
                        "2026/09/29 03:59:59",
                        ["SSReopen-X", "ACT-8", "ACT-7", "ACT-8"],
                    ),
                    "future": activity(
                        "2026/09/20 04:00:00", "2026/10/01 03:59:59", ["NEXT-8"]
                    ),
                }
            },
            "YoStarJP": {
                "sideStoryStage": {
                    "live": activity(
                        "2026/09/15 04:00:00", "2026/09/29 03:59:59", ["JP-8"], 9
                    ),
                }
            },
        }

    def read(self, now=datetime(2026, 9, 16, tzinfo=UTC)):
        with (
            patch(
                "src.config.maa_stages.load_game_config",
                side_effect=[self.data, self.config],
            ) as loader,
            patch("src.config.maa_stages.datetime", wraps=datetime) as clock,
        ):
            clock.now.return_value = now
            result = load_activity_stages("MAA", "cache/gui/StageActivityV2.json")
        self.assertEqual(
            loader.call_args_list[0].args, ("MAA", "cache/gui/StageActivityV2.json")
        )
        return result

    def test_only_current_single_stages_and_order_are_exposed(self):
        before = copy.deepcopy(self.data)
        self.assertEqual(self.read(), ["ACT-8", "ACT-7", "ACT-8"])
        self.assertEqual(self.data, before)

    def test_server_comes_from_native_client_type(self):
        runtime = self.config["Configurations"]["Default"]["Gui"]["RuntimeSettings"]
        runtime["ClientType"] = 1
        self.assertEqual(self.read(), ["ACT-8", "ACT-7", "ACT-8"])
        runtime["ClientType"] = 3
        self.assertEqual(self.read(), ["JP-8"])

    def test_open_time_respects_resource_timezone(self):
        self.data["Official"]["sideStoryStage"] = {
            "live": activity("2026/09/16 04:00:00", "2026/09/17 04:00:00", ["ACT-8"])
        }
        self.assertEqual(self.read(datetime(2026, 9, 15, 19, 59, 59, tzinfo=UTC)), [])
        self.assertEqual(self.read(datetime(2026, 9, 15, 20, tzinfo=UTC)), [])
        self.assertEqual(
            self.read(datetime(2026, 9, 15, 20, 0, 1, tzinfo=UTC)), ["ACT-8"]
        )
        self.assertEqual(self.read(datetime(2026, 9, 16, 20, tzinfo=UTC)), [])

    def test_navigation_filter_uses_native_value_not_display_text(self):
        self.data["Official"]["sideStoryStage"]["live"]["Stages"] = [
            {"Value": "SSReopen-AT", "Display": "复刻活动导航"},
            {"Value": "ACT-8", "Display": "SSReopen 活动材料关"},
            {"Value": "ACT-7"},
            {"Value": "", "Display": "当前关卡"},
        ]
        self.assertEqual(self.read(), ["ACT-8", "ACT-7"])

    def test_missing_files_do_not_need_network_or_create_options(self):
        for data, config in ((None, self.config), (self.data, None)):
            with patch(
                "src.config.maa_stages.load_game_config", side_effect=[data, config]
            ):
                self.assertEqual(load_activity_stages("MAA", "missing.json"), [])

    def test_invalid_time_is_logged_and_skipped(self):
        self.data["Official"]["sideStoryStage"]["live"]["Activity"]["UtcExpireTime"] = (
            "bad"
        )
        with self.assertLogs("src.config.maa_stages", level="WARNING"):
            self.assertEqual(self.read(), [])

    def test_invalid_resource_is_logged(self):
        with (
            patch(
                "src.config.maa_stages.load_game_config",
                side_effect=ValueError("bad json"),
            ),
            self.assertLogs("src.config.maa_stages", level="WARNING"),
        ):
            self.assertEqual(load_activity_stages("MAA", "bad.json"), [])


class TestMaaStageMenus(unittest.TestCase):
    def test_only_activity_menu_reads_resource(self):
        declarations = get_daily_configs("MAA")
        normal = declarations[1]["options"]["values"]
        self.assertEqual(normal, declarations[2]["options"]["values"])
        with (
            patch(
                "src.config.daily_config.load_daily_map",
                return_value={"MAA": declarations},
            ),
            patch("src.config.set_config.load_game_config") as generic_resource,
            patch(
                "src.config.daily.load_activity_stages", return_value=["ACT-8"]
            ) as activity,
        ):
            menus = get_daily_map()["MAA"]["dailies"]
        self.assertEqual(
            {
                menu["display_name"]: [
                    option["physical_name"] for option in menu["options"]["values"]
                ]
                for menu in menus
            },
            {
                "活动关卡": ["ACT-8"],
                "理智作战": [option["display_name"] for option in normal],
                "剩余理智": [option["display_name"] for option in normal],
            },
        )
        generic_resource.assert_not_called()
        activity.assert_called_once_with(
            "MAA", "cache/gui/StageActivityV2.json", "config/gui.new.json"
        )

    def test_source_dispatch_does_not_depend_on_task_names_or_fixed_paths(self):
        declarations = get_daily_configs("MAA")
        activity = declarations[0]
        activity["display_name"] = "改名活动"
        activity["physical_name"] = "NativeActivity"
        activity["config"] = "profiles/gui.json"
        activity["options"]["source"]["path"] = "assets/activity.json"
        with (
            patch(
                "src.config.set_config.get_daily_configs",
                return_value=list(reversed(declarations)),
            ),
            patch(
                "src.config.daily.load_activity_stages", return_value=["ACT-8"]
            ) as loader,
        ):
            self.assertEqual(
                ArknightsConfig.get_task_lists(activity["options"]["source"]), ["ACT-8"]
            )
        loader.assert_called_once_with(
            "MAA", "assets/activity.json", "profiles/gui.json"
        )

    def test_undeclared_or_conflicting_source_asserts(self):
        with self.assertRaises(AssertionError):
            ArknightsConfig.get_task_lists({"path": "unknown.json"})
        declarations = get_daily_configs("MAA")
        source = declarations[0]["options"]["source"]
        duplicate = copy.deepcopy(declarations[0])
        duplicate["config"] = "other/gui.json"
        declarations.append(duplicate)
        with (
            patch("src.config.set_config.get_daily_configs", return_value=declarations),
            self.assertRaises(AssertionError),
        ):
            ArknightsConfig.get_task_lists(source)
