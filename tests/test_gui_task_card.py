"""测试 src/gui/controllers/task_card.py：多周常 items 与选副本持久化。"""

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from src.config.daily_task_config import get_daily_task_map, get_weekly_map
from src.gui.controllers import task_card as task_card_mod
from src.gui.controllers.task_card import TaskCardController
from src.utils.utils_yaml import dump_yaml_file


class _FakeGameList:
    def __init__(self, games):
        self.games = games
        self.current_game = games[0]


class _EmptyGameList:
    """config 删空后的 game_list 替身：current_game 为 None。"""

    current_game = None


def _write_defs(tmp, data):
    """写临时 weekly_task_list.yml（周常声明配置）。"""
    path = os.path.join(tmp.name, "weekly_task_list.yml")
    declarations = {}
    for script_name, tasks in data.items():
        declarations[script_name] = []
        for task in tasks:
            definition = {"display_name": task["name"]}
            if "tasks" in task:
                definition["options"] = {
                    "values": [{"display_name": name} for name in task["tasks"]]
                }
            declarations[script_name].append(definition)
    dump_yaml_file(path, declarations)
    return path


def _make_controller(script_name="March7th-Launcher", display_name="崩铁"):
    games = [{"script_name": script_name, "display_name": display_name}]
    game_list = _FakeGameList(games)
    service = MagicMock()
    # 副本/周常声明经真实 task_config 模块函数读取（weekly_task_list.yml 路径已由用例 patch）。
    service.get_weekly_map.side_effect = get_weekly_map
    service.get_daily_task_map.side_effect = get_daily_task_map
    service.get_weekly_start.return_value = None
    toast = MagicMock()
    return TaskCardController(game_list, service, toast)


