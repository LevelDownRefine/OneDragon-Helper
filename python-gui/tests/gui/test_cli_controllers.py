"""轻量入口的异步边界：真实模型、过期响应、失败写入与共享会话恢复。"""

from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QImage

from gui.cli_client import CliFailure, CliSession
from gui.controllers.cli_background import CliBackgroundController, valid_wallpaper
from gui.controllers.cli_game_list import CliGameListController, valid_edit_view
from gui.controllers.cli_links import CliLinksController
from gui.controllers.cli_settings import CliSettingsController, parse_settings
from src.service.schedule import RunOptions, StartupOptions
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


def snapshot(*names):
    return {
        "default_icon_path": "",
        "scripts": [
            {
                "script_name": name,
                "display_name": name,
                "script_path": "",
                "adapted": False,
                "icon_path": None,
                "script_data": {"script_path": "", "display_name": name},
            }
            for name in names
        ],
    }


def settings():
    return {
        "startup": asdict(StartupOptions()),
        "daily_enabled": False,
        "run_options": asdict(RunOptions()),
        "shutdown_supported": True,
    }


class SessionTests(TestCase):
    def setUp(self):
        get_app()
        self.old, self.new = Transport(), Transport()
        self.factory = Mock(return_value=self.new)
        self.session = CliSession(self.old, self.factory)

    def test_shared_session_recovers_read_with_new_ids_and_never_replays_write(self):
        results, failures = [], []
        recovered = Mock()
        self.session.recovered.connect(recovered)
        first = self.session.request("script.remove", {"script_name": "A"})
        self.session.failed.connect(
            lambda request_id, failure: failures.append(request_id)
        )
        self.session.succeeded.connect(
            lambda request_id, result: results.append(request_id)
        )
        self.old.usable = False
        self.old.failed.emit(1, CliFailure("transport_failed", "lost"))
        with self.assertRaises(RuntimeError):
            self.session.request("script.remove", {"script_name": "A"})
        second = self.session.request("app.snapshot", {})
        self.assertGreater(second, first)
        self.assertEqual(self.new.requests, [("app.snapshot", {})])
        recovered.assert_not_called()
        self.old.succeeded.emit(1, None)
        self.new.succeeded.emit(1, snapshot("A"))
        self.assertEqual(failures, [first])
        self.assertEqual(results, [second])
        self.factory.assert_called_once()
        recovered.assert_called_once()

    def test_malformed_callback_is_reported_and_association_is_removed(self):
        failures = []

        def validate(result):
            parse_settings(result)

        self.session.call("settings.view", {}, validate, failures.append)
        self.old.succeeded.emit(1, {})
        self.assertEqual(failures[0].code, "invalid_response")
        self.assertEqual(self.session._callbacks, {})

    def test_exit_discards_callbacks_and_does_not_restart_session(self):
        success, failure = Mock(), Mock()
        self.session.call("settings.view", {}, success, failure)
        self.session.detach()
        self.old.succeeded.emit(1, settings())
        success.assert_not_called()
        failure.assert_not_called()
        with self.assertRaises(RuntimeError):
            self.session.request("settings.view", {})
        self.factory.assert_not_called()


