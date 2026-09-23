"""测试 src/gui/controllers/task_card.py：多周常 items 与选副本持久化。"""

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from src.config.daily_config import get_daily_map, get_weekly_map
from src.gui.controllers import task_card as task_card_mod
from src.gui.controllers.task_card import TaskCardController
from src.utils.utils_weekly import DISABLED_START_DAY
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
            # class/config 是声明必填（机制类与文件路径）；菜单物化只取词汇。
            definition = {
                "display_name": task["name"],
                "class": "WutheringWavesWeekly",
                "config": "config.json",
            }
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
    service.get_daily_map.side_effect = get_daily_map
    # 周几起默认未设置（脚本级与条目级都要给值，否则 MagicMock 会被当起始日）
    service.get_weekly_start_for.return_value = None
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
        # 周几起未设置 → 占位文案且 start_set=False（每条周常各一份）
        self.assertEqual(items[0]["start_label"], "选择周几")
        self.assertFalse(items[0]["start_set"])
        self.assertEqual(items[1]["start_label"], "选择周几")
        self.assertFalse(items[1]["start_set"])

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
        self.assertEqual(
            [option["display_name"] for option in options],
            ["无", "铁骸的锈冢", "晨昏的回眸"],
        )
        self.assertTrue(
            all(option["physical_name"] == option["display_name"] for option in options)
        )

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
        ctrl.selectWeekly("历战余响", "铁骸的锈冢")
        # 写脚本自身 config 的 instance_names（M7A 约定键名），经 service 入口
        ctrl._app_service.set_script_weekly_task.assert_called_once_with(
            "March7th-Launcher", "历战余响", "铁骸的锈冢"
        )


