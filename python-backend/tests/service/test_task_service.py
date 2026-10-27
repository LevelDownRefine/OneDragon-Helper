"""任务卡聚合查询的读取边界。"""

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import patch

from src.config.native_task_switch import SwitchWriteResult
from src.service import app_service, task_service
from src.service.app_service import AppService


class TaskServiceTests(unittest.TestCase):
    def test_snapshot_keeps_order_identity_and_custom_scripts_without_loading_tasks(
        self,
    ):
        scripts = [
            {"display_name": "自定义", "script_path": "task.py", "enabled": False},
            {"display_name": "游戏", "script_path": "BetterGI.exe", "timeout": 90},
        ]
        with (
            patch.object(
                task_service, "load_config", return_value={"script_list": scripts}
            ),
            patch.object(task_service, "get_daily_readback") as read,
            patch.object(task_service, "get_daily_map") as menus,
            patch.object(task_service, "get_weekly_map") as weeklies,
        ):
            snapshot = AppService().app_snapshot()
        self.assertEqual(
            snapshot,
            {
                "default_icon_path": sys.executable,
                "scripts": [
                    {
                        "script_name": name,
                        "display_name": script["display_name"],
                        "script_path": script["script_path"],
                        "adapted": adapted,
                        "script_data": script,
                        "icon_path": sys.executable,
                    }
                    for script, name, adapted in zip(
                        scripts, ("自定义", "BetterGI"), (False, True), strict=True
                    )
                ],
            },
        )
        self.assertIsNot(snapshot["scripts"][0]["script_data"], scripts[0])
        read.assert_not_called()
        menus.assert_not_called()
        weeklies.assert_not_called()

    def test_custom_script_view_has_empty_tasks(self):
        with patch.object(
            task_service,
            "get_script",
            return_value={"display_name": "自定义", "script_path": "task.py"},
        ):
            self.assertEqual(
                AppService().script_view("自定义"),
                {
                    "script": {
                        "script_name": "自定义",
                        "display_name": "自定义",
                        "script_path": "task.py",
                        "adapted": False,
                        "icon_path": sys.executable,
                    },
                    "dailies": [],
                    "weeklies": [],
                },
            )

    def test_unknown_script_query_reports_error_before_loading_tasks(self):
        with (
            patch.object(task_service, "get_script", return_value=None),
            patch.object(task_service, "get_daily_readback") as read,
            self.assertRaisesRegex(task_service.InvalidTaskSelection, "脚本不存在"),
        ):
            AppService().script_view("不存在")
        read.assert_not_called()

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
        if fullname.split('.')[0] in ('PySide6', 'shiboken6') or fullname.startswith('gui'):
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


class SetScriptSwitchesTests(unittest.TestCase):
    """set_script_switches：名字对不上时返回原因，不写盘、不抛错。"""

    def test_returns_result_for_resolved_names(self):
        switch = mock.Mock()
        switch.apply.return_value = SwitchWriteResult(2, {})
        with patch.object(app_service, "native_task_switch_of", return_value=switch):
            result = AppService().set_script_switches(
                "BetterGI", {"甲": True, "乙": False}
            )
        self.assertTrue(result.ok)
        self.assertEqual(result.changed, 2)
        switch.apply.assert_called_once_with({"甲": True, "乙": False})

    def test_unknown_name_returns_reason(self):
        switch = mock.Mock()
        switch.apply.return_value = SwitchWriteResult(
            0, {"模拟宇宙_差分": "未找到该任务"}
        )
        with patch.object(app_service, "native_task_switch_of", return_value=switch):
            result = AppService().set_script_switches(
                "March7th-Launcher", {"模拟宇宙_差分": False}
            )
        self.assertFalse(result.ok)
        self.assertEqual(result.changed, 0)
        self.assertIn("未找到该任务", result.describe("March7th-Launcher"))

    def test_script_without_switches_reports_reason(self):
        with patch.object(app_service, "native_task_switch_of", return_value=None):
            result = AppService().set_script_switches("自定义脚本", {"任意": True})
        self.assertFalse(result.ok)
        self.assertEqual(result.reasons, {"任意": "脚本未声明任务开关"})

    def test_empty_states_reports_success(self):
        switch = mock.Mock()
        switch.apply.return_value = SwitchWriteResult(0, {})
        with patch.object(app_service, "native_task_switch_of", return_value=switch):
            result = AppService().set_script_switches("BetterGI", {})
        self.assertTrue(result.ok)
        switch.apply.assert_called_once_with({})
