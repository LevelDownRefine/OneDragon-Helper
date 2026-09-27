"""任务卡查询与开关校验的读取边界。"""

import unittest
from unittest.mock import patch

from src.service import task_service


class TaskServiceTests(unittest.TestCase):
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