class TestSelectDailyWritesSubscriptConfig(unittest.TestCase):
    """日常副本选择：实时落盘子脚本 config（与链生成解耦，不再依赖运行全体）。"""

    def test_select_daily_task_writes_subscript_config(self):
        """选中日常副本：实时经 service 落盘子脚本 config，并带上该行所属日常。"""
        ctrl = _make_controller("ok-ww", "鸣潮")
        ctrl.selectDaily("每日任务", "凝素领域", "5")
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
        ctrl._daily_map_cache = {
            "ok-ww": {
                "dailies": [
                    {
                        "display_name": "每日任务",
                        "options": {
                            "values": [
                                {"display_name": "声明项", "physical_name": "声明项"}
                            ]
                        },
                    }
                ]
            }
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
        ctrl._daily_map_cache = {
            "ok-nte": {
                "dailies": [
                    {
                        "display_name": "异象界域",
                        "options": {
                            "values": [
                                {
                                    "display_name": "空幕",
                                    "physical_name": "空幕",
                                    "options": {
                                        "values": [
                                            {
                                                "display_name": "光暗",
                                                "physical_name": 1,
                                            },
                                            {
                                                "display_name": "轨道之夜",
                                                "physical_name": 6,
                                            },
                                        ]
                                    },
                                }
                            ]
                        },
                    }
                ]
            }
        }
        items = self._items(
            ctrl,
            [{"name": "异象界域", "task": "空幕", "sequence": 6, "enabled": True}],
        )
        self.assertEqual(items[0]["task_label"], "空幕 · 轨道之夜")

    def test_daily_name_is_exposed_for_multi_daily_row(self):
        """多日常：每行带自己的日常展示名（QML 据此区分下拉）。"""
        ctrl = _make_controller("ok-nte", "异环")
        ctrl._daily_map_cache = {
            "ok-nte": {
                "dailies": [
                    {"display_name": "异象界域", "options": {"values": []}},
                    {"display_name": "追猎目标", "options": {"values": []}},
                ]
            }
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
        ctrl._daily_map_cache = {
            "ok-nte": {
                "dailies": [
                    {
                        "display_name": "追猎目标",
                        "options": {
                            "values": [
                                {
                                    "display_name": "追猎目标",
                                    "physical_name": "追猎目标",
                                }
                            ]
                        },
                    }
                ]
            }
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
        ctrl._daily_map_cache = {
            "ok-nte": {
                "dailies": [
                    {
                        "display_name": "追猎目标",
                        "options": {
                            "values": [
                                {
                                    "display_name": "追猎目标",
                                    "physical_name": "追猎目标",
                                }
                            ]
                        },
                    }
                ]
            }
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
        ctrl._daily_map_cache = {
            "OneDragon-Launcher": {
                "dailies": [
                    {
                        "display_name": "每日任务",
                        "options": {
                            "values": [
                                {
                                    "display_name": "培养方案",
                                    "physical_name": "培养方案",
                                }
                            ]
                        },
                    }
                ]
            }
        }
        items = self._items(
            ctrl,
            [{"name": "每日任务", "task": None, "sequence": None, "enabled": None}],
        )
        self.assertEqual(items[0]["task_label"], "培养方案")

    def test_placeholder_when_daily_has_no_options(self):
        """该日常声明里没有选项、也没有开关落点 → 占位「选择副本」。"""
        ctrl = _make_controller("ok-ww", "鸣潮")
        ctrl._daily_map_cache = {
            "ok-ww": {
                "dailies": [{"display_name": "每日任务", "options": {"values": []}}]
            }
        }
        items = self._items(
            ctrl,
            [{"name": "每日任务", "task": None, "sequence": None, "enabled": None}],
        )
        self.assertEqual(items[0]["task_label"], "选择副本")
        self.assertTrue(items[0]["switch_only"])

    def test_switch_only_daily_states_enabled_state(self):
        """无副本选项但有开关落点（原神的领取邮件/千星等）：chip 只表达开关态。"""
        ctrl = _make_controller("BetterGI", "原神")
        ctrl._daily_map_cache = {
            "BetterGI": {
                "dailies": [{"display_name": "领取邮件", "options": {"values": []}}]
            }
        }
        for enabled, label in ((True, "启用"), (False, "不启用")):
            with self.subTest(enabled=enabled):
                items = self._items(
                    ctrl,
                    [
                        {
                            "name": "领取邮件",
                            "task": None,
                            "sequence": None,
                            "enabled": enabled,
                        }
                    ],
                )
                self.assertTrue(items[0]["switch_only"])
                self.assertTrue(items[0]["can_disable"])
                self.assertEqual(items[0]["task_label"], label)

    def test_switch_only_is_false_when_options_declared(self):
        """有副本选项的日常：switch_only 为假（chip 仍弹副本菜单）。"""
        ctrl = _make_controller("ok-ww", "鸣潮")
        ctrl._daily_map_cache = {
            "ok-ww": {
                "dailies": [
                    {
                        "display_name": "每日任务",
                        "options": {
                            "values": [
                                {
                                    "display_name": "凝素领域",
                                    "physical_name": "凝素领域",
                                }
                            ]
                        },
                    }
                ]
            }
        }
        items = self._items(
            ctrl,
            [
                {
                    "name": "每日任务",
                    "task": "凝素领域",
                    "sequence": None,
                    "enabled": True,
                }
            ],
        )
        self.assertFalse(items[0]["switch_only"])
        self.assertEqual(items[0]["task_label"], "凝素领域")

    def test_no_items_without_dailies(self):
        """脚本无日常声明（反读为空）→ 无日常行。"""
        ctrl = _make_controller("ok-ww", "鸣潮")
        ctrl._daily_map_cache = {}
        self.assertEqual(self._items(ctrl, []), [])

    def test_daily_options_by_daily_name(self):
        """下拉数据按日常取；未知日常返回空列表。"""
        ctrl = _make_controller("ok-nte", "异环")
        ctrl._daily_map_cache = {
            "ok-nte": {
                "dailies": [
                    {
                        "display_name": "异象界域",
                        "options": {
                            "values": [
                                {"display_name": "空幕", "physical_name": "空幕"}
                            ]
                        },
                    },
                    {
                        "display_name": "追猎目标",
                        "options": {
                            "values": [
                                {
                                    "display_name": "追猎目标",
                                    "physical_name": "追猎目标",
                                }
                            ]
                        },
                    },
                ]
            }
        }
        self.assertEqual(
            ctrl.daily_options("追猎目标"),
            [{"display_name": "追猎目标", "physical_name": "追猎目标"}],
        )
        self.assertEqual(ctrl.daily_options("不存在"), [])


class TestWeeklyItemsReadback(unittest.TestCase):
    """weekly_items 的 task_label 优先反读子脚本 config。"""

    def test_weekly_daily_label_prefers_config(self):
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


class TestWeeklyStartChip(unittest.TestCase):
    """周常行的「周几起」chip：条目级反读 weekly.yml 与写穿透。"""

    def test_start_label_reflects_weekly_start_map(self):
        """已设起始日的周常显示「周X起」、不启用显示「不启用」，未设显示占位（逐条独立）。

        用真实 weekly_task_list.yml 取崩铁三条周常（当前均无副本选型，故不依赖游戏侧资源）。
        """
        ctrl = _make_controller()
        starts = {"历战余响": 3, "模拟宇宙": DISABLED_START_DAY}
        ctrl._app_service.get_weekly_start_for.side_effect = lambda _script, name: (
            starts.get(name)
        )
        items = ctrl.weekly_items
        self.assertEqual(
            [item["name"] for item in items],
            ["货币战争", "历战余响", "模拟宇宙"],
        )
        self.assertFalse(items[0]["start_set"])
        self.assertEqual(items[0]["start_label"], "选择周几")
        self.assertTrue(items[1]["start_set"])
        self.assertEqual(items[1]["start_label"], "周三起")
        # 不启用也是「已设置」（写进了 weekly.yml），只是文案不同
        self.assertTrue(items[2]["start_set"])
        self.assertEqual(items[2]["start_label"], "不启用")

    def test_start_options_are_disabled_plus_weekdays(self):
        """下拉候选 = 不启用 + 周一~周日（label 供渲染、value 供写回）。"""
        self.assertEqual(
            _make_controller().weekly_start_options,
            [
                {"label": "不启用", "value": DISABLED_START_DAY},
                {"label": "周一起", "value": 1},
                {"label": "周二起", "value": 2},
                {"label": "周三起", "value": 3},
                {"label": "周四起", "value": 4},
                {"label": "周五起", "value": 5},
                {"label": "周六起", "value": 6},
                {"label": "周日起", "value": 7},
            ],
        )

    def test_select_weekly_start_writes_through_service(self):
        """选择周几起经 service 写 weekly.yml（只动该条周常）。"""
        ctrl = _make_controller()
        ctrl.selectWeeklyStart("历战余响", 5)
        ctrl._app_service.set_weekly_start_for.assert_called_once_with(
            "March7th-Launcher", "历战余响", 5
        )

    def test_select_weekly_start_survives_game_side_failure(self):
        """游戏侧写不进去（原生 config 缺失/损坏/只读）→ 提示 + 仍刷新，不抛给 QML。

        不抛是关键：抛回 QML 会跳过 onClicked 里后续的关下拉，且界面静默
        （意图已落 weekly.yml，下次任何刷新即按新值显示）。
        """
        for exc in (AssertionError("config 文件不存在"), OSError("拒绝访问")):
            with self.subTest(exc=type(exc).__name__):
                ctrl = _make_controller()
                ctrl._app_service.set_weekly_start_for.side_effect = exc
                with patch.object(ctrl, "refresh") as mock_refresh:
                    ctrl.selectWeeklyStart("历战余响", 3)  # 不应抛出
                mock_refresh.assert_called_once()
                ctrl._toast.assert_called_once()
                self.assertIn("历战余响", ctrl._toast.call_args[0][0])

    def test_invalid_start_day_raises(self):
        """weekly.yml 被手工改坏（越界值）→ assert 暴露，不静默当未设置。"""
        with self.assertRaises(AssertionError):
            task_card_mod.TaskCardController._start_day_label(9)


class TestEmptyCurrentSentinel(unittest.TestCase):
    """config 删空（current_game None）时回退哨兵空项：各 QML 属性安全求值。"""

    def test_properties_degrade_without_raising(self):
        service = MagicMock()
        service.get_weekly_map.return_value = {}
        service.get_weekly_start_for.return_value = None
        ctrl = TaskCardController(_EmptyGameList(), service, MagicMock())
        self.assertIs(ctrl._current, task_card_mod._EMPTY_GAME)
        self.assertEqual(ctrl.task_title, "")
        self.assertFalse(ctrl.task_adapted)
        self.assertFalse(ctrl.weekly_supported)
        self.assertEqual(ctrl.daily_items, [])
        self.assertEqual(ctrl.daily_options("每日任务"), [])
        self.assertEqual(ctrl.weekly_items, [])


if __name__ == "__main__":
    unittest.main()
