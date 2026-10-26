"""脚本列表模型、内存勾选与 CLI 写入确认。"""

import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMessageBox

from gui.cli_client import CliFailure, CliSession
from gui.controllers.cli_game_list import CliGameListController
from gui.controllers.game_list import GameListController, ScriptIconProvider
from tests.gui.helpers import get_app


class Transport(QObject):
    succeeded = Signal(int, object)
    failed = Signal(int, object)

    def __init__(self):
        super().__init__()
        self.usable = True
        self.requests = []

    def request(self, method, params):
        self.requests.append((method, params))
        return len(self.requests)

    def close(self):
        self.usable = False


def snapshot(names):
    return {
        "default_icon_path": "",
        "scripts": [
            {
                "script_name": name,
                "display_name": name,
                "script_path": f"{name}.py",
                "adapted": False,
                "icon_path": None,
                "script_data": {"display_name": name, "script_path": f"{name}.py"},
            }
            for name in names
        ],
    }


class TestScriptList(unittest.TestCase):
    def setUp(self):
        get_app()

    def controller(self, names=("A", "B")):
        transport = Transport()
        controller = CliGameListController(CliSession(transport, None), Mock(), Mock())
        controller.reload_games()
        with patch.object(controller.icon_provider, "refresh"):
            transport.succeeded.emit(1, snapshot(names))
        return controller, transport

    def reply(self, transport, result):
        transport.succeeded.emit(len(transport.requests), result)

    def test_refresh_recomputes_existing_icon_name(self):
        provider = ScriptIconProvider([])
        provider._cache["A"] = Mock()
        with patch("gui.controllers.game_list._exe_icon") as extract:
            provider.refresh([{"script_name": "A", "icon_path": "C:/new.exe"}])
        extract.assert_called_once_with("C:/new.exe")

    def test_cancel_delete_keeps_data_without_request_or_reload(self):
        controller, transport = self.controller()
        with patch("gui.dialogs.styled_msg_box") as warning:
            warning.return_value.exec.return_value = QMessageBox.Cancel
            controller.deleteScript(0)
        self.assertEqual(transport.requests, [("app.snapshot", {})])
        self.assertEqual([game["script_name"] for game in controller.games], ["A", "B"])
        controller._on_reload.assert_not_called()

    def test_confirmed_delete_reloads_only_after_cli_ack(self):
        controller, transport = self.controller()
        with patch("gui.dialogs.styled_msg_box") as warning:
            warning.return_value.exec.return_value = QMessageBox.Ok
            controller.deleteScript(0)
        self.assertEqual(
            transport.requests[-1], ("script.remove", {"script_name": "A"})
        )
        controller._on_reload.assert_not_called()
        self.reply(transport, None)
        controller._on_reload.assert_called_once()

    def test_toggle_only_touches_memory(self):
        controller, transport = self.controller()
        controller.toggleMode()
        controller.selectGame(0)
        self.assertEqual(controller.enabled, [False, True])
        self.assertEqual(transport.requests, [("app.snapshot", {})])

    def test_reopen_starts_with_all_selected(self):
        controller, _ = self.controller()
        controller.deselectAll()
        reopened, _ = self.controller()
        self.assertEqual(reopened.enabled, [True, True])

    def test_reorder_keeps_selection_by_identity_after_ack_and_readback(self):
        controller, transport = self.controller()
        controller.toggleMode()
        controller.selectGame(1)
        controller.reorderGames(1, 0)
        self.assertEqual(controller.enabled, [True, False])
        self.assertEqual(
            transport.requests[-1], ("script.reorder", {"script_names": ["B", "A"]})
        )
        self.reply(transport, None)
        controller._on_reload.assert_called_once()
        controller.reload_games()
        with patch.object(controller.icon_provider, "refresh"):
            self.reply(transport, snapshot(["B", "A"]))
        self.assertEqual([game["script_name"] for game in controller.games], ["B", "A"])
        self.assertEqual(controller.enabled, [False, True])

    def test_stale_reorder_keeps_model_until_reload(self):
        controller, transport = self.controller()
        controller.selectGame(1)
        controller._enabled = [False, True]
        controller.reorderGames(0, 1)
        transport.failed.emit(2, CliFailure(-32002, "列表已变化"))
        self.assertEqual([game["script_name"] for game in controller.games], ["A", "B"])
        self.assertEqual(controller.game_model.games, controller.games)
        self.assertEqual(controller.enabled, [False, True])
        self.assertEqual(controller.current_index, 1)
        controller._on_reload.assert_called_once()
        controller._toast.assert_called_once_with("列表已变化")

    def test_unknown_reorder_result_keeps_ui_without_replay(self):
        controller, transport = self.controller()
        controller.reorderGames(0, 1)
        transport.failed.emit(2, CliFailure("transport_failed", "拒绝写入"))
        self.assertEqual([game["script_name"] for game in controller.games], ["A", "B"])
        self.assertEqual(controller.game_model.games, controller.games)
        self.assertEqual(len(transport.requests), 2)
        controller._on_reload.assert_not_called()
        controller._toast.assert_called_once_with("拒绝写入")

    def test_reload_keeps_selection_in_bounds_and_checked_by_identity(self):
        for names, index, enabled in (
            (["C", "A", "B"], 2, [True, False, True]),
            (["A"], 0, [False]),
            ([], 0, []),
        ):
            with self.subTest(names=names):
                controller, transport = self.controller()
                controller.selectGame(1)
                controller._enabled = [False, True]
                controller.reload_games()
                with patch.object(controller.icon_provider, "refresh"):
                    self.reply(transport, snapshot(names))
                self.assertEqual(controller.enabled, enabled)
                self.assertEqual(controller.current_index, index)

    def test_delete_rejection_reports_backend_message_and_refreshes(self):
        controller, transport = self.controller()
        controller._on_delete_script("A")
        transport.failed.emit(2, CliFailure(-32002, "至少保留一个脚本"))
        controller._on_reload.assert_called_once()
        controller._toast.assert_called_once_with("至少保留一个脚本")

    def test_last_script_delete_is_blocked_locally(self):
        controller, transport = self.controller(["A"])
        with patch("gui.dialogs.styled_msg_box") as warning:
            controller.deleteScript(0)
        warning.assert_not_called()
        self.assertEqual(transport.requests, [("app.snapshot", {})])
        controller._on_reload.assert_not_called()
        controller._toast.assert_called_once_with("至少保留一个脚本，无法删除")

    def test_icons_refresh_before_model_reset(self):
        controller = GameListController(Mock(), Mock())
        order = []
        with (
            patch.object(
                controller._game_model,
                "set_games",
                side_effect=lambda games: order.append("set_games"),
            ),
            patch.object(
                controller.icon_provider,
                "refresh",
                side_effect=lambda games: order.append("refresh"),
            ),
        ):
            controller._set_games([{"script_name": "A", "display_name": "甲"}])
        self.assertEqual(order, ["refresh", "set_games"])

    def test_empty_snapshot_downgrades_gracefully(self):
        controller, _ = self.controller([])
        self.assertEqual(controller.games, [])
        self.assertEqual(controller.current_index, 0)
        self.assertIsNone(controller.current_game)
