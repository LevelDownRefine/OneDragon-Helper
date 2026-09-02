"""测试 src/gui/controllers/task_card.py：多周常 items 与选副本持久化。"""

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from src.config.dungeon_config import get_dungeon_map, get_weekly_map
from src.gui.controllers import task_card as task_card_mod
from src.gui.controllers.task_card import TaskCardController
from src.utils_yaml import dump_yaml_file


class _FakeGameList:
    def __init__(self, games):
        self.games = games
        self.current_game = games[0]


def _write_defs(tmp, data):
    """写临时 weekly_list.yml（周常声明配置）。"""
    path = os.path.join(tmp.name, "weekly_list.yml")
    dump_yaml_file(path, data)
    return path


def _make_controller(script_name="March7th-Assistant", display_name="崩铁"):
    games = [{"script_name": script_name, "display_name": display_name}]
    game_list = _FakeGameList(games)
    service = MagicMock()
    # 副本/周常声明经真实 dungeon_config 模块函数读取（weekly_list.yml 路径已由用例 patch）。
    service.get_weekly_map.side_effect = get_weekly_map
    service.get_dungeon_map.side_effect = get_dungeon_map
    service.get_weekly_start.return_value = None
    toast = MagicMock()
    return TaskCardController(game_list, service, toast)


class TestWeeklyItems(unittest.TestCase):
    def test_weekly_items_for_star_rail(self):
        """崩铁两种周常（来自 weekly_list.yml）：货币战争(无副本) + 历战余响(有副本)。"""
        tmp = tempfile.TemporaryDirectory()
        defs_path = _write_defs(
            tmp,
            {
                "March7th-Assistant": [
                    {"name": "货币战争"},
                    {
                        "name": "历战余响",
                        "dungeons": ["无", "铁骸的锈冢", "晨昏的回眸"],
                    },
                ]
            },
        )
        with (
            patch(
                "src.config.dungeon_config.get_weekly_list_yml_path_under_root",
                return_value=defs_path,
            ),
            patch.object(task_card_mod, "get_weekly_dungeon", return_value=None),
        ):
            ctrl = _make_controller()
            items = ctrl.weekly_items
        tmp.cleanup()
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["name"], "货币战争")
        self.assertFalse(items[0]["has_dungeon"])
        self.assertEqual(items[0]["dungeon_label"], "")
        self.assertEqual(items[1]["name"], "历战余响")
        self.assertTrue(items[1]["has_dungeon"])
        # 无配置/未选：反读 None → 占位提示（周常侧不设回退）
        self.assertEqual(items[1]["dungeon_label"], "选择副本")

    def test_weekly_dungeon_options_reads_from_config(self):
        """副本清单来自 weekly_list.yml 的 dungeons 字段，不再依赖游戏脚本配置。"""
        tmp = tempfile.TemporaryDirectory()
        defs_path = _write_defs(
            tmp,
            {
                "March7th-Assistant": [
                    {
                        "name": "历战余响",
                        "dungeons": ["无", "铁骸的锈冢", "晨昏的回眸"],
                    },
                ]
            },
        )
        with patch(
            "src.config.dungeon_config.get_weekly_list_yml_path_under_root",
            return_value=defs_path,
        ):
            ctrl = _make_controller()
            options = ctrl.weekly_dungeon_options("历战余响")
        tmp.cleanup()
        self.assertEqual(options, ["无", "铁骸的锈冢", "晨昏的回眸"])

    def test_weekly_dungeon_options_unknown_weekly_returns_empty(self):
        """未声明的周常名 → 空列表。"""
        tmp = tempfile.TemporaryDirectory()
        defs_path = _write_defs(
            tmp,
            {
                "March7th-Assistant": [
                    {"name": "历战余响", "dungeons": ["无", "铁骸的锈冢"]},
                ]
            },
        )
        with patch(
            "src.config.dungeon_config.get_weekly_list_yml_path_under_root",
            return_value=defs_path,
        ):
            ctrl = _make_controller()
            self.assertEqual(ctrl.weekly_dungeon_options("不存在"), [])
        tmp.cleanup()

    def test_weekly_dungeon_options_without_dungeons_key(self):
        """无 dungeons 字段的周常 → 空列表（不报 KeyError）。"""
        tmp = tempfile.TemporaryDirectory()
        defs_path = _write_defs(
            tmp,
            {
                "March7th-Assistant": [
                    {"name": "货币战争"},
                ]
            },
        )
        with patch(
            "src.config.dungeon_config.get_weekly_list_yml_path_under_root",
            return_value=defs_path,
        ):
            ctrl = _make_controller()
            self.assertEqual(ctrl.weekly_dungeon_options("货币战争"), [])
        tmp.cleanup()

    def test_weekly_supported_follows_config(self):
        """weekly_supported 唯一真相源为 weekly_list.yml：声明即支持，未声明即不支持。"""
        # 崩铁声明、鸣潮未声明
        tmp = tempfile.TemporaryDirectory()
        defs_path = _write_defs(
            tmp,
            {
                "March7th-Assistant": [
                    {"name": "历战余响", "dungeons": ["无"]},
                ]
            },
        )
        with patch(
            "src.config.dungeon_config.get_weekly_list_yml_path_under_root",
            return_value=defs_path,
        ):
            ctrl_star = _make_controller("March7th-Assistant", "崩铁")
            ctrl_ww = _make_controller("ok-ww", "鸣潮")
            self.assertTrue(ctrl_star.weekly_supported)
            self.assertFalse(ctrl_ww.weekly_supported)
        tmp.cleanup()

    def test_weekly_items_empty_for_non_weekly_script(self):
        tmp = tempfile.TemporaryDirectory()
        # ok-ww 不在 weekly_list.yml 声明 → 空列表
        defs_path = _write_defs(tmp, {})
        with patch(
            "src.config.dungeon_config.get_weekly_list_yml_path_under_root",
            return_value=defs_path,
        ):
            ctrl = _make_controller("ok-ww", "鸣潮")
            self.assertEqual(ctrl.weekly_items, [])
        tmp.cleanup()