class TestWeeklyItems(unittest.TestCase):
    def test_weekly_items_for_star_rail(self):
        """崩铁两种周常（来自 weekly_task_list.yml）：货币战争(无副本) + 历战余响(有副本)。"""
        tmp = tempfile.TemporaryDirectory()
        defs_path = _write_defs(
            tmp,
            {
                "March7th-Launcher": [
                    {"name": "货币战争"},
                    {
                        "name": "历战余响",
                        "tasks": ["无", "铁骸的锈冢", "晨昏的回眸"],
                    },
                ]
            },
        )
        with (
            patch(
                "src.config.task_config.get_weekly_task_list_yml_path_under_root",
                return_value=defs_path,
            ),
            patch.object(task_card_mod, "get_weekly_task", return_value=None),
        ):
            ctrl = _make_controller()
            items = ctrl.weekly_items
        tmp.cleanup()
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["name"], "货币战争")
        self.assertFalse(items[0]["has_task"])
        self.assertEqual(items[0]["task_label"], "")
        self.assertEqual(items[1]["name"], "历战余响")
        self.assertTrue(items[1]["has_task"])
        # 无配置/未选：反读 None → 占位提示（周常侧不设回退）
        self.assertEqual(items[1]["task_label"], "选择副本")

    def test_weekly_task_options_reads_from_config(self):
        """副本清单来自 weekly_task_list.yml 的 tasks 字段，不再依赖游戏脚本配置。"""
        tmp = tempfile.TemporaryDirectory()
        defs_path = _write_defs(
            tmp,
            {
                "March7th-Launcher": [
                    {
                        "name": "历战余响",
                        "tasks": ["无", "铁骸的锈冢", "晨昏的回眸"],
                    },
                ]
            },
        )
        with patch(
            "src.config.task_config.get_weekly_task_list_yml_path_under_root",
            return_value=defs_path,
        ):
            ctrl = _make_controller()
            options = ctrl.weekly_task_options("历战余响")
        tmp.cleanup()
        self.assertEqual(options, ["无", "铁骸的锈冢", "晨昏的回眸"])

    def test_weekly_task_options_unknown_weekly_returns_empty(self):
        """未声明的周常名 → 空列表。"""
        tmp = tempfile.TemporaryDirectory()
        defs_path = _write_defs(
            tmp,
            {
                "March7th-Launcher": [
                    {"name": "历战余响", "tasks": ["无", "铁骸的锈冢"]},
                ]
            },
        )
        with patch(
            "src.config.task_config.get_weekly_task_list_yml_path_under_root",
            return_value=defs_path,
        ):
            ctrl = _make_controller()
            self.assertEqual(ctrl.weekly_task_options("不存在"), [])
        tmp.cleanup()

    def test_weekly_task_options_without_tasks_key(self):
        """无 tasks 字段的周常 → 空列表（不报 KeyError）。"""
        tmp = tempfile.TemporaryDirectory()
        defs_path = _write_defs(
            tmp,
            {
                "March7th-Launcher": [
                    {"name": "货币战争"},
                ]
            },
        )
        with patch(
            "src.config.task_config.get_weekly_task_list_yml_path_under_root",
            return_value=defs_path,
        ):
            ctrl = _make_controller()
            self.assertEqual(ctrl.weekly_task_options("货币战争"), [])
        tmp.cleanup()

    def test_weekly_supported_follows_config(self):
        """weekly_supported 唯一真相源为 weekly_task_list.yml：声明即支持，未声明即不支持。"""
        # 崩铁声明、鸣潮未声明
        tmp = tempfile.TemporaryDirectory()
        defs_path = _write_defs(
            tmp,
            {
                "March7th-Launcher": [
                    {"name": "历战余响", "tasks": ["无"]},
                ]
            },
        )
        with patch(
            "src.config.task_config.get_weekly_task_list_yml_path_under_root",
            return_value=defs_path,
        ):
            ctrl_star = _make_controller("March7th-Launcher", "崩铁")
            ctrl_ww = _make_controller("ok-ww", "鸣潮")
            self.assertTrue(ctrl_star.weekly_supported)
            self.assertFalse(ctrl_ww.weekly_supported)
        tmp.cleanup()

    def test_weekly_items_empty_for_non_weekly_script(self):
        tmp = tempfile.TemporaryDirectory()
        # ok-ww 不在 weekly_task_list.yml 声明 → 空列表
        defs_path = _write_defs(tmp, {})
        with patch(
            "src.config.task_config.get_weekly_task_list_yml_path_under_root",
            return_value=defs_path,
        ):
            ctrl = _make_controller("ok-ww", "鸣潮")
            self.assertEqual(ctrl.weekly_items, [])
        tmp.cleanup()


class TestSelectWeeklyTask(unittest.TestCase):
    def test_select_weekly_daily_task_writes_config(self):
        """选副本：经 service 写脚本自身 config（周常侧无 no-op 脚本）。"""
        ctrl = _make_controller()
        ctrl.selectWeeklyTask("历战余响", "铁骸的锈冢")
        # 写脚本自身 config 的 instance_names（M7A 约定键名），经 service 入口
        ctrl._app_service.set_script_weekly_task.assert_called_once_with(
            "March7th-Launcher", "历战余响", "铁骸的锈冢"
        )


class TestSelectDailyTaskWritesSubscriptConfig(unittest.TestCase):
    """日常副本选择：实时落盘子脚本 config（与链生成解耦，不再依赖运行全体）。"""

    def test_select_daily_task_writes_subscript_config(self):
        """选中日常副本：实时经 service 落盘子脚本 config，并带上该行所属日常。"""
        ctrl = _make_controller("ok-ww", "鸣潮")
        ctrl.selectDailyTask("每日任务", "凝素领域", "5")
        # 实时落盘：task_name + sequence（鸣潮要求 sequence 非空），经 service 入口
        ctrl._app_service.set_script_daily_task.assert_called_once_with(
            "ok-ww",
            task_name="凝素领域",
            sequence="5",
            daily_display_name="每日任务",
        )


class TestSetDailyEnabled(unittest.TestCase):
    """日常开关：经 service 落盘子脚本 config 的日常开关。"""

    def test_set_daily_enabled_writes_through_service(self):
        ctrl = _make_controller("ok-nte", "异环")
        ctrl.setDailyEnabled("追猎目标", False)
        ctrl._app_service.set_script_daily_enabled.assert_called_once_with(
            "ok-nte", "追猎目标", False
        )