class ControllerTests(TestCase):
    def setUp(self):
        get_app()
        self.transport = Transport()
        self.session = CliSession(self.transport, None)
        self.messages = []
        self.reload = Mock()
        self.games = CliGameListController(
            self.session, self.messages.append, self.reload
        )

    def load(self, *names):
        self.games.reload_games()
        self.transport.succeeded.emit(len(self.transport.requests), snapshot(*names))

    def test_list_response_is_async_and_stale_reload_does_not_replace_model(self):
        self.games.reload_games()
        self.games.reload_games()
        self.assertEqual(self.games.games, [])
        self.transport.succeeded.emit(1, snapshot("old"))
        self.assertEqual(self.games.games, [])
        self.transport.succeeded.emit(2, snapshot("A", "B"))
        self.games.selectGame(1)
        self.games._set_enabled([False, True])
        self.load("B", "A")
        self.assertEqual(self.games.current_game["script_name"], "B")
        self.assertEqual(self.games.enabled, [True, False])

    def test_list_edit_waits_for_ack_and_failure_does_not_replay(self):
        self.load("A", "B")
        self.games.reorderGames(0, 1)
        self.assertEqual([row["script_name"] for row in self.games.games], ["A", "B"])
        self.assertEqual(
            self.transport.requests[-1],
            ("script.reorder", {"script_names": ["B", "A"]}),
        )
        self.transport.succeeded.emit(2, None)
        self.reload.assert_called_once()
        self.games._on_delete_script("A")
        self.transport.failed.emit(3, CliFailure("transport_failed", "lost"))
        self.assertEqual(len(self.transport.requests), 3)
        self.assertEqual(self.messages[-1], "lost")
        self.assertFalse(self.games._mutating)

    def test_invalid_snapshot_preserves_existing_state(self):
        self.load("A")
        self.games.reload_games()
        invalid = snapshot("B")
        invalid["scripts"][0]["adapted"] = "yes"
        self.transport.succeeded.emit(2, invalid)
        self.assertEqual(self.games.current_game["script_name"], "A")
        self.assertIn("无效", self.messages[-1])

    def test_multiple_file_drop_stops_after_transport_failure(self):
        temporary = self.enterContext(TemporaryDirectory())
        paths = [Path(temporary) / name for name in ("a.py", "b.py", "c.py")]
        for path in paths:
            path.write_text("", encoding="utf-8")
        accepted = self.games.dropScripts(
            [QUrl.fromLocalFile(str(path)) for path in paths]
        )
        self.assertTrue(accepted)
        self.assertEqual(len(self.transport.requests), 1)
        self.transport.succeeded.emit(1, {"script_name": "A", "display_name": "A"})
        self.assertEqual(len(self.transport.requests), 2)
        self.transport.failed.emit(2, CliFailure("transport_failed", "lost"))
        self.assertEqual(len(self.transport.requests), 2)
        self.assertFalse(self.games._mutating)
        self.reload.assert_called_once()
        self.assertIn("lost", self.messages[-1])

    def test_script_edit_snapshot_avoids_service_io_and_save_uses_shared_signature(
        self,
    ):
        self.load("A")
        from gui.dialogs import SingleScriptConfigDialog

        view = {
            "script_name": "A",
            "script": {"display_name": "A", "script_path": ""},
            "weekly_timeouts": [120] * 7,
            "switches": [],
        }

        def edit(dialog):
            dialog.name_input.setText("renamed")
            dialog.save_data()
            self.assertEqual(self.transport.requests[-1][0], "script.edit_save")
            params = self.transport.requests[-1][1]
            self.assertEqual(
                set(params),
                {
                    "script_name",
                    "display_name",
                    "config_patch",
                    "weekly_timeouts",
                    "switches",
                },
            )
            self.assertEqual(params["display_name"], "renamed")
            self.transport.succeeded.emit(3, {"script_name": "renamed"})
            return 1

        with (
            patch.object(SingleScriptConfigDialog, "exec", edit),
            patch(
                "gui.dialogs.AppService", side_effect=AssertionError("no service reads")
            ),
        ):
            self.games.configCurrent()
            self.transport.succeeded.emit(2, view)
        self.reload.assert_called_once()

    def test_links_query_target_and_icon_stale_switch_does_not_open(self):
        self.load("A", "B")
        links = CliLinksController(self.games, self.session, self.messages.append)
        links.refresh()
        links.openHome()
        self.games.selectGame(1)
        links.refresh()
        with patch("gui.controllers.cli_links.webbrowser.open") as opened:
            self.transport.succeeded.emit(
                3, {"kind": "url", "value": "https://example.com"}
            )
        opened.assert_not_called()
        self.transport.succeeded.emit(2, {"script_name": "A", "path": "old.exe"})
        self.assertEqual(links.gameIconSource(), "")
        self.transport.succeeded.emit(4, {"script_name": "B", "path": "new.exe"})
        self.assertEqual(self.games.game_icon_provider.paths, {"B": "new.exe"})
        self.assertIn("B?v=", links.gameIconSource())
        links.launchGame()
        with patch.object(links, "_open_path", return_value=True) as opened:
            self.transport.succeeded.emit(
                5, {"kind": "association", "path": "game.exe"}
            )
        opened.assert_called_once_with("game.exe", "")

    def test_wallpaper_stale_and_changed_target_uses_cli(self):
        self.load("A", "B")
        background = CliBackgroundController(
            self.games, self.session, self.messages.append
        )
        background.apply_current(self.games.current_game)
        self.games.selectGame(1)
        background.apply_current(self.games.current_game)
        view = {
            "script_name": "A",
            "display_name": "A",
            "mode": "image",
            "source": "/tmp/a.jpg",
            "token": "a",
            "cache": None,
            "custom_path": None,
        }
        self.transport.succeeded.emit(2, view)
        self.assertEqual(background.background_mode, "gradient")
        view["script_name"] = "B"
        self.transport.succeeded.emit(3, view)
        self.assertEqual(background.background_mode, "image")
        with patch("gui.dialogs.pick_file", return_value="/tmp/b.jpg"):
            background.open_wallpaper()
        self.assertEqual(
            self.transport.requests[-1],
            ("wallpaper.set", {"script_name": "B", "file_path": "/tmp/b.jpg"}),
        )
        self.transport.succeeded.emit(4, None)
        self.assertEqual(
            self.transport.requests[-1], ("wallpaper.current", {"script_name": "B"})
        )

    def test_script_command_query_inherits_environment_and_rejects_bad_args(self):
        self.load("A")
        links = CliLinksController(self.games, self.session, self.messages.append)
        links.launchScript()
        self.assertEqual(
            self.transport.requests[-1],
            ("script.launch_target", {"script_name": "A", "target": "script"}),
        )
        command = {
            "kind": "command",
            "program": "runner",
            "args": ["--script", "a.py"],
            "cwd": "/tmp",
            "env": {"ODH_TEST": "override"},
        }
        with patch("gui.controllers.cli_links.subprocess.Popen") as popen:
            self.transport.succeeded.emit(2, command)
        self.assertEqual(popen.call_args.args[0], ["runner", "--script", "a.py"])
        self.assertEqual(popen.call_args.kwargs["env"]["ODH_TEST"], "override")
        links.launchScript()
        command["args"] = "not an array"
        with patch("gui.controllers.cli_links.subprocess.Popen") as popen:
            self.transport.succeeded.emit(3, command)
        popen.assert_not_called()
        self.assertIn("无效", self.messages[-1])

    def test_startup_save_ack_and_error_keep_dialog_input(self):
        controller = CliSettingsController(Mock(), self.session, self.messages.append)
        dialog = Mock()
        dialog.startup_options = StartupOptions(False, 12)
        dialog.isVisible.return_value = True

        def edit():
            save = dialog.saveRequested.connect.call_args.args[0]
            save()
            self.assertEqual(
                self.transport.requests[-1],
                (
                    "settings.startup_save",
                    {"options": {"enabled": False, "delay_seconds": 12}},
                ),
            )
            self.transport.failed.emit(2, CliFailure(-32002, "cannot save"))
            dialog.accept.assert_not_called()
            dialog.show_error.assert_called_once_with("cannot save")
            save()
            self.transport.succeeded.emit(3, None)
            dialog.accept.assert_called_once()

        dialog.exec.side_effect = edit
        with patch("gui.controllers.cli_settings.ConfigDialog", return_value=dialog):
            controller.openConfig()
            self.transport.succeeded.emit(1, settings())

    def test_wallpaper_cache_upload_uses_token_and_does_not_write_in_gui(self):
        self.load("A")
        background = CliBackgroundController(
            self.games, self.session, self.messages.append
        )
        background.apply_current(self.games.current_game)
        view = {
            "script_name": "A",
            "display_name": "A",
            "mode": "video",
            "source": "/tmp/a.mp4",
            "token": "identity",
            "cache": None,
            "custom_path": None,
        }
        self.transport.succeeded.emit(2, view)
        image = QImage(4, 4, QImage.Format_RGB888)
        image.fill(0)
        with patch("builtins.open", side_effect=AssertionError("no GUI writes")):
            background._save_cache(image, view, background.background_version)
        method, params = self.transport.requests[-1]
        self.assertEqual(method, "wallpaper.cache")
        self.assertEqual(params["token"], "identity")
        self.assertEqual(params["script_name"], "A")
        import base64

        self.assertTrue(base64.b64decode(params["jpeg_base64"]).startswith(b"\xff\xd8"))
        self.transport.succeeded.emit(3, True)
        self.assertEqual(self.transport.requests[-1][0], "wallpaper.current")
        view["cache"] = "/tmp/cache.jpg"
        self.transport.succeeded.emit(4, view)
        self.assertIn("cache.jpg", background.background_preview_url)

    def test_run_settings_save_uses_shared_options_and_waits_for_ack(self):
        controller = CliSettingsController(Mock(), self.session, self.messages.append)
        dialog = Mock()
        dialog.run_options = RunOptions(mute_enabled=True)

        def build(count, options, **kwargs):
            def edit():
                kwargs["submit"](dialog)
                self.assertEqual(
                    self.transport.requests[-1],
                    ("settings.run_save", {"options": asdict(dialog.run_options)}),
                )
                dialog.accept.assert_not_called()
                self.transport.succeeded.emit(2, None)
                dialog.accept.assert_called_once()

            dialog.exec.side_effect = edit
            return dialog

        with patch("gui.controllers.cli_settings.RunConfirmDialog", side_effect=build):
            controller.configureRunOptions()
            self.transport.succeeded.emit(1, settings())

    def test_bridge_initial_reads_do_not_use_service_and_auto_launch_waits_for_list(
        self,
    ):
        from gui.main_window import QmlBridge

        service = Mock()
        service.get_registered_script_names.side_effect = AssertionError(
            "GUI must not read config"
        )
        service.load_config.side_effect = AssertionError("GUI must not read config")
        with patch("gui.main_window.AppService", return_value=service):
            bridge = QmlBridge(self.transport)
        bridge.maybe_auto_launch()
        self.assertEqual(bridge.game_list.enabled, [])
        self.assertEqual(self.transport.requests, [("app.snapshot", {})])
        self.transport.succeeded.emit(1, snapshot("A"))
        methods = [method for method, _ in self.transport.requests]
        self.assertIn("wallpaper.current", methods)
        self.assertIn("script.icon_path", methods)
        self.assertIn("script.view", methods)
        self.assertIn("startup.view", methods)
        service.load_config.assert_not_called()
        service.load_startup_options.assert_not_called()
        service.load_daily_plan.assert_not_called()

    def test_response_validators_reject_wrong_nullable_fields(self):
        valid = {
            "script_name": "A",
            "script": {"display_name": "A", "script_path": ""},
            "weekly_timeouts": [120] * 7,
            "switches": [],
        }
        self.assertTrue(valid_edit_view(valid, "A"))
        invalid = deepcopy(valid)
        invalid["weekly_timeouts"][0] = True
        self.assertFalse(valid_edit_view(invalid, "A"))
        view = {
            "script_name": "A",
            "display_name": "A",
            "mode": "gradient",
            "source": "",
            "token": None,
            "cache": None,
            "custom_path": None,
        }
        self.assertTrue(valid_wallpaper(view, "A"))
        for key in ("cache", "token", "custom_path"):
            invalid = deepcopy(view)
            del invalid[key]
            self.assertFalse(valid_wallpaper(invalid, "A"))
        invalid = settings()
        invalid["startup"]["delay_seconds"] = True
        with self.assertRaises(ValueError):
            parse_settings(invalid)
