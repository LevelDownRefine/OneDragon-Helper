"""MAA 本地活动缓存的服务器、开放时间和缺失回退。"""

import copy
import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from src.config.daily_config import get_daily_map
from src.config.maa_stages import load_activity_stages, load_normal_stages
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


class TestMaaNormalStages(unittest.TestCase):
    def setUp(self):
        self.stages = [
            {"code": code, "stageId": stage_id}
            for code, stage_id in (
                ("1-10", "main_01-10"),
                ("1-7", "main_01-07"),
                ("R8-11", "main_08-13"),
                ("S4-1", "sub_04-1"),
                ("12-17", "main_12-15"),
                ("12-17", "tough_12-15"),
                ("12-17", "tough_12-15"),
                ("19-1", "main_19-01"),
                ("AP-5", "wk_toxic_5"),
                ("AP-1", "wk_toxic_1"),
                ("CE-5", "wk_melee_5"),
                ("CE-6", "wk_melee_6"),
                ("CA-5", "wk_fly_5"),
                ("PR-B-2", "pro_b_2"),
                ("ACT-8", "act99side_08"),
                ("Annihilation", "camp_01"),
            )
        ]
        self.tasks = dict.fromkeys(
            ("Episode1", "Episode4", "Episode8", "Episode12", "ChapterDifficultyHard"),
            {},
        )
        self.supplies = {
            "AP-5": {},
            "CE-5": {"next": ["CE-6"]},
            "CE-6": {},
            "CA-5": {},
            "PR-B-2": {},
        }
        self.files = {
            "resource/stages.json": self.stages,
            "resource/tasks/tasks.json": self.tasks,
            "resource/tasks/Stages/Supplies.json": self.supplies,
        }

    def load(self, source="resource/stages.json"):
        def read(script, path):
            self.assertEqual(script, "MAA")
            if path not in self.files:
                return None
            return self.files[path]

        with patch("src.config.maa_stages.load_game_config", side_effect=read):
            return load_normal_stages("MAA", source)

    def test_menu_keeps_mas_common_main_stages_supplies_and_chips(self):
        before = copy.deepcopy(self.files)
        self.assertEqual(
            self.load(),
            [
                "1-7",
                "R8-11",
                "12-17-HARD",
                "AP-5",
                "CA-5",
                "CE-6",
                "PR-B-2",
            ],
        )
        self.assertEqual(self.files, before)

    def test_old_monolithic_tasks_and_declared_resource_directory(self):
        self.files = {
            "assets/stages.json": self.stages,
            "assets/tasks.json": self.tasks | self.supplies,
        }
        stages = self.load("assets/stages.json")
        self.assertIn("PR-B-2", stages)
        self.assertIn("12-17-HARD", stages)

    def test_new_main_stages_stay_hidden_but_resource_stages_update(self):
        self.stages.append({"code": "19-2", "stageId": "main_19-02"})
        self.assertNotIn("19-2", self.load())
        self.tasks["Episode19"] = {}
        self.assertNotIn("19-2", self.load())
        self.stages.append({"code": "SK-5", "stageId": "wk_armor_5"})
        self.supplies["SK-5"] = {}
        self.assertIn("SK-5", self.load())
        del self.supplies["CA-5"]
        self.assertNotIn("CA-5", self.load())

    def test_hard_stage_requires_native_difficulty_switch(self):
        del self.tasks["ChapterDifficultyHard"]
        self.assertNotIn("12-17-HARD", self.load())
        self.assertIn("1-7", self.load())
        self.assertIn("R8-11", self.load())

    def test_common_main_stage_still_requires_native_navigation(self):
        del self.tasks["Episode8"]
        self.assertNotIn("R8-11", self.load())

    def test_missing_or_invalid_resources_do_not_create_fallback_choices(self):
        for path in ("resource/stages.json", "resource/tasks/tasks.json"):
            files = self.files.copy()
            del self.files[path]
            self.assertEqual(self.load(), [])
            self.files = files
        with (
            patch(
                "src.config.maa_stages.load_game_config",
                side_effect=ValueError("bad json"),
            ),
            self.assertLogs("src.config.maa_stages", level="WARNING"),
        ):
            self.assertEqual(load_normal_stages("MAA", "resource/stages.json"), [])

    def test_menu_dispatch_uses_same_normal_list_for_both_roles(self):
        with (
            patch(
                "src.config.daily_config.load_daily_map",
                return_value={"MAA": get_daily_configs("MAA")},
            ),
            patch(
                "src.config.daily.load_normal_stages", return_value=["PR-B-2", "R8-11"]
            ) as normal,
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
                "理智作战": ["PR-B-2", "R8-11"],
                "剩余理智": ["PR-B-2", "R8-11"],
            },
        )
        self.assertEqual(normal.call_count, 2)
        normal.assert_called_with("MAA", "resource/stages.json")
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
        source = declarations[1]["options"]["source"]
        declarations[0]["options"]["source"] = source
        with (
            patch("src.config.set_config.get_daily_configs", return_value=declarations),
            self.assertRaises(AssertionError),
        ):
            ArknightsConfig.get_task_lists(source)