class TestDailyItems(unittest.TestCase):
    """daily_items：一次反读记录 + 声明菜单 → 每行 chip 文案与「不启用」入口。"""

    def _items(self, ctrl, records):
        with patch.object(task_card_mod, "get_daily_readback", return_value=records):
            return ctrl.daily_items

    def test_prefers_readback_over_declared(self):
        """反读有真相时以反读为准，不走声明项回退。"""
        ctrl = _make_controller("ok-ww", "鸣潮")
        ctrl._daily_task_options_cache = {
            "ok-ww": [
                {"name": "每日任务", "options": [{"name": "声明项", "sequences": []}]}
            ]
        }
        items = self._items(
            ctrl,
            [
                {
                    "name": "每日任务",
                    "task": "凝素领域",
                    "sequence": "5",
                    "enabled": None,
                }
            ],
        )
        self.assertEqual(items[0]["task_label"], "凝素领域")

    def test_nte_daily_shows_daily_task_and_sequence(self):
        """异环：空幕 · 轨道之夜（选项不自包含副本名，必须两者同显）。"""
        ctrl = _make_controller("ok-nte", "异环")
        ctrl._daily_task_options_cache = {
            "ok-nte": [
                {
                    "name": "异象界域",
                    "options": [
                        {
                            "name": "空幕",
                            "sequences": [
                                {"label": "光暗", "value": 1},
                                {"label": "轨道之夜", "value": 6},
                            ],
                        }
                    ],
                }
            ]
        }
        items = self._items(
            ctrl,
            [{"name": "异象界域", "task": "空幕", "sequence": 6, "enabled": True}],
        )
        self.assertEqual(items[0]["task_label"], "空幕 · 轨道之夜")

    def test_daily_name_is_exposed_for_multi_daily_row(self):
        """多日常：每行带自己的日常展示名（QML 据此区分下拉）。"""
        ctrl = _make_controller("ok-nte", "异环")
        ctrl._daily_task_options_cache = {
            "ok-nte": [
                {"name": "异象界域", "options": []},
                {"name": "追猎目标", "options": []},
            ]
        }
        items = self._items(
            ctrl,
            [
                {"name": "异象界域", "task": None, "sequence": None, "enabled": True},
                {"name": "追猎目标", "task": None, "sequence": None, "enabled": True},
            ],
        )
        self.assertEqual([item["name"] for item in items], ["异象界域", "追猎目标"])

    def test_disabled_daily_shows_disabled_and_can_disable(self):
        """被停用的日常：chip 显示「不启用」，该行提供「不启用」入口。"""
        ctrl = _make_controller("ok-nte", "异环")
        ctrl._daily_task_options_cache = {
            "ok-nte": [
                {
                    "name": "追猎目标",
                    "options": [{"name": "追猎目标", "sequences": []}],
                }
            ]
        }
        items = self._items(
            ctrl,
            [
                {
                    "name": "追猎目标",
                    "task": "音霸魔王",
                    "sequence": None,
                    "enabled": False,
                }
            ],
        )
        self.assertEqual(items[0]["task_label"], "不启用")
        self.assertTrue(items[0]["can_disable"])
        self.assertTrue(items[0]["disabled"])

    def test_uninstalled_daily_is_not_reported_as_disabled(self):
        """脚本未安装（整条记录无真相）→ 不谎报「不启用」，也不提供该入口。"""
        ctrl = _make_controller("ok-nte", "异环")
        ctrl._daily_task_options_cache = {
            "ok-nte": [
                {
                    "name": "追猎目标",
                    "options": [{"name": "追猎目标", "sequences": []}],
                }
            ]
        }
        items = self._items(
            ctrl,
            [{"name": "追猎目标", "task": None, "sequence": None, "enabled": None}],
        )
        self.assertEqual(items[0]["task_label"], "追猎目标")  # 回退声明项
        self.assertFalse(items[0]["can_disable"])
        self.assertFalse(items[0]["disabled"])

    def test_falls_back_to_declared_option_when_no_truth(self):
        """no-op 脚本（绝区零）反读无真相 → 回退声明的首个选项，呈现为已选。"""
        ctrl = _make_controller("OneDragon-Launcher", "绝区零")
        ctrl._daily_task_options_cache = {
            "OneDragon-Launcher": [
                {"name": "每日任务", "options": [{"name": "培养方案", "sequences": []}]}
            ]
        }
        items = self._items(
            ctrl,
            [{"name": "每日任务", "task": None, "sequence": None, "enabled": None}],
        )
        self.assertEqual(items[0]["task_label"], "培养方案")

    def test_placeholder_when_daily_has_no_options(self):
        """该日常声明里没有选项 → 占位「选择副本」。"""
        ctrl = _make_controller("ok-ww", "鸣潮")
        ctrl._daily_task_options_cache = {
            "ok-ww": [{"name": "每日任务", "options": []}]
        }
        items = self._items(
            ctrl,
            [{"name": "每日任务", "task": None, "sequence": None, "enabled": None}],
        )
        self.assertEqual(items[0]["task_label"], "选择副本")

    def test_no_items_without_dailies(self):
        """脚本无日常声明（反读为空）→ 无日常行。"""
        ctrl = _make_controller("ok-ww", "鸣潮")
        ctrl._daily_task_options_cache = {}
        self.assertEqual(self._items(ctrl, []), [])

    def test_daily_task_options_by_daily_name(self):
        """下拉数据按日常取；未知日常返回空列表。"""
        ctrl = _make_controller("ok-nte", "异环")
        ctrl._daily_task_options_cache = {
            "ok-nte": [
                {"name": "异象界域", "options": [{"name": "空幕", "sequences": []}]},
                {
                    "name": "追猎目标",
                    "options": [{"name": "追猎目标", "sequences": []}],
                },
            ]
        }
        self.assertEqual(
            ctrl.daily_task_options("追猎目标"), [{"name": "追猎目标", "sequences": []}]
        )
        self.assertEqual(ctrl.daily_task_options("不存在"), [])


