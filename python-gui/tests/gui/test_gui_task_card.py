"""测试 src/gui/controllers/task_card.py：script_view 聚合视图 → 任务卡行。

数据源已收敛为 AppService.script_view（与 Rust 前端同一视图）：本文件用视图
替身验证控制器的展示衍生（chip 文案 / 行字段 / 下拉 / 视图缓存失效）与写穿透；
声明的物化与反读真相的聚合归后端 test_task_service 覆盖。
"""

import unittest
from unittest.mock import MagicMock, call, patch

from gui.controllers import task_card as task_card_mod
from gui.controllers.task_card import TaskCardController
from src.utils.utils_weekly import DISABLED_START_DAY


class _FakeGameList:
    def __init__(self, games):
        self.games = games
        self.current_game = games[0]


class _EmptyGameList:
    """config 删空后的 game_list 替身：current_game 为 None。"""

    current_game = None


def _daily(name, task=None, sequence=None, enabled=None, values=None):
    """一条视图日常行：反读真相（task/sequence/enabled）并入声明菜单。"""
    return {
        "name": name,
        "task": task,
        "sequence": sequence,
        "enabled": enabled,
        "options": {"values": values or []},
    }


def _weekly(name, options=None, task=None, start_day=None):
    """一条视图周常行：options 为 None 表示无副本选型。"""
    return {"name": name, "options": options, "task": task, "start_day": start_day}


def _view(dailies=(), weeklies=()):
    return {
        "script": {"script_name": "demo", "display_name": "demo"},
        "dailies": list(dailies),
        "weeklies": list(weeklies),
    }


def _make_controller(script_name="March7th-Launcher", display_name="崩铁", view=None):
    games = [{"script_name": script_name, "display_name": display_name}]
    service = MagicMock()
    service.script_view.return_value = view if view is not None else _view()
    service.is_adapted.return_value = False
    return TaskCardController(_FakeGameList(games), service, MagicMock())


class TestViewCache(unittest.TestCase):
    """聚合视图按脚本缓存：同一脚本一次取全，失效点（refresh/重载）后重取。"""

    def test_switch_fetches_per_script_and_reuses_within(self):
        games = [
            {"script_name": name, "display_name": name} for name in ("first", "second")
        ]
        service = MagicMock()
        views = {
            name: _view(dailies=[_daily("日常", values=[{"display_name": name}])])
            for name in ("first", "second")
        }
        service.script_view.side_effect = lambda name: views[name]
        ctrl = TaskCardController(_FakeGameList(games), service, MagicMock())
        ctrl.build_daily_cache()
        self.assertEqual(ctrl.daily_options("日常"), [{"display_name": "first"}])
        self.assertEqual(
            ctrl.daily_options("日常"), [{"display_name": "first"}]
        )  # 同脚本复用
        service.script_view.assert_called_once_with("first")
        games_list = ctrl._game_list
        games_list.current_game = games[1]
        self.assertEqual(ctrl.daily_options("日常"), [{"display_name": "second"}])
        games_list.current_game = games[0]
        self.assertEqual(ctrl.daily_options("日常"), [{"display_name": "first"}])
        # 只缓存当前脚本的视图：切走再切回会重取（QML 一次求值一个脚本，无需驻留）。
        self.assertEqual(
            service.script_view.call_args_list,
            [call("first"), call("second"), call("first")],
        )

        # 重载后两个脚本都须重新取视图，不能沿用旧资源。
        for name in views:
            views[name] = _view(
                dailies=[_daily("日常", values=[{"display_name": f"new-{name}"}])]
            )
        ctrl.build_daily_cache()
        self.assertEqual(ctrl.daily_options("日常"), [{"display_name": "new-first"}])
        games_list.current_game = games[1]
        self.assertEqual(ctrl.daily_options("日常"), [{"display_name": "new-second"}])
        self.assertEqual(
            service.script_view.call_args_list,
            [
                call("first"),
                call("second"),
                call("first"),
                call("first"),
                call("second"),
            ],
        )

    def test_refresh_invalidates_for_next_evaluation(self):
        """写操作后的 refresh 失效缓存：QML 重读拿到新视图。"""
        service = MagicMock()
        service.script_view.return_value = _view(
            dailies=[_daily("每日任务", task="旧副本")]
        )
        ctrl = _make_controller_view(service)
        self.assertEqual(ctrl.daily_items[0]["task_label"], "旧副本")
        service.script_view.return_value = _view(
            dailies=[_daily("每日任务", task="新副本")]
        )
        ctrl.refresh()
        self.assertEqual(ctrl.daily_items[0]["task_label"], "新副本")
        self.assertEqual(service.script_view.call_count, 2)

    def test_empty_script_never_fetches(self):
        """config 删空（哨兵空项）：不求视图，属性安全收缩。"""
        service = MagicMock()
        ctrl = TaskCardController(_EmptyGameList(), service, MagicMock())
        self.assertEqual(ctrl.daily_items, [])
        self.assertEqual(ctrl.daily_options("日常"), [])
        self.assertEqual(ctrl.weekly_items, [])
        self.assertFalse(ctrl.weekly_supported)
        service.script_view.assert_not_called()

    def test_removed_script_shrinks_card(self):
        """脚本已被移除（script_view 抛 InvalidTaskSelection）→ 空视图收缩。"""
        from src.service.task_service import InvalidTaskSelection

        service = MagicMock()
        service.script_view.side_effect = InvalidTaskSelection("脚本不存在: gone")
        ctrl = _make_controller_view(service, script_name="gone")
        self.assertEqual(ctrl.daily_items, [])
        self.assertEqual(ctrl.weekly_items, [])
        service.script_view.assert_called_once_with("gone")


