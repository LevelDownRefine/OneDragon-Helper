"""测试 src/gui/controllers/task_card.py：多周常 items 与选副本持久化。"""

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from src.gui.controllers import task_card as task_card_mod
from src.gui.controllers.task_card import TaskCardController
from src.service.app_service import AppService, get_daily_map, get_weekly_map
from src.utils.utils_yaml import dump_yaml_file


class _FakeGameList:
    def __init__(self, games):
        self.games = games
        self.current_game = games[0]


class _EmptyGameList:
    """config 删空后的 game_list 替身：current_game 为 None。"""

    current_game = None


def _write_defs(tmp, data):
    """写临时 task_list.yml（周常声明配置）。"""
    path = os.path.join(tmp.name, "task_list.yml")
    data = {
        script: [{**task, "type": "weekly"} for task in tasks]
        for script, tasks in data.items()
    }
    dump_yaml_file(path, data)
    return path


def _make_controller(script_name="March7th-Launcher", display_name="崩铁"):
    games = [{"script_name": script_name, "display_name": display_name}]
    game_list = _FakeGameList(games)
    service = MagicMock()
    # 日常/周常声明经 service 分别读取，周常路径已由用例隔离。
    service.get_weekly_map.side_effect = get_weekly_map
    service.get_daily_map.side_effect = get_daily_map
    service.get_daily_items.side_effect = AppService().get_daily_items
    service.get_weekly_items.side_effect = AppService().get_weekly_items
    service.get_weekly_task_options.side_effect = AppService().get_weekly_task_options
    service.get_weekly_start.return_value = None
    toast = MagicMock()
    return TaskCardController(game_list, service, toast)