class TestWeeklyItemsReadback(unittest.TestCase):
    """weekly_items 的 task_label 优先反读子脚本 config。"""

    def test_weekly_daily_task_label_prefers_config(self):
        tmp = tempfile.TemporaryDirectory()
        defs_path = _write_defs(
            tmp,
            {
                "March7th-Launcher": [
                    {"name": "历战余响", "tasks": ["无", "铁骸的锈冢"]},
                ]
            },
        )
        with (
            patch(
                "src.config.task_config.get_weekly_task_list_yml_path_under_root",
                return_value=defs_path,
            ),
            patch.object(task_card_mod, "get_weekly_task", return_value="铁骸的锈冢"),
        ):
            ctrl = _make_controller()
            items = ctrl.weekly_items
        tmp.cleanup()
        self.assertEqual(items[0]["task_label"], "铁骸的锈冢")


class TestEmptyCurrentSentinel(unittest.TestCase):
    """config 删空（current_game None）时回退哨兵空项：各 QML 属性安全求值。"""

    def test_properties_degrade_without_raising(self):
        service = MagicMock()
        service.get_weekly_map.return_value = {}
        service.get_weekly_start.return_value = None
        ctrl = TaskCardController(_EmptyGameList(), service, MagicMock())
        self.assertIs(ctrl._current, task_card_mod._EMPTY_GAME)
        self.assertEqual(ctrl.task_title, "")
        self.assertFalse(ctrl.task_adapted)
        self.assertFalse(ctrl.daily_supported)
        self.assertFalse(ctrl.weekly_supported)
        self.assertEqual(ctrl.daily_items, [])
        self.assertEqual(ctrl.daily_task_options("每日任务"), [])
        self.assertEqual(ctrl.weekly_items, [])


if __name__ == "__main__":
    unittest.main()
