"""测试 QmlBridge 任务卡后端（日常副本 / 周常周几）。

复用 gui_helpers.make_bridge：用 mock 隔离 config / 壁纸 I/O；is_adapted / daily_config.get_weekly_map / get_daily_map /
parse_daily_config 按用例 patch（task_card 经 AppService 取数，patch 目标指向
真实模块函数），验证 QML 任务卡所需的数据与写回行为。
"""

import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QDialog

from src.gui.controllers import task_card
from src.service import app_service
from tests.gui_helpers import make_bridge


class TestTaskCard(unittest.TestCase):
    """任务卡数据 / 写回：与旧 task_card.py 对齐。"""

    @patch("src.service.app_service.get_daily_map", return_value={})
    def test_restore_refreshes_task_properties(self, _map):
        bridge = make_bridge()
        name = bridge.games[0]["script_name"]
        bridge.task_card._daily_map_cache = {
            name: {
                "dailies": [
                    {
                        "display_name": "每日任务",
                        "options": {
                            "values": [
                                {
                                    "display_name": "副本A",
                                    "physical_name": "副本A",
                                }
                            ]
                        },
                    }
                ]
            }
        }
        changed = MagicMock()
        bridge.taskStateChanged.connect(changed)
        bridge.app_service.restore_backup = MagicMock(
            return_value={"restored": 1, "skipped_scripts": []}
        )
        with (
            patch.object(bridge.backup, "_pick_zip", return_value="backup.zip"),
            patch.object(task_card, "get_daily_readback") as readback,
        ):
            readback.return_value = [
                {"name": "每日任务", "task": "副本A", "sequence": None, "enabled": None}
            ]
            self.assertEqual(bridge.dailyItems[0]["task_label"], "副本A")
            readback.return_value = [
                {"name": "每日任务", "task": "副本B", "sequence": None, "enabled": None}
            ]
            bridge.restoreConfig()
            changed.assert_called_once_with()
            self.assertEqual(bridge.dailyItems[0]["task_label"], "副本B")

    @patch.object(task_card, "is_adapted", return_value=True)
    @patch(
        "src.service.app_service.get_weekly_map",
        return_value=[{"display_name": "周常"}],
    )
    @patch("src.service.app_service.get_weekly_start_map", return_value={})
    @patch("src.service.app_service.get_daily_map", return_value={})
    @patch.object(task_card, "get_daily_readback", return_value=[])
    def test_daily_items_default_is_empty(self, *_):
        b = make_bridge()
        self.assertEqual(b.dailyItems, [])

    @patch("src.service.app_service.get_daily_map", return_value={})
    def test_set_daily_enabled_writes_through_service(self, *_):
        """日常开关经 Bridge → service 落盘（开关无副本名可反查，显式带日常）。"""
        b = make_bridge()
        name = b.games[0]["script_name"]
        b.app_service.set_script_daily_enabled = MagicMock()
        b.setDailyEnabled("追猎目标", False)
        b.app_service.set_script_daily_enabled.assert_called_once_with(
            name, "追猎目标", False
        )

    @patch.object(task_card, "is_adapted", return_value=False)
    @patch("src.service.app_service.get_daily_map", return_value={})
    def test_task_adapted_reflects_is_adapted(self, *_):
        b = make_bridge()
        self.assertFalse(b.taskAdapted)

    @patch("src.service.app_service.set_config")  # 实时落盘子脚本 config（经 service）
    @patch.object(task_card, "is_adapted", return_value=True)
    @patch("src.service.app_service.get_weekly_map", return_value=[])
    @patch("src.service.app_service.get_daily_map", return_value={})
    @patch.object(task_card, "get_daily_readback")
    def test_select_daily_task_writes_config(self, readback, *_):
        b = make_bridge()
        name = b.games[0]["script_name"]
        # 反读无真相 → chip 回退声明的首个选项
        b.task_card._daily_map_cache = {
            name: {
                "dailies": [
                    {
                        "display_name": "每日任务",
                        "options": {
                            "values": [
                                {
                                    "display_name": "副本A",
                                    "physical_name": "副本A",
                                }
                            ]
                        },
                    }
                ]
            }
        }
        readback.return_value = [
            {"name": "每日任务", "task": None, "sequence": None, "enabled": None}
        ]
        b.selectDaily("每日任务", "副本A", "seq1")
        self.assertEqual(b.dailyItems[0]["task_label"], "副本A")
        # 实时落盘子脚本 config（日常副本编辑期即生效，不再依赖运行全体），经 service 入口；
        # 日常名由该行（GUI 手上就有）带出
        app_service.set_config.assert_called_once_with(
            name,
            task_name="副本A",
            sequence="seq1",
            daily_display_name="每日任务",
        )

    @patch("src.service.app_service.get_weekly_map", return_value=[])
    @patch.object(task_card, "is_adapted", return_value=True)
    @patch.object(task_card, "get_daily_readback")
    def test_nte_menu_yields_two_daily_rows(self, readback, *_):
        """多日常（异环形态）：菜单按日常分组 → 两行，且下拉数据按日常取。"""
        menu = {
            "ok-ww": {
                "dailies": [
                    {
                        "display_name": "异象界域",
                        "options": {
                            "values": [
                                {
                                    "display_name": "空幕",
                                    "physical_name": "空幕",
                                }
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
        readback.return_value = [
            {"name": "异象界域", "task": "空幕", "sequence": None, "enabled": True},
            {
                "name": "追猎目标",
                "task": "追猎目标",
                "sequence": None,
                "enabled": False,
            },
        ]
        with patch("src.service.app_service.get_daily_map", return_value=menu):
            b = make_bridge()
        self.assertEqual(
            [item["name"] for item in b.dailyItems], ["异象界域", "追猎目标"]
        )
        self.assertEqual(
            b.dailyOptions("追猎目标"),
            [{"display_name": "追猎目标", "physical_name": "追猎目标"}],
        )

    @patch.object(task_card, "is_adapted", return_value=True)
    def test_daily_options_shape(self, *_):
        menu = {
            "ok-ww": {
                "dailies": [
                    {
                        "display_name": "每日任务",
                        "options": {
                            "values": [
                                {
                                    "display_name": "副本A",
                                    "physical_name": "副本A",
                                    "options": {
                                        "values": [
                                            {
                                                "display_name": "难1",
                                                "physical_name": "s1",
                                            }
                                        ]
                                    },
                                }
                            ]
                        },
                    }
                ]
            }
        }
        with patch("src.service.app_service.get_daily_map", return_value=menu):
            b = make_bridge()
        opts = b.dailyOptions("每日任务")
        self.assertEqual(opts[0]["display_name"], "副本A")
        self.assertEqual(
            opts[0]["options"]["values"],
            [{"display_name": "难1", "physical_name": "s1"}],
        )

    @patch("src.service.app_service.get_daily_map", return_value={})
    def test_daily_options_empty_when_no_cfg(self, *_):
        b = make_bridge()
        self.assertEqual(b.dailyOptions("每日任务"), [])

    @patch("src.gui.dialogs.SingleScriptConfigDialog")
    def test_config_current_accept_saves_and_reloads(self, mock_dialog_cls):
        b = make_bridge()
        toasts = []
        b.toastRequested.connect(lambda t: toasts.append(t))
        dlg = mock_dialog_cls.return_value
        dlg.exec.return_value = QDialog.Accepted
        dlg.pending_changes = {
            "old_script_name": "ok-ww",
            "new_display_name": "鸣潮",
            "config_patch": {"k": "v"},
            "weekly_timeouts": {"1": [1]},
        }
        with (
            patch.object(b.app_service, "update_script") as mock_update,
            patch.object(b, "_reload_games") as mock_reload,
        ):
            b.configCurrent()
        mock_update.assert_called_once_with("ok-ww", "鸣潮", {"k": "v"}, {"1": [1]})
        mock_reload.assert_called_once()
        self.assertTrue(any("已保存" in s for s in toasts))

    @patch("src.gui.dialogs.SingleScriptConfigDialog")
    def test_config_current_cancel_does_not_save(self, mock_dialog_cls):
        b = make_bridge()
        dlg = mock_dialog_cls.return_value
        dlg.exec.return_value = QDialog.Rejected
        with (
            patch.object(b.app_service, "update_script") as mock_update,
            patch.object(b, "_reload_games") as mock_reload,
        ):
            b.configCurrent()
        mock_update.assert_not_called()
        mock_reload.assert_not_called()


class TestWeeklyStartBridge(unittest.TestCase):
    """「周几起」经 Bridge 暴露：候选列表与按条写回（weekly.yml 的 weekly_start 段）。"""

    def test_weekly_start_options_forwarded(self):
        """候选为「不启用 + 周一~周日」八项，value 即写回用的起始日。"""
        b = make_bridge()
        self.assertEqual(
            [option["value"] for option in b.weeklyStartOptions()],
            [0, 1, 2, 3, 4, 5, 6, 7],
        )

    def test_select_weekly_start_writes_intent_and_game_side(self):
        """写某条周常的起始日：weekly.yml 按条覆盖（其它条目不动）+ 该条游戏侧字面字段。"""
        b = make_bridge()
        script_name = b.games[0]["script_name"]
        written = {}
        with (
            patch(
                "src.service.app_service.get_weekly_start_map",
                return_value={script_name: {"货币战争": 2, "历战余响": 2}},
            ),
            patch(
                "src.service.app_service.set_weekly_start",
                side_effect=lambda script, start_days: written.update(
                    {script: start_days}
                ),
            ),
            patch("src.service.app_service.set_weekly_start_day") as game_side,
        ):
            b.selectWeeklyStart("历战余响", 5)
        self.assertEqual(written, {script_name: {"货币战争": 2, "历战余响": 5}})
        # 游戏侧字面起始日只在编辑期落盘该条（是否真有字面字段由 weekly 模块判定）
        game_side.assert_called_once_with(script_name, "历战余响", 5)

    def test_select_weekly_start_creates_entry_for_first_time(self):
        """该脚本尚无 weekly_start 条目时，只写被选中的那一条。"""
        b = make_bridge()
        script_name = b.games[0]["script_name"]
        written = {}
        with (
            patch("src.service.app_service.get_weekly_start_map", return_value={}),
            patch(
                "src.service.app_service.set_weekly_start",
                side_effect=lambda script, start_days: written.update(
                    {script: start_days}
                ),
            ),
            patch("src.service.app_service.set_weekly_start_day"),
        ):
            b.selectWeeklyStart("货币战争", 4)
        self.assertEqual(written, {script_name: {"货币战争": 4}})


if __name__ == "__main__":
    unittest.main()
