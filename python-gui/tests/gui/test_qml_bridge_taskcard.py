"""QmlBridge 通过 CLI 响应呈现任务卡并发送写请求。"""

import unittest
from dataclasses import asdict
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QDialog

from gui.cli_client import CliFailure
from src.service.script_service import ScriptEdit
from tests.gui.helpers import drain_events, make_bridge, script_view


def daily(name, task=None, sequence=None, enabled=None, values=None):
    return {
        "name": name,
        "task": task,
        "sequence": sequence,
        "enabled": enabled,
        "options": {"values": [] if values is None else values},
    }


def set_view(bridge, *, dailies=None, weeklies=None, adapted=False):
    name = bridge.game_list.current_game["script_name"]
    bridge.test_client.responses["script.view"] = script_view(
        name, adapted=adapted, dailies=dailies, weeklies=weeklies
    )
    bridge.task_card.refresh()
    drain_events()


def writes(bridge, method):
    return [params for name, params in bridge.test_client.requests if name == method]


class TestTaskCard(unittest.TestCase):
    def test_completed_restore_refreshes_task_properties(self):
        bridge = make_bridge()
        values = [{"display_name": "副本A", "physical_name": "副本A"}]
        set_view(bridge, dailies=[daily("每日任务", "副本A", values=values)])
        self.assertEqual(bridge.dailyItems[0]["task_label"], "副本A")
        name = bridge.games[0]["script_name"]
        bridge.test_client.responses["script.view"] = script_view(
            name, dailies=[daily("每日任务", "副本B", values=values)]
        )
        changed = Mock()
        bridge.taskStateChanged.connect(changed)
        before = len(writes(bridge, "script.view"))
        bridge.backup.restoreCompleted.emit()
        drain_events()
        self.assertGreater(changed.call_count, 0)
        self.assertEqual(len(writes(bridge, "script.view")), before + 1)
        self.assertEqual(bridge.dailyItems[0]["task_label"], "副本B")

    def test_daily_items_default_is_empty(self):
        self.assertEqual(make_bridge().dailyItems, [])

    def test_daily_enable_sends_explicit_row_and_boolean(self):
        bridge = make_bridge()
        bridge.setDailyEnabled("追猎目标", False)
        drain_events()
        self.assertEqual(
            writes(bridge, "daily.enable"),
            [
                {
                    "script_name": "ok-ww",
                    "daily_name": "追猎目标",
                    "enabled": False,
                }
            ],
        )

    def test_adapted_flag_follows_cli_view(self):
        bridge = make_bridge()
        self.assertFalse(bridge.taskAdapted)
        set_view(bridge, adapted=True)
        self.assertTrue(bridge.taskAdapted)

    def test_daily_selection_sends_sequence_and_refreshes_view(self):
        bridge = make_bridge()
        set_view(
            bridge,
            dailies=[
                daily(
                    "每日任务",
                    values=[
                        {"display_name": "副本A", "physical_name": "副本A"},
                    ],
                )
            ],
        )
        bridge.selectDaily("每日任务", "副本A", "seq1")
        drain_events()
        self.assertEqual(bridge.dailyItems[0]["task_label"], "副本A")
        self.assertEqual(
            writes(bridge, "daily.select"),
            [
                {
                    "script_name": "ok-ww",
                    "daily_name": "每日任务",
                    "task_name": "副本A",
                    "sequence": "seq1",
                }
            ],
        )

    def test_nte_shape_keeps_two_independent_daily_rows(self):
        bridge = make_bridge()
        set_view(
            bridge,
            dailies=[
                daily(
                    "异象界域",
                    "空幕",
                    enabled=True,
                    values=[{"display_name": "空幕", "physical_name": "空幕"}],
                ),
                daily(
                    "追猎目标",
                    "追猎目标",
                    enabled=False,
                    values=[{"display_name": "追猎目标", "physical_name": "追猎目标"}],
                ),
            ],
        )
        self.assertEqual(
            [row["name"] for row in bridge.dailyItems], ["异象界域", "追猎目标"]
        )
        self.assertEqual([row["disabled"] for row in bridge.dailyItems], [False, True])
        self.assertEqual(
            bridge.dailyOptions("追猎目标"),
            [{"display_name": "追猎目标", "physical_name": "追猎目标"}],
        )

    def test_daily_options_preserve_recursive_physical_values(self):
        bridge = make_bridge()
        values = [
            {
                "display_name": "副本A",
                "physical_name": "副本A",
                "options": {
                    "values": [{"display_name": "难1", "physical_name": "s1"}],
                },
            }
        ]
        set_view(bridge, dailies=[daily("每日任务", values=values)])
        self.assertEqual(bridge.dailyOptions("每日任务"), values)

    def test_unknown_daily_has_no_options(self):
        self.assertEqual(make_bridge().dailyOptions("每日任务"), [])

    def edit_bridge(self):
        bridge = make_bridge()
        bridge.test_client.responses["script.edit_view"] = {
            "script_name": "ok-ww",
            "script": {
                "display_name": "鸣潮",
                "script_path": "scripts/ok-ww/ok-ww.exe",
            },
            "weekly_timeouts": [60] * 7,
            "switches": [],
            "task_options": [],
        }
        return bridge

    def test_config_save_waits_for_ack_before_reload_and_accept(self):
        bridge = self.edit_bridge()
        edit = ScriptEdit(
            "ok-ww", "鸣潮", {"block": True}, [60] * 7, {"领取邮件": True}
        )
        dialog = Mock()
        reload = Mock()
        bridge.game_list._on_reload = reload

        def response(params):
            dialog.accept.assert_not_called()
            reload.assert_not_called()
            self.assertEqual(params, asdict(edit))
            return {"script_name": "hhw"}

        bridge.test_client.responses["script.edit_save"] = response

        def build(*args, **kwargs):
            assert "submit" in kwargs
            dialog.exec.side_effect = lambda: kwargs["submit"](edit)
            return dialog

        with patch("gui.dialogs.SingleScriptConfigDialog", side_effect=build):
            bridge.configCurrent()
            drain_events()
        dialog.accept.assert_called_once()
        reload.assert_called_once()
        self.assertEqual(writes(bridge, "script.edit_save"), [asdict(edit)])

    def test_config_cancel_does_not_save_or_reload(self):
        bridge = self.edit_bridge()
        bridge.game_list._on_reload = Mock()
        with patch("gui.dialogs.SingleScriptConfigDialog") as dialog:
            dialog.return_value.exec.return_value = QDialog.Rejected
            bridge.configCurrent()
            drain_events()
        self.assertEqual(writes(bridge, "script.edit_save"), [])
        bridge.game_list._on_reload.assert_not_called()

    def test_config_failure_keeps_form_without_following_actions(self):
        bridge = self.edit_bridge()
        bridge.game_list._on_reload = Mock()
        bridge.test_client.responses["script.edit_save"] = CliFailure(
            -32002, "拒绝写入"
        )
        edit = ScriptEdit("ok-ww", "鸣潮", {}, [60] * 7, {})
        dialog = Mock()
        dialog.isVisible.return_value = True

        def build(*args, **kwargs):
            assert "submit" in kwargs
            dialog.exec.side_effect = lambda: kwargs["submit"](edit)
            return dialog

        with (
            patch("gui.dialogs.SingleScriptConfigDialog", side_effect=build),
            patch("gui.dialogs.show_warning") as warning,
        ):
            bridge.configCurrent()
            drain_events()
        warning.assert_called_once_with(dialog, "拒绝写入")
        dialog.accept.assert_not_called()
        bridge.game_list._on_reload.assert_not_called()


class TestWeeklyStartBridge(unittest.TestCase):
    def test_weekly_start_options_are_disabled_plus_seven_days(self):
        bridge = make_bridge()
        self.assertEqual(
            [row["value"] for row in bridge.weeklyStartOptions()], list(range(8))
        )

    def test_weekly_start_request_identifies_only_the_selected_row(self):
        bridge = make_bridge()
        bridge.selectWeeklyStart("历战余响", 5)
        drain_events()
        self.assertEqual(
            writes(bridge, "weekly.start"),
            [
                {
                    "script_name": "ok-ww",
                    "weekly_name": "历战余响",
                    "start_day": 5,
                }
            ],
        )

    def test_first_weekly_start_can_be_selected_without_prior_entry(self):
        bridge = make_bridge()
        self.assertEqual(bridge.weeklyItems, [])
        bridge.selectWeeklyStart("货币战争", 4)
        drain_events()
        self.assertEqual(
            writes(bridge, "weekly.start"),
            [
                {
                    "script_name": "ok-ww",
                    "weekly_name": "货币战争",
                    "start_day": 4,
                }
            ],
        )