def _make_controller_view(service, script_name="demo", display_name="示例"):
    games = [{"script_name": script_name, "display_name": display_name}]
    return TaskCardController(_FakeGameList(games), service, MagicMock())


class TestDailyItems(unittest.TestCase):
    """daily_items：视图行（真相 + 菜单已并入）→ 每行 chip 文案与「不启用」入口。"""

    def test_prefers_readback_over_declared(self):
        """反读有真相时以反读为准，不走声明项回退。"""
        ctrl = _make_controller(
            "ok-ww",
            "鸣潮",
            _view(
                dailies=[
                    _daily(
                        "每日任务",
                        task="凝素领域",
                        sequence="5",
                        values=[{"display_name": "声明项", "physical_name": "声明项"}],
                    )
                ]
            ),
        )
        self.assertEqual(ctrl.daily_items[0]["task_label"], "凝素领域")

    def test_nte_daily_shows_daily_task_and_sequence(self):
        """异环：空幕 · 轨道之夜（选项不自包含副本名，必须两者同显）。"""
        ctrl = _make_controller(
            "ok-nte",
            "异环",
            _view(
                dailies=[
                    _daily(
                        "异象界域",
                        task="空幕",
                        sequence=6,
                        enabled=True,
                        values=[
                            {
                                "display_name": "空幕",
                                "physical_name": "空幕",
                                "options": {
                                    "values": [
                                        {"display_name": "光暗", "physical_name": 1},
                                        {
                                            "display_name": "轨道之夜",
                                            "physical_name": 6,
                                        },
                                    ]
                                },
                            }
                        ],
                    )
                ]
            ),
        )
        self.assertEqual(ctrl.daily_items[0]["task_label"], "空幕 · 轨道之夜")

    def test_daily_name_is_exposed_for_multi_daily_row(self):
        """多日常：每行带自己的日常展示名（QML 据此区分下拉）。"""
        ctrl = _make_controller(
            "ok-nte",
            "异环",
            _view(
                dailies=[
                    _daily("异象界域", enabled=True),
                    _daily("追猎目标", enabled=True),
                ]
            ),
        )
        self.assertEqual(
            [item["name"] for item in ctrl.daily_items], ["异象界域", "追猎目标"]
        )

    def test_disabled_daily_shows_disabled_and_can_disable(self):
        """被停用的日常：chip 显示「不启用」，该行提供「不启用」入口。"""
        ctrl = _make_controller(
            "ok-nte",
            "异环",
            _view(
                dailies=[
                    _daily(
                        "追猎目标",
                        task="音霸魔王",
                        enabled=False,
                        values=[
                            {
                                "display_name": "追猎目标",
                                "physical_name": "追猎目标",
                            }
                        ],
                    )
                ]
            ),
        )
        item = ctrl.daily_items[0]
        self.assertEqual(item["task_label"], "不启用")
        self.assertTrue(item["can_disable"])
        self.assertTrue(item["disabled"])

    def test_uninstalled_daily_is_not_reported_as_disabled(self):
        """脚本未安装（整条记录无真相）→ 不谎报「不启用」，也不提供该入口。"""
        ctrl = _make_controller(
            "ok-nte",
            "异环",
            _view(
                dailies=[
                    _daily(
                        "追猎目标",
                        values=[
                            {
                                "display_name": "追猎目标",
                                "physical_name": "追猎目标",
                            }
                        ],
                    )
                ]
            ),
        )
        item = ctrl.daily_items[0]
        self.assertEqual(item["task_label"], "追猎目标")  # 回退声明项
        self.assertFalse(item["can_disable"])
        self.assertFalse(item["disabled"])

    def test_falls_back_to_declared_option_when_no_truth(self):
        """no-op 脚本（绝区零）反读无真相 → 回退声明的首个选项，呈现为已选。"""
        ctrl = _make_controller(
            "OneDragon-Launcher",
            "绝区零",
            _view(
                dailies=[
                    _daily(
                        "每日任务",
                        values=[
                            {"display_name": "培养方案", "physical_name": "培养方案"}
                        ],
                    )
                ]
            ),
        )
        self.assertEqual(ctrl.daily_items[0]["task_label"], "培养方案")

    def test_placeholder_when_daily_has_no_options(self):
        """该日常声明里没有选项 → 占位「选择副本」。"""
        ctrl = _make_controller("ok-ww", "鸣潮", _view(dailies=[_daily("每日任务")]))
        self.assertEqual(ctrl.daily_items[0]["task_label"], "选择副本")

    def test_no_items_without_dailies(self):
        """脚本无日常声明 → 无日常行。"""
        ctrl = _make_controller("ok-ww", "鸣潮", _view())
        self.assertEqual(ctrl.daily_items, [])

    def test_daily_options_by_daily_name(self):
        """下拉数据按日常取；未知日常返回空列表。"""
        ctrl = _make_controller(
            "ok-nte",
            "异环",
            _view(
                dailies=[
                    _daily(
                        "异象界域",
                        values=[{"display_name": "空幕", "physical_name": "空幕"}],
                    ),
                    _daily(
                        "追猎目标",
                        values=[
                            {
                                "display_name": "追猎目标",
                                "physical_name": "追猎目标",
                            }
                        ],
                    ),
                ]
            ),
        )
        self.assertEqual(
            ctrl.daily_options("追猎目标"),
            [{"display_name": "追猎目标", "physical_name": "追猎目标"}],
        )
        self.assertEqual(ctrl.daily_options("不存在"), [])