class TestSelectWeeklyDungeon(unittest.TestCase):
    def test_select_weekly_dungeon_writes_config(self):
        """选副本：调 set_weekly_dungeon 写脚本自身 config（周常侧无 no-op 脚本）。"""
        ctrl = _make_controller()
        with patch.object(task_card_mod, "set_weekly_dungeon") as mock_set:
            ctrl.selectWeeklyDungeon("历战余响", "铁骸的锈冢")
        # 写脚本自身 config 的 instance_names（M7A 约定键名）
        mock_set.assert_called_once_with("March7th-Assistant", "历战余响", "铁骸的锈冢")


class TestSelectDungeonWritesSubscriptConfig(unittest.TestCase):
    """日常副本选择：实时落盘子脚本 config（与链生成解耦，不再依赖运行全体）。"""

    def test_select_dungeon_writes_subscript_config(self):
        """选中日常副本：实时经 set_config 落盘子脚本 config。"""
        ctrl = _make_controller("ok-ww", "鸣潮")
        with patch.object(task_card_mod, "set_config") as mock_set:
            ctrl.selectDungeon("凝素领域", "5")
        # 实时落盘：dungeon_name + sequence（鸣潮要求 sequence 非空）
        mock_set.assert_called_once_with("ok-ww", dungeon_name="凝素领域", sequence="5")


class TestDailyDungeonTextReadback(unittest.TestCase):
    """daily_dungeon_text 优先反读子脚本 config，无真相回退声明的唯一选项。"""

    def test_prefers_subscript_config_over_declared(self):
        """config 有真相时以 config 为准，不走声明项回退。"""
        ctrl = _make_controller("ok-ww", "鸣潮")
        ctrl._dungeon_map_cache = {}
        ctrl._dungeon_options_cache = {"ok-ww": [{"name": "声明项"}]}
        with (
            patch.object(task_card_mod, "get_dungeon", return_value="凝素领域"),
            patch.object(task_card_mod, "get_sequence", return_value="5"),
        ):
            self.assertEqual(ctrl.daily_dungeon_text, "凝素领域")

    def test_nte_daily_shows_dungeon_and_sequence(self):
        """异环：空幕 · 轨道之夜（序号不自包含副本名，必须两者同显）。"""
        dungeon_cfg = {
            "dungeons": [
                {
                    "name": "空幕",
                    "sequences": [
                        {"display": "光暗", "value": 1},
                        {"display": "轨道之夜", "value": 6},
                    ],
                }
            ]
        }
        ctrl = _make_controller("ok-nte", "异环")
        ctrl._dungeon_map_cache = {"ok-nte": dungeon_cfg}
        with (
            patch.object(task_card_mod, "get_dungeon", return_value="空幕"),
            patch.object(task_card_mod, "get_sequence", return_value=6),
        ):
            self.assertEqual(ctrl.daily_dungeon_text, "空幕 · 轨道之夜")

    def test_falls_back_to_declared_option_when_config_none(self):
        """no-op 脚本（绝区零）反读无真相 → 回退声明的唯一选项，呈现为已选。"""
        ctrl = _make_controller("OneDragon-Launcher", "绝区零")
        ctrl._dungeon_map_cache = {}
        ctrl._dungeon_options_cache = {
            "OneDragon-Launcher": [{"name": "培养方案", "sequences": []}]
        }
        with (
            patch.object(task_card_mod, "get_dungeon", return_value=None),
            patch.object(task_card_mod, "get_sequence", return_value=None),
        ):
            self.assertEqual(ctrl.daily_dungeon_text, "培养方案")

    def test_placeholder_when_no_config_and_no_declaration(self):
        """config 无真相且 dungeon_list.yml 未声明 → 占位「选择副本」。"""
        ctrl = _make_controller("ok-ww", "鸣潮")
        ctrl._dungeon_map_cache = {}
        ctrl._dungeon_options_cache = {}
        with (
            patch.object(task_card_mod, "get_dungeon", return_value=None),
            patch.object(task_card_mod, "get_sequence", return_value=None),
        ):
            self.assertEqual(ctrl.daily_dungeon_text, "选择副本")


class TestWeeklyItemsReadback(unittest.TestCase):
    """weekly_items 的 dungeon_label 优先反读子脚本 config。"""

    def test_weekly_dungeon_label_prefers_config(self):
        tmp = tempfile.TemporaryDirectory()
        defs_path = _write_defs(
            tmp,
            {
                "March7th-Assistant": [
                    {"name": "历战余响", "dungeons": ["无", "铁骸的锈冢"]},
                ]
            },
        )
        with (
            patch(
                "src.config.dungeon_config.get_weekly_list_yml_path_under_root",
                return_value=defs_path,
            ),
            patch.object(
                task_card_mod, "get_weekly_dungeon", return_value="铁骸的锈冢"
            ),
        ):
            ctrl = _make_controller()
            items = ctrl.weekly_items
        tmp.cleanup()
        self.assertEqual(items[0]["dungeon_label"], "铁骸的锈冢")


if __name__ == "__main__":
    unittest.main()
