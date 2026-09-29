"""GUI/CLI 共用写接口：保留适配器语义，写入不依赖任务卡查询。"""

import unittest
from copy import deepcopy
from unittest.mock import patch, sentinel

from src.config import daily as daily_mod
from src.config import set_config as config_mod
from src.config import weekly as weekly_mod
from src.service import app_service, task_service
from src.service.app_service import AppService
from src.utils import utils_weekly


class CliForwardingTests(unittest.TestCase):
    def test_cli_uses_original_method_result_and_error(self):
        service = AppService()
        routes = (
            (
                "select_daily",
                ("脚本", "日常", "材料", True),
                "set_script_daily_task",
                ("脚本",),
                {"daily_display_name": "日常", "task_name": "材料", "sequence": True},
            ),
            (
                "select_daily",
                ("脚本",),
                "set_script_daily_task",
                ("脚本",),
                {"daily_display_name": None, "task_name": None, "sequence": None},
            ),
            (
                "enable_daily",
                ("脚本", "日常", False),
                "set_script_daily_enabled",
                ("脚本", "日常", False),
                {},
            ),
            (
                "select_weekly",
                ("脚本", "周常", "副本"),
                "set_script_weekly_task",
                ("脚本", "周常", "副本"),
                {},
            ),
            (
                "start_weekly",
                ("脚本", "周常", 0),
                "set_weekly_start_for",
                ("脚本", "周常", 0),
                {},
            ),
        )
        for cli_name, args, original_name, forwarded_args, forwarded_kwargs in routes:
            with self.subTest(cli=cli_name, args=args):
                cli = getattr(service, cli_name)
                with patch.object(
                    service, original_name, return_value=sentinel.result
                ) as original:
                    self.assertIs(cli(*args), sentinel.result)
                    original.assert_called_once_with(
                        *forwarded_args, **forwarded_kwargs
                    )
                error = OSError("原接口失败")
                with patch.object(
                    service, original_name, side_effect=error
                ) as original:
                    with self.assertRaises(OSError) as caught:
                        cli(*args)
                    self.assertIs(caught.exception, error)
                    original.assert_called_once_with(
                        *forwarded_args, **forwarded_kwargs
                    )