class TestWeeklyItems(unittest.TestCase):
    """weekly_items / weekly_task_options：周常行与下拉来自视图 weeklies。"""

    def test_two_weeklies_with_and_without_options(self):
        """货币战争(无副本) + 历战余响(有副本)：has_task 与占位文案。"""
        ctrl = _make_controller(
            view=_view(
                weeklies=[
                    _weekly("货币战争"),
                    _weekly(
                        "历战余响",
                        options={
                            "values": [
                                {"display_name": "无", "physical_name": "无"},
                                {
                                    "display_name": "铁骸的锈冢",
                                    "physical_name": "铁骸的锈冢",
                                },
                            ]
                        },
                    ),
                ]
            )
        )
        items = ctrl.weekly_items
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["name"], "货币战争")
        self.assertFalse(items[0]["has_task"])
        self.assertEqual(items[0]["task_label"], "")
        self.assertEqual(items[1]["name"], "历战余响")
        self.assertTrue(items[1]["has_task"])
        # 无配置/未选：task 为 None → 占位提示（周常侧不设回退）
        self.assertEqual(items[1]["task_label"], "选择副本")
        # 周几起未设置 → 占位文案且 start_set=False（每条周常各一份）
        self.assertEqual(items[0]["start_label"], "选择周几")
        self.assertFalse(items[0]["start_set"])
        self.assertEqual(items[1]["start_label"], "选择周几")
        self.assertFalse(items[1]["start_set"])

    def test_task_label_prefers_config(self):
        """已选副本（task 反读真相）直接展示。"""
        ctrl = _make_controller(
            view=_view(
                weeklies=[
                    _weekly(
                        "历战余响",
                        options={"values": [{"display_name": "无"}]},
                        task="铁骸的锈冢",
                    )
                ]
            )
        )
        self.assertEqual(ctrl.weekly_items[0]["task_label"], "铁骸的锈冢")

    def test_weekly_task_options_from_view(self):
        """副本清单来自视图；未声明副本（options=None）或未知周常 → 空列表。"""
        ctrl = _make_controller(
            view=_view(
                weeklies=[
                    _weekly(
                        "历战余响",
                        options={
                            "values": [
                                {"display_name": "无", "physical_name": "无"},
                                {
                                    "display_name": "铁骸的锈冢",
                                    "physical_name": "铁骸的锈冢",
                                },
                            ]
                        },
                    ),
                    _weekly("货币战争"),
                ]
            )
        )
        self.assertEqual(
            [option["display_name"] for option in ctrl.weekly_task_options("历战余响")],
            ["无", "铁骸的锈冢"],
        )
        self.assertEqual(ctrl.weekly_task_options("货币战争"), [])
        self.assertEqual(ctrl.weekly_task_options("不存在"), [])

    def test_weekly_supported_follows_view(self):
        """weekly_supported 由视图 weeklies 推导：声明即支持。"""
        self.assertTrue(
            _make_controller(
                view=_view(weeklies=[_weekly("历战余响")])
            ).weekly_supported
        )
        self.assertFalse(_make_controller(view=_view()).weekly_supported)
        self.assertEqual(_make_controller(view=_view()).weekly_items, [])


