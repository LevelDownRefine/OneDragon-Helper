"""测试 src/gui/controllers/links.py：LinksController 各跳转动作。"""

import unittest
from unittest.mock import MagicMock, patch

from src.gui.controllers.links import LinksController


class _FakeGameList:
    """极简 game_list 替身：仅提供 current_game。"""

    def __init__(self, game):
        self.current_game = game


class TestLinksGameIcon(unittest.TestCase):
    def setUp(self):
        self.games = _FakeGameList({"script_name": "ok-ww"})
        self.toast = MagicMock()
        self.ctrl = LinksController(self.games, self.toast, MagicMock())

    def test_reads_current_game_exe_each_time(self):
        with patch.object(
            self.ctrl._app_service,
            "game_icon_path",
            side_effect=[{"path": "C:/鸣潮/Game.exe"}, {"path": "D:/Game2.exe"}],
        ) as read_path:
            self.assertEqual(self.ctrl.gameIconSource(), "image://gameicon/ok-ww")
            self.games.current_game = {"script_name": "second"}
            self.assertEqual(self.ctrl.gameIconSource(), "image://gameicon/second")
        self.assertEqual(
            read_path.call_args_list,
            [unittest.mock.call("ok-ww"), unittest.mock.call("second")],
        )
        self.toast.assert_not_called()

    def test_falsy_path_returns_empty_without_toast(self):
        for path in (None, ""):
            with (
                self.subTest(path=path),
                patch.object(
                    self.ctrl._app_service,
                    "game_icon_path",
                    return_value={"path": path},
                ),
            ):
                self.assertEqual(self.ctrl.gameIconSource(), "")
        self.toast.assert_not_called()

    def test_no_current_game_does_not_read_or_toast(self):
        self.games.current_game = None
        with patch.object(self.ctrl._app_service, "game_icon_path") as read_path:
            self.assertEqual(self.ctrl.gameIconSource(), "")
        read_path.assert_not_called()
        self.toast.assert_not_called()


class TestLinksOpenScriptConfig(unittest.TestCase):
    """openScriptConfig：委托 AppService.resolve_script_target 打开当前脚本配置文件。"""

    def _make_controller(self, config_return):
        game = {
            "script_name": "ok-ww",
            "display_name": "鸣潮",
            "script_data": {"script_path": "C:/games/run.exe"},
        }
        svc = MagicMock()
        svc.resolve_script_target.return_value = config_return
        toast = MagicMock()
        ctrl = LinksController(
            game_list=_FakeGameList(game), toast=toast, app_service=svc
        )
        return ctrl, svc, toast

    def test_opens_resolved_config(self):
        """service 返回 config 路径：以 open_in_explorer 打开，toast 成功。"""
        ctrl, svc, toast = self._make_controller(
            {"kind": "path", "value": "C:/games/config/DailyTask.json"}
        )
        with patch("src.gui.controllers.links.open_in_explorer") as mock_open:
            ctrl.openScriptConfig()
        mock_open.assert_called_once_with("C:/games/config/DailyTask.json")
        svc.resolve_script_target.assert_called_once_with("ok-ww", "configfile")
        toast.assert_called_once_with("已打开 鸣潮 配置文件")

    def test_missing_shows_toast(self):
        """service 返回错误：不打开文件，toast 透传错误文案。"""
        ctrl, svc, toast = self._make_controller(
            {"kind": "unavailable", "reason": "该脚本暂未适配配置文件，无法打开"}
        )
        with patch("src.gui.controllers.links.open_in_explorer") as mock_open:
            ctrl.openScriptConfig()
        mock_open.assert_not_called()
        toast.assert_called_once_with("鸣潮：该脚本暂未适配配置文件，无法打开")

    def test_all_toolbar_paths_use_the_same_resolver(self):
        for action, target in (
            ("openScriptFolder", "folder"),
            ("openLogFolder", "log"),
            ("openScriptConfig", "configfile"),
        ):
            with self.subTest(action=action):
                ctrl, service, toast = self._make_controller(
                    {"kind": "path", "value": "C:/中文 100%/data"}
                )
                with patch("src.gui.controllers.links.open_in_explorer") as open_path:
                    getattr(ctrl, action)()
                service.resolve_script_target.assert_called_once_with("ok-ww", target)
                open_path.assert_called_once_with("C:/中文 100%/data")
                toast.assert_called_once()

    def test_browser_refusal_is_reported(self):
        ctrl, service, toast = self._make_controller(
            {"kind": "url", "value": "https://example.org"}
        )
        with patch("src.gui.controllers.links.webbrowser.open", return_value=False):
            ctrl.openGithub()
        service.resolve_script_target.assert_called_once_with("ok-ww", "github")
        toast.assert_called_once_with("无法打开GitHub：https://example.org")


class TestOpenPathOSError(unittest.TestCase):
    """_open_path：无关联程序等 OSError 转 toast，不逃逸出 QML 槽。"""

    def _make(self):
        game = {
            "script_name": "ok-ww",
            "display_name": "鸣潮",
            "script_data": {"script_path": "C:/games/run.exe"},
        }
        toast = MagicMock()
        ctrl = LinksController(
            game_list=_FakeGameList(game), toast=toast, app_service=MagicMock()
        )
        return ctrl, toast

    def test_oserror_toasts_failure_only(self):
        ctrl, toast = self._make()
        with patch(
            "src.gui.controllers.links.open_in_explorer",
            side_effect=OSError("no association"),
        ):
            ok = ctrl._open_path("C:/x/settings.yml")
        self.assertFalse(ok)
        toast.assert_called_once()
        self.assertIn("无法打开", toast.call_args[0][0])

    def test_success_returns_true(self):
        ctrl, toast = self._make()
        with patch("src.gui.controllers.links.open_in_explorer"):
            ok = ctrl._open_path("C:/games")
        self.assertTrue(ok)
        toast.assert_not_called()  # 成功提示由调用方给文案


class TestLinksEmptyCurrent(unittest.TestCase):
    """config 删空（current_game 为 None）时各槽只 toast，不越界触发，不崩。

    旧实现直接 ``current_game["script_name"]`` 取键，空列表会抛 KeyError 逃出槽。
    """

    ACTIONS = [
        "launchGame",
        "openHome",
        "openBilibili",
        "openGithub",
        "openScriptFolder",
        "openLogFolder",
        "openScriptConfig",
    ]

    def _make_ctrl(self) -> LinksController:
        toast = MagicMock()
        return LinksController(
            game_list=_FakeGameList(None), toast=toast, app_service=MagicMock()
        )

    def test_each_action_degrades_with_toast(self):
        for action in self.ACTIONS:
            with self.subTest(action=action):
                ctrl = self._make_ctrl()
                getattr(ctrl, action)()
                ctrl._toast.assert_called_once_with("尚无脚本")


if __name__ == "__main__":
    unittest.main()