class TaskEditingTests(unittest.TestCase):
    def setUp(self):
        self.service = AppService()
        self.select_daily = self.service.set_script_daily_task
        self.enable_daily = self.service.set_script_daily_enabled
        self.select_weekly = self.service.set_script_weekly_task
        # 查询坏了也不能影响独立写入；菜单物化同样不应是写操作的前置条件。
        for name in (
            "script_view",
            "get_daily_map",
            "get_weekly_map",
            "get_daily_readback",
        ):
            self.enterContext(
                patch.object(task_service, name, side_effect=OSError("任务卡无法读取"))
            )
        self.enterContext(
            patch.object(daily_mod.Daily, "read", side_effect=OSError("副本无法反读"))
        )
        declaration = {
            "class": "Daily",
            "display_name": "日常",
            "config": "daily.json",
            "enable_key": "enabled",
            "options": {
                "key": "task",
                "values": [
                    {
                        "display_name": "材料",
                        "physical_name": "material",
                        "options": {
                            "key": "sequence",
                            "values": [{"display_name": "第一项", "physical_name": 1}],
                        },
                    }
                ],
            },
        }
        dynamic = deepcopy(declaration)
        dynamic.update(display_name="动态日常", config="dynamic.json")
        dynamic["options"]["values"][0]["options"] = {
            "key": "sequence",
            "source": {"path": "resource.json"},
        }
        no_switch = deepcopy(declaration)
        no_switch.update(display_name="无开关日常", config="no-switch.json")
        del no_switch["enable_key"]
        with patch.object(
            daily_mod,
            "get_daily_configs",
            return_value=[declaration, dynamic, no_switch],
        ):
            config = config_mod.ScriptConfig()
        self.config = config
        self.enterContext(
            patch.dict(config_mod._CONFIGS, {"脚本": lambda: config}, clear=True)
        )
        self.files = {
            "daily.json": {"task": "material", "sequence": 2, "enabled": False},
            "dynamic.json": {
                "task": "material",
                "sequence": "原副本",
                "enabled": False,
            },
        }
        self.reads = []
        self.saves = []

        def load(script, display, path, **kwargs):
            self.reads.append(path)
            assert path in self.files
            return deepcopy(self.files[path])

        def save(script, display, path, data):
            assert path in self.files
            self.files[path] = deepcopy(data)
            self.saves.append((path, deepcopy(data)))

        self.enterContext(
            patch.object(daily_mod, "load_script_config", side_effect=load)
        )
        self.enterContext(
            patch.object(daily_mod, "save_script_config", side_effect=save)
        )

    def test_unselected_or_unadapted_daily_is_noop(self):
        self.assertIsNone(self.select_daily("脚本"))
        for task in (None, "", "未选择"):
            with self.subTest(task=task):
                self.assertIsNone(self.select_daily("脚本", task_name=task))
        self.assertIsNone(self.select_daily("自定义", "日常", "材料", 1))
        self.assertEqual(self.reads, [])
        self.assertEqual(self.saves, [])

    def test_static_display_name_is_mapped_and_selection_enables_daily(self):
        self.assertIsNone(self.select_daily("脚本", "日常", "材料", "第一项"))
        self.assertEqual(
            self.saves,
            [
                ("daily.json", {"task": "material", "sequence": 1, "enabled": False}),
                ("daily.json", {"task": "material", "sequence": 1, "enabled": True}),
            ],
        )

    def test_dynamic_sequence_does_not_require_resource_menu(self):
        for sequence, expected in (
            (None, "原副本"),
            ("资源菜单之外的副本", "资源菜单之外的副本"),
        ):
            with self.subTest(sequence=sequence):
                self.assertIsNone(
                    self.select_daily("脚本", "动态日常", "材料", sequence)
                )
                self.assertEqual(
                    self.files["dynamic.json"],
                    {"task": "material", "sequence": expected, "enabled": True},
                )

    def test_invalid_static_selection_retains_adapter_assertion(self):
        for daily, task, sequence in (
            ("未知日常", "材料", 1),
            ("日常", "未知任务", 1),
            ("日常", "材料", None),
            ("日常", "材料", "未知二级项"),
        ):
            with self.subTest(daily=daily, task=task, sequence=sequence):
                with self.assertRaises(AssertionError):
                    self.select_daily("脚本", daily, task, sequence)
                self.assertEqual(self.saves, [])

    def test_enable_only_changes_target_switch_without_reading_selections(self):
        self.files["daily.json"]["enabled"] = True
        before = deepcopy(self.files["dynamic.json"])
        self.assertIsNone(self.enable_daily("脚本", "日常", False))
        self.assertEqual(
            self.files["daily.json"],
            {"task": "material", "sequence": 2, "enabled": False},
        )
        self.assertEqual(self.files["dynamic.json"], before)
        self.assertEqual(self.reads, ["daily.json"])
        self.assertEqual(len(self.saves), 1)

    def test_daily_without_switch_is_noop_even_without_config(self):
        self.assertIsNone(self.enable_daily("脚本", "无开关日常", False))
        self.assertEqual(self.reads, [])
        self.assertEqual(self.saves, [])

    def test_unknown_daily_switch_retains_adapter_assertion(self):
        for script, daily in (("自定义", "日常"), ("脚本", "未知日常")):
            with (
                self.subTest(script=script, daily=daily),
                self.assertRaises(AssertionError),
            ):
                self.enable_daily(script, daily, False)
        self.assertEqual(self.reads, [])
        self.assertEqual(self.saves, [])

    def test_weekly_selection_without_target_or_setter_is_noop(self):
        weekly = weekly_mod.Weekly(
            "脚本", {"display_name": "周常", "config": "weekly.json"}, "脚本"
        )
        with (
            patch.object(self.config, "_weeklies", [weekly]),
            patch.object(weekly_mod, "load_script_config") as read,
            patch.object(weekly_mod, "save_script_config") as write,
        ):
            for script, name in (
                ("脚本", "周常"),
                ("脚本", "未知周常"),
                ("自定义", "周常"),
            ):
                with self.subTest(script=script, name=name):
                    self.assertIsNone(self.select_weekly(script, name, "副本"))
        read.assert_not_called()
        write.assert_not_called()