class TestSelectWrites(unittest.TestCase):
    """写穿透：日常/周常选择与开关、周几起均经 service，随后失效视图。"""

    def test_select_daily_task_writes_subscript_config(self):
        """选中日常副本：实时经 service 落盘子脚本 config，并带上该行所属日常。"""
        ctrl = _make_controller("ok-ww", "鸣潮")
        ctrl.selectDaily("每日任务", "凝素领域", "5")
        ctrl._app_service.set_script_daily_task.assert_called_once_with(
            "ok-ww",
            task_name="凝素领域",
            sequence="5",
            daily_display_name="每日任务",
        )

    def test_set_daily_enabled_writes_through_service(self):
        ctrl = _make_controller("ok-nte", "异环")
        ctrl.setDailyEnabled("追猎目标", False)
        ctrl._app_service.set_script_daily_enabled.assert_called_once_with(
            "ok-nte", "追猎目标", False
        )

    def test_select_weekly_task_writes_config(self):
        """选副本：经 service 写脚本自身 config（周常侧无 no-op 脚本）。"""
        ctrl = _make_controller()
        ctrl.selectWeekly("历战余响", "铁骸的锈冢")
        ctrl._app_service.set_script_weekly_task.assert_called_once_with(
            "March7th-Launcher", "历战余响", "铁骸的锈冢"
        )

    def test_write_then_refresh_refetches(self):
        """写操作后 refresh 清缓存：QML 重读时重新取视图（不沿用旧值）。"""
        ctrl = _make_controller(view=_view(dailies=[_daily("每日任务", task="旧")]))
        self.assertEqual(ctrl.daily_items[0]["task_label"], "旧")  # 首次求值
        ctrl.selectDaily("每日任务", "新副本", None)
        self.assertIsNone(ctrl._view)  # refresh 已失效
        self.assertEqual(ctrl.daily_items[0]["task_label"], "旧")  # mock 未变，仅证重取
        self.assertEqual(ctrl._app_service.script_view.call_count, 2)


class TestWeeklyStartChip(unittest.TestCase):
    """周常行的「周几起」chip：视图 start_day 与写穿透。"""

    def test_start_label_reflects_view_start_days(self):
        """已设起始日的周常显示「周X起」、不启用显示「不启用」，未设显示占位（逐条独立）。"""
        ctrl = _make_controller(
            view=_view(
                weeklies=[
                    _weekly("货币战争"),
                    _weekly("历战余响", start_day=3),
                    _weekly("模拟宇宙", start_day=DISABLED_START_DAY),
                ]
            )
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
            TaskCardController._start_day_label(9)


class TestEmptyCurrentSentinel(unittest.TestCase):
    """config 删空（current_game None）时回退哨兵空项：各 QML 属性安全求值。"""

    def test_properties_degrade_without_raising(self):
        service = MagicMock()
        service.is_adapted.return_value = False
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
