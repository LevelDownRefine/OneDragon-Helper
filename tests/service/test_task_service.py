"""任务卡查询与开关校验的读取边界。"""

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from src.service import task_service
from src.service.app_service import AppService


class TaskServiceTests(unittest.TestCase):
    def test_selection_preserves_json_types_and_reads_after_write(self):
        for allowed, selected in (
            (1, 1),
            (True, True),
            (False, False),
            ("副本", "副本"),
        ):
            with self.subTest(selected=selected):
                events = []
                result = {"saved": selected}
                with (
                    patch.object(task_service, "get_script", return_value={}),
                    patch.object(task_service, "is_adapted", return_value=True),
                    patch.object(
                        task_service, "get_daily_map", return_value=self.menu(allowed)
                    ),
                    patch.object(
                        task_service,
                        "set_config",
                        side_effect=lambda *args, events=events: events.append(
                            ("write", args)
                        ),
                    ),
                    patch.object(
                        task_service,
                        "script_view",
                        side_effect=lambda name, events=events, result=result: (
                            events.append(("read", name)) or result
                        ),
                    ),
                ):
                    actual = AppService().select_daily("脚本", "日常", "材料", selected)
                self.assertIs(actual, result)
                self.assertEqual(
                    events,
                    [("write", ("脚本", "日常", "材料", selected)), ("read", "脚本")],
                )
                self.assertIs(type(events[0][1][3]), type(selected))

    @staticmethod
    def menu(value):
        return {
            "脚本": {
                "dailies": [
                    {
                        "display_name": "日常",
                        "options": {
                            "values": [
                                {
                                    "display_name": "材料",
                                    "options": {"values": [{"physical_name": value}]},
                                }
                            ]
                        },
                    }
                ]
            }
        }

    def test_invalid_selections_never_reach_adapter(self):
        cases = (
            (1, True),
            (True, 1),
            (False, 0),
            (1, "1"),
            ("副本", "已删除"),
            (1, None),
            (1, 1.0),
        )
        with (
            patch.object(task_service, "get_script", return_value={}),
            patch.object(task_service, "is_adapted", return_value=True),
            patch.object(task_service, "set_config") as write,
        ):
            for allowed, selected in cases:
                with (
                    self.subTest(allowed=allowed, selected=selected),
                    patch.object(
                        task_service, "get_daily_map", return_value=self.menu(allowed)
                    ),
                    self.assertRaises(task_service.InvalidTaskSelection),
                ):
                    task_service.select_daily("脚本", "日常", "材料", selected)
            with patch.object(task_service, "get_daily_map", return_value=self.menu(1)):
                for daily, task in (("未知日常", "材料"), ("日常", "未知任务")):
                    with (
                        self.subTest(daily=daily, task=task),
                        self.assertRaises(task_service.InvalidTaskSelection),
                    ):
                        task_service.select_daily("脚本", daily, task, 1)
        write.assert_not_called()

    def test_unknown_or_unadapted_script_is_rejected(self):
        with patch.object(task_service, "set_config") as write:
            with (
                patch.object(task_service, "get_script", return_value=None),
                self.assertRaises(task_service.InvalidTaskSelection),
            ):
                task_service.select_daily("不存在", "日常", "材料", 1)
            with (
                patch.object(task_service, "get_script", return_value={}),
                patch.object(task_service, "is_adapted", return_value=False),
                self.assertRaises(task_service.InvalidTaskSelection),
            ):
                task_service.select_daily("未适配", "日常", "材料", 1)
        write.assert_not_called()

    def test_leaf_selection_accepts_only_null_sequence(self):
        menu = {
            "脚本": {
                "dailies": [
                    {
                        "display_name": "日常",
                        "options": {"values": [{"display_name": "单项"}]},
                    }
                ]
            }
        }
        with (
            patch.object(task_service, "get_script", return_value={}),
            patch.object(task_service, "is_adapted", return_value=True),
            patch.object(task_service, "get_daily_map", return_value=menu),
            patch.object(task_service, "set_config") as write,
            patch.object(task_service, "script_view", return_value={"saved": True}),
        ):
            self.assertEqual(
                task_service.select_daily("脚本", "日常", "单项"), {"saved": True}
            )
            for value in (0, False, ""):
                with (
                    self.subTest(value=value),
                    self.assertRaises(task_service.InvalidTaskSelection),
                ):
                    task_service.select_daily("脚本", "日常", "单项", value)
        write.assert_called_once_with("脚本", "日常", "单项", None)

    def test_weekly_choice_and_day_validate_before_writing(self):
        definitions = [
            {"display_name": "周常", "options": {"values": [{"display_name": "副本"}]}}
        ]
        service = AppService()
        with (
            patch.object(task_service, "get_script", return_value={}),
            patch.object(task_service, "get_weekly_map", return_value=definitions),
            patch.object(task_service, "set_weekly_task") as write,
            patch.object(task_service, "script_view", return_value={"saved": True}),
            patch.object(service, "set_weekly_start_for") as start,
        ):
            for weekly, task in (("不存在", "副本"), ("周常", "失效副本")):
                with (
                    self.subTest(weekly=weekly, task=task),
                    self.assertRaises(task_service.InvalidTaskSelection),
                ):
                    service.select_weekly("脚本", weekly, task)
            for day in (-1, 8, True, "1"):
                with (
                    self.subTest(day=day),
                    self.assertRaises(task_service.InvalidTaskSelection),
                ):
                    service.start_weekly("脚本", "周常", day)
            write.assert_not_called()
            start.assert_not_called()
            self.assertEqual(
                service.select_weekly("脚本", "周常", "副本"), {"saved": True}
            )
            self.assertEqual(service.start_weekly("脚本", "周常", 0), {"saved": True})
        write.assert_called_once_with("脚本", "周常", "副本")
        start.assert_called_once_with("脚本", "周常", 0)

    def test_query_rereads_state_and_distinguishes_disabled_from_unset(self):
        script = {"display_name": "脚本", "script_path": "脚本.exe"}
        state = {"name": "日常", "task": "材料", "sequence": 1, "enabled": True}
        with (
            patch.object(task_service, "get_script", return_value=script),
            patch.object(task_service, "is_adapted", return_value=True),
            patch.object(task_service, "get_daily_map", return_value=self.menu(1)),
            patch.object(
                task_service, "get_daily_readback", side_effect=lambda _: [dict(state)]
            ),
            patch.object(
                task_service, "get_weekly_map", return_value=[{"display_name": "周常"}]
            ),
            patch.object(task_service, "get_weekly_task", return_value=None),
            patch.object(
                task_service,
                "get_weekly_start_map",
                side_effect=[{}, {"脚本": {"周常": 0}}],
            ),
        ):
            first = task_service.script_view("脚本")
            state.update(sequence=2, enabled=False)
            second = task_service.script_view("脚本")
        self.assertEqual(first["dailies"][0]["sequence"], 1)
        self.assertEqual(second["dailies"][0]["sequence"], 2)
        self.assertIs(second["dailies"][0]["enabled"], False)
        self.assertIsNone(first["weeklies"][0]["start_day"])
        self.assertEqual(second["weeklies"][0]["start_day"], 0)
        self.assertEqual(
            set(second["dailies"][0]),
            {"name", "task", "sequence", "enabled", "options"},
        )

    def test_service_import_does_not_load_gui(self):
        code = """
import importlib.abc
import sys
class NoGui(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in ('PySide6', 'shiboken6') or fullname.startswith('src.gui'):
            raise AssertionError('service loaded GUI: ' + fullname)
sys.meta_path.insert(0, NoGui())
from src.service.app_service import AppService
AppService()
"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_enable_writes_before_reading_unrelated_weeklies(self):
        state = {"name": "日常", "task": "副本", "sequence": None, "enabled": True}
        saved = []

        def write(script_name, daily_name, enabled):
            saved.append((script_name, daily_name, enabled))
            state["enabled"] = enabled

        def read_weeklies(_script):
            self.assertEqual(saved, [("脚本", "日常", False)])
            return []

        with (
            patch.object(
                task_service,
                "get_script",
                return_value={"display_name": "脚本", "script_path": "脚本.exe"},
            ),
            patch.object(
                task_service,
                "get_daily_readback",
                side_effect=lambda _script: [dict(state)],
            ),
            patch.object(
                task_service,
                "get_daily_map",
                return_value={
                    "脚本": {
                        "dailies": [{"display_name": "日常", "options": {"values": []}}]
                    }
                },
            ) as menus,
            patch.object(task_service, "set_daily_enabled", side_effect=write),
            patch.object(
                task_service, "get_weekly_map", side_effect=read_weeklies
            ) as weeklies,
        ):
            result = task_service.enable_daily("脚本", "日常", False)
        self.assertEqual(result["dailies"], [{**state, "options": {"values": []}}])
        self.assertIs(result["dailies"][0]["enabled"], False)
        self.assertEqual(result["weeklies"], [])
        menus.assert_called_once_with("脚本")
        weeklies.assert_called_once_with("脚本")

    def test_unavailable_switch_does_not_load_menus_or_write(self):
        for records in (
            [],
            [{"name": "其他日常", "enabled": True}],
            [{"name": "日常", "enabled": None}],
        ):
            with (
                self.subTest(records=records),
                patch.object(task_service, "get_script", return_value={}),
                patch.object(task_service, "get_daily_readback", return_value=records),
                patch.object(
                    task_service,
                    "get_daily_map",
                    side_effect=AssertionError("无效开关不加载菜单"),
                ),
                patch.object(
                    task_service,
                    "get_weekly_map",
                    side_effect=AssertionError("无效开关不读取周常"),
                ),
                patch.object(task_service, "set_daily_enabled") as write,
            ):
                with self.assertRaises(task_service.InvalidTaskSelection):
                    task_service.enable_daily("脚本", "日常", False)
                write.assert_not_called()