class TestWeeklyItems(unittest.TestCase):
    def test_weekly_rows_are_provided_by_service(self):
        ctrl = _make_controller()
        rows = [{"name": "周本", "has_options": True, "selection_label": "当前副本"}]
        ctrl._app_service.get_weekly_items.side_effect = None
        ctrl._app_service.get_weekly_items.return_value = rows
        self.assertEqual(ctrl.weekly_items, rows)
        ctrl._app_service.get_weekly_items.assert_called_once_with("March7th-Launcher")
        ctrl._app_service.get_weekly_map.assert_not_called()

    def test_weekly_items_for_star_rail(self):
        """崩铁两种周常（来自 task_list.yml）：货币战争(无副本) + 历战余响(有副本)。"""
        tmp = tempfile.TemporaryDirectory()
        defs_path = _write_defs(
            tmp,
            {
                "March7th-Launcher": [
                    {"display_name": "货币战争"},
                    {
                        "display_name": "历战余响",
                        "options": {
                            "values": [
                                {"display_name": "无"},
                                {"display_name": "铁骸的锈冢"},
                                {"display_name": "晨昏的回眸"},
                            ]
                        },
                    },
                ]
            },
        )
        with (
            patch(
                "src.config.task_config.get_task_list_yml_path_under_root",
                return_value=defs_path,
            ),
            patch("src.service.app_service.get_weekly_task", return_value=(None, None)),
        ):
            ctrl = _make_controller()
            items = ctrl.weekly_items
        tmp.cleanup()
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["name"], "货币战争")
        self.assertFalse(items[0]["has_options"])
        self.assertEqual(items[0]["selection_label"], "")
        self.assertEqual(items[1]["name"], "历战余响")
        self.assertTrue(items[1]["has_options"])
        # 无配置/未选：反读 None → 占位提示（周常侧不设回退）
        self.assertEqual(items[1]["selection_label"], "选择副本")

    def test_weekly_dungeon_options_reads_from_config(self):
        """副本清单来自 task_list.yml 的 options 字段，不再依赖游戏脚本配置。"""
        tmp = tempfile.TemporaryDirectory()
        defs_path = _write_defs(
            tmp,
            {
                "March7th-Launcher": [
                    {
                        "display_name": "历战余响",
                        "options": {
                            "values": [
                                {"display_name": "无"},
                                {"display_name": "铁骸的锈冢"},
                                {"display_name": "晨昏的回眸"},
                            ]
                        },
                    }
                ]
            },
        )
        with patch(
            "src.config.task_config.get_task_list_yml_path_under_root",
            return_value=defs_path,
        ):
            ctrl = _make_controller()
            options = ctrl.weekly_task_options("历战余响")
        tmp.cleanup()
        self.assertEqual(options, ["无", "铁骸的锈冢", "晨昏的回眸"])

    def test_weekly_dungeon_options_unknown_weekly_returns_empty(self):
        """未声明的周常名 → 空列表。"""
        tmp = tempfile.TemporaryDirectory()
        defs_path = _write_defs(
            tmp,
            {
                "March7th-Launcher": [
                    {
                        "display_name": "历战余响",
                        "options": {
                            "values": [
                                {"display_name": "无"},
                                {"display_name": "铁骸的锈冢"},
                            ]
                        },
                    }
                ]
            },
        )
        with patch(
            "src.config.task_config.get_task_list_yml_path_under_root",
            return_value=defs_path,
        ):
            ctrl = _make_controller()
            self.assertEqual(ctrl.weekly_task_options("不存在"), [])
        tmp.cleanup()

    def test_weekly_dungeon_options_without_dungeons_key(self):
        """无 options 字段的周常 → 空列表（不报 KeyError）。"""
        tmp = tempfile.TemporaryDirectory()
        defs_path = _write_defs(
            tmp,
            {
                "March7th-Launcher": [
                    {"display_name": "货币战争"},
                ]
            },
        )
        with patch(
            "src.config.task_config.get_task_list_yml_path_under_root",
            return_value=defs_path,
        ):
            ctrl = _make_controller()
            self.assertEqual(ctrl.weekly_task_options("货币战争"), [])
        tmp.cleanup()

    def test_weekly_supported_follows_config(self):
        """weekly_supported 唯一真相源为 task_list.yml：声明即支持，未声明即不支持。"""
        # 崩铁声明、鸣潮未声明
        tmp = tempfile.TemporaryDirectory()
        defs_path = _write_defs(
            tmp,
            {
                "March7th-Launcher": [
                    {
                        "display_name": "历战余响",
                        "options": {"values": [{"display_name": "无"}]},
                    }
                ]
            },
        )
        with patch(
            "src.config.task_config.get_task_list_yml_path_under_root",
            return_value=defs_path,
        ):
            ctrl_star = _make_controller("March7th-Launcher", "崩铁")
            ctrl_ww = _make_controller("ok-ww", "鸣潮")
            self.assertTrue(ctrl_star.weekly_supported)
            self.assertFalse(ctrl_ww.weekly_supported)
        tmp.cleanup()

    def test_weekly_items_empty_for_non_weekly_script(self):
        tmp = tempfile.TemporaryDirectory()
        # ok-ww 不在 task_list.yml 声明 → 空列表
        defs_path = _write_defs(tmp, {})
        with patch(
            "src.config.task_config.get_task_list_yml_path_under_root",
            return_value=defs_path,
        ):
            ctrl = _make_controller("ok-ww", "鸣潮")
            self.assertEqual(ctrl.weekly_items, [])
        tmp.cleanup()


class TestSelectWeeklyDungeon(unittest.TestCase):
    def test_select_weekly_dungeon_writes_config(self):
        """选副本：经 service 写脚本自身 config（周常侧无 no-op 脚本）。"""
        ctrl = _make_controller()
        ctrl.selectWeeklyTaskOption("历战余响", "铁骸的锈冢")
        # 写脚本自身 config 的 instance_names（M7A 约定键名），经 service 入口
        ctrl._app_service.set_weekly_task_option.assert_called_once_with(
            "March7th-Launcher", "历战余响", "铁骸的锈冢"
        )