class WeeklyStartEditingTests(unittest.TestCase):
    def setUp(self):
        self.service = AppService()
        self.start_weekly = self.service.set_weekly_start_for
        self.data = {
            "weekly_start": {"脚本": {"周常": 2, "另一周常": 3}},
            "weekly_timeouts": {"脚本": [60] * 7},
        }
        self.saves = []

        def save(data):
            self.data = deepcopy(data)
            self.saves.append(deepcopy(data))

        self.enterContext(
            patch.object(
                utils_weekly,
                "_load_weekly_file",
                side_effect=lambda: deepcopy(self.data),
            )
        )
        self.enterContext(
            patch.object(utils_weekly, "_dump_weekly_file", side_effect=save)
        )
        self.enterContext(
            patch.object(task_service, "script_view", side_effect=OSError("查询失败"))
        )

    def test_start_day_keeps_other_entries_and_saves_intent_before_game_side(self):
        def sync(script, weekly, day):
            self.assertEqual(self.data["weekly_start"][script][weekly], day)
            self.assertEqual(self.data["weekly_start"][script]["另一周常"], 3)
            self.assertEqual(self.data["weekly_timeouts"], {"脚本": [60] * 7})

        with patch.object(
            app_service, "set_weekly_start_day", side_effect=sync
        ) as game:
            for day in (0, 1, 7):
                with self.subTest(day=day):
                    self.assertIsNone(self.start_weekly("脚本", "周常", day))
            self.assertEqual(game.call_count, 3)
        self.assertEqual(len(self.saves), 3)

    def test_invalid_day_retains_assertion_and_never_writes(self):
        with patch.object(app_service, "set_weekly_start_day") as game:
            for day in (-1, 8, True, "1", 1.0):
                with self.subTest(day=day), self.assertRaises(AssertionError):
                    self.start_weekly("脚本", "周常", day)
        self.assertEqual(self.saves, [])
        game.assert_not_called()

    def test_game_side_failure_keeps_saved_intent_and_original_error(self):
        error = OSError("游戏配置不可写")
        with (
            patch.object(app_service, "set_weekly_start_day", side_effect=error),
            self.assertRaises(OSError) as caught,
        ):
            self.start_weekly("脚本", "周常", 0)
        self.assertIs(caught.exception, error)
        self.assertEqual(
            self.data["weekly_start"], {"脚本": {"周常": 0, "另一周常": 3}}
        )
        self.assertEqual(len(self.saves), 1)

    def test_unknown_weekly_still_saves_intent_and_skips_game_side(self):
        with (
            patch.dict(config_mod._CONFIGS, {}, clear=True),
            patch.object(weekly_mod, "save_script_config") as game,
        ):
            self.assertIsNone(self.start_weekly("脚本", "未知周常", 4))
        self.assertEqual(
            self.data["weekly_start"],
            {"脚本": {"周常": 2, "另一周常": 3, "未知周常": 4}},
        )
        game.assert_not_called()


class CliTaskEditingTests(TaskEditingTests):
    """对同样的输入与原生配置执行 CLI 入口，断言同一份行为契约。"""

    def setUp(self):
        super().setUp()
        self.select_daily = self.service.select_daily
        self.enable_daily = self.service.enable_daily
        self.select_weekly = self.service.select_weekly


class CliWeeklyStartEditingTests(WeeklyStartEditingTests):
    """CLI 周常起始日与 GUI 入口使用同一组持久化及失败场景。"""

    def setUp(self):
        super().setUp()
        self.start_weekly = self.service.start_weekly
