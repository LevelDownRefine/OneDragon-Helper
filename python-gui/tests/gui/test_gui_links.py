"""CLI 资源目标查询、本机打开动作及图标刷新。"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from gui.controllers.cli_links import CliLinksController
from gui.controllers.links import LinksController
from tests.gui.helpers import get_app


class Session:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def call(self, method, params, loaded, failed):
        self.calls.append((method, params))
        loaded(self.result(params) if callable(self.result) else self.result)


class TestLinks(unittest.TestCase):
    def setUp(self):
        get_app()

    def controller(self, result, game=None):
        games = SimpleNamespace(
            current_game=game or {"script_name": "ok-ww", "display_name": "鸣潮"},
            game_icon_provider=SimpleNamespace(paths={}),
        )
        session, toast = Session(result), Mock()
        return CliLinksController(games, session, toast), session, toast

    def test_icon_refresh_queries_current_identity_and_discards_old_source(self):
        controller, session, toast = self.controller(
            lambda params: {"script_name": params["script_name"], "path": "C:/game.exe"}
        )
        controller.refresh()
        self.assertEqual(controller.gameIconSource(), "image://gameicon/ok-ww?v=1")
        controller._game_list.current_game = {"script_name": "second"}
        controller.refresh()
        self.assertEqual(controller.gameIconSource(), "image://gameicon/second?v=2")
        self.assertEqual(
            session.calls,
            [
                ("script.icon_path", {"script_name": "ok-ww"}),
                ("script.icon_path", {"script_name": "second"}),
            ],
        )
        toast.assert_not_called()

    def test_missing_icon_path_uses_text_without_toast(self):
        for path in (None, ""):
            with self.subTest(path=path):
                controller, _, toast = self.controller(
                    {"script_name": "ok-ww", "path": path}
                )
                controller.refresh()
                self.assertEqual(controller.gameIconSource(), "")
                toast.assert_not_called()

    def test_empty_current_icon_does_not_query_or_toast(self):
        controller, session, toast = self.controller(None)
        controller._game_list.current_game = None
        controller.refresh()
        self.assertEqual(controller.gameIconSource(), "")
        self.assertEqual(session.calls, [])
        toast.assert_not_called()

    def test_game_arguments_reach_system_opener_unchanged(self):
        arguments = '--profile "中文 空格" --literal "a&b"'
        controller, session, toast = self.controller(
            {
                "kind": "association",
                "path": "C:/Game/game.exe",
                "arguments": arguments,
            }
        )
        with patch("gui.controllers.links.open_in_explorer") as opener:
            controller.launchGame()
        opener.assert_called_once_with("C:/Game/game.exe", arguments)
        self.assertEqual(
            session.calls,
            [("script.launch_target", {"script_name": "ok-ww", "target": "game"})],
        )
        toast.assert_called_once_with("正在启动 鸣潮…")

    def test_successful_game_cli_is_reaped_without_error_or_blocking_wait(self):
        controller, _, toast = self.controller(
            {
                "kind": "command",
                "program": "C:/Helper/CLI.exe",
                "args": ["--launch-game=demo"],
                "cwd": "C:/Helper",
                "env": {},
            }
        )
        with patch("gui.controllers.links.subprocess.Popen") as spawn:
            spawn.return_value.poll.return_value = 0
            controller.launchGame()
        controller._game_launch_timer.setInterval(0)
        get_app().processEvents()
        self.assertFalse(controller._game_launch_timer.isActive())
        self.assertEqual(controller._game_launches, [])
        spawn.return_value.wait.assert_not_called()
        spawn.return_value.kill.assert_not_called()
        toast.assert_called_once_with("正在启动 鸣潮…")

    def test_config_target_opens_path_from_cli(self):
        controller, session, toast = self.controller(
            {"kind": "path", "value": "C:/games/config/DailyTask.json"}
        )
        with patch("gui.controllers.links.open_in_explorer") as opener:
            controller.openScriptConfig()
        opener.assert_called_once_with("C:/games/config/DailyTask.json")
        self.assertEqual(
            session.calls,
            [("script.target", {"script_name": "ok-ww", "target": "configfile"})],
        )
        toast.assert_called_once_with("已打开 鸣潮 配置文件")

    def test_unavailable_target_only_toasts(self):
        controller, _, toast = self.controller(
            {"kind": "unavailable", "reason": "该脚本暂未适配配置文件，无法打开"}
        )
        with patch("gui.controllers.links.open_in_explorer") as opener:
            controller.openScriptConfig()
        opener.assert_not_called()
        toast.assert_called_once_with("鸣潮：该脚本暂未适配配置文件，无法打开")

    def test_toolbar_paths_query_cli_and_keep_unicode(self):
        for action, target in (
            ("openScriptFolder", "folder"),
            ("openLogFolder", "log"),
            ("openScriptConfig", "configfile"),
        ):
            with self.subTest(action=action):
                controller, session, toast = self.controller(
                    {"kind": "path", "value": "C:/中文 100%/data"}
                )
                with patch("gui.controllers.links.open_in_explorer") as opener:
                    getattr(controller, action)()
                self.assertEqual(
                    session.calls,
                    [("script.target", {"script_name": "ok-ww", "target": target})],
                )
                opener.assert_called_once_with("C:/中文 100%/data")
                toast.assert_called_once()

    def test_browser_refusal_is_reported(self):
        controller, session, toast = self.controller(
            {"kind": "url", "value": "https://example.org"}
        )
        with patch("gui.controllers.cli_links.webbrowser.open", return_value=False):
            controller.openGithub()
        self.assertEqual(
            session.calls,
            [("script.target", {"script_name": "ok-ww", "target": "github"})],
        )
        toast.assert_called_once_with("无法打开GitHub：https://example.org")

    def test_os_open_error_is_reported_without_success(self):
        toast = Mock()
        controller = LinksController(SimpleNamespace(current_game=None), toast)
        with patch(
            "gui.controllers.links.open_in_explorer",
            side_effect=OSError("no association"),
        ):
            self.assertFalse(controller._open_path("C:/x/settings.yml"))
        toast.assert_called_once()
        self.assertIn("无法打开", toast.call_args.args[0])

    def test_os_open_success_leaves_feedback_to_caller(self):
        toast = Mock()
        controller = LinksController(SimpleNamespace(current_game=None), toast)
        with patch("gui.controllers.links.open_in_explorer"):
            self.assertTrue(controller._open_path("C:/games"))
        toast.assert_not_called()

    def test_empty_current_actions_toast_without_query(self):
        for action in (
            "launchGame",
            "openHome",
            "openBilibili",
            "openGithub",
            "openScriptFolder",
            "openLogFolder",
            "openScriptConfig",
        ):
            with self.subTest(action=action):
                controller, session, toast = self.controller(None)
                controller._game_list.current_game = None
                getattr(controller, action)()
                toast.assert_called_once_with("尚无脚本")
                self.assertEqual(session.calls, [])