class TestSelectDungeonWritesSubscriptConfig(unittest.TestCase):
    """日常副本选择：实时落盘子脚本 config（与链生成解耦，不再依赖运行全体）。"""

    def test_select_dungeon_writes_subscript_config(self):
        """选中日常副本：实时经 service 落盘子脚本 config。"""
        ctrl = _make_controller("ok-ww", "鸣潮")
        ctrl.selectDailyTask("每日任务", "凝素领域", "5")
        # 实时落盘：option_name + sequence（鸣潮要求 sequence 非空），经 service 入口
        ctrl._app_service.set_daily_task.assert_called_once_with(
            "ok-ww", "每日任务", option_name="凝素领域", sequence="5"
        )


class TestDailyItems(unittest.TestCase):
    def test_two_dailies_have_independent_labels_and_options(self):
        ctrl = _make_controller("example", "示例")
        definitions = [
            {"display_name": "资源", "options": {"values": [{"display_name": "金币"}]}},
            {
                "display_name": "清理",
                "options": {
                    "values": [
                        {
                            "display_name": "经验",
                            "options": {
                                "values": [{"display_name": "高级", "physical_name": 2}]
                            },
                        }
                    ]
                },
            },
        ]
        ctrl._daily_map_cache = {"example": definitions}
        with patch(
            "src.service.app_service.get_daily_task",
            side_effect=[("金币", None), ("经验", 2)],
        ) as read:
            rows = ctrl.daily_items
        self.assertEqual([r["name"] for r in rows], ["资源", "清理"])
        self.assertEqual([r["selection_label"] for r in rows], ["金币", "高级"])
        self.assertEqual(rows[0]["options"], [{"name": "金币", "options": []}])
        self.assertEqual(
            rows[1]["options"][0]["options"],
            [{"name": "高级", "value": 2}],
        )
        self.assertEqual(read.call_count, 2)
        self.assertEqual(read.call_args_list[1].args, ("example", "清理"))
        ctrl.selectDailyTask("清理", "经验", 2)
        ctrl._app_service.set_daily_task.assert_called_once_with(
            "example", "清理", option_name="经验", sequence=2
        )

    def test_missing_declaration_has_no_rows(self):
        ctrl = _make_controller()
        self.assertEqual(ctrl.daily_items, [])


class TestWeeklyItemsReadback(unittest.TestCase):
    """weekly_items 的 selection_label 优先反读子脚本 config。"""

    def test_weekly_dungeon_label_prefers_config(self):
        tmp = tempfile.TemporaryDirectory()
        defs_path = _write_defs(
            tmp,
            {
                "March7th-Launcher": [
                    {
                        "display_name": "历战余响",
                        "options": {
                            "values": [
                                {"display_name": "无"},
                                {"display_name": "铁骸的锈冢"},
                            ]
                        },
                    }
                ]
            },
        )
        with (
            patch(
                "src.config.task_config.get_task_list_yml_path_under_root",
                return_value=defs_path,
            ),
            patch(
                "src.service.app_service.get_weekly_task",
                return_value=("铁骸的锈冢", None),
            ),
        ):
            ctrl = _make_controller()
            items = ctrl.weekly_items
        tmp.cleanup()
        self.assertEqual(items[0]["selection_label"], "铁骸的锈冢")


class TestEmptyCurrentSentinel(unittest.TestCase):
    """config 删空（current_game None）时回退哨兵空项：各 QML 属性安全求值。"""

    def test_properties_degrade_without_raising(self):
        service = MagicMock()
        service.get_weekly_map.return_value = {}
        service.get_daily_items.return_value = []
        service.get_weekly_items.return_value = []
        service.get_weekly_start.return_value = None
        ctrl = TaskCardController(_EmptyGameList(), service, MagicMock())
        self.assertIs(ctrl._current, task_card_mod._EMPTY_GAME)
        self.assertEqual(ctrl.task_title, "")
        self.assertFalse(ctrl.task_adapted)
        self.assertFalse(ctrl.weekly_supported)
        self.assertEqual(ctrl.daily_items, [])
        self.assertEqual(ctrl.weekly_items, [])


if __name__ == "__main__":
    unittest.main()
