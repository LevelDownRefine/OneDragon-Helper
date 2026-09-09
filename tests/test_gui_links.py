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
        with (
            patch(
                "src.gui.controllers.links._get_game_exe_path",
                side_effect=["C:/鸣潮/Game.exe", "D:/Game2.exe"],
            ) as read_path,
            patch(
                "src.gui.controllers.links.get_exe_icon_url",
                side_effect=["icon1", "icon2"],
            ) as read_icon,
        ):
            self.assertEqual(self.ctrl.gameIconSource(), "icon1")
            self.games.current_game = {"script_name": "second"}
            self.assertEqual(self.ctrl.gameIconSource(), "icon2")
        self.assertEqual(
            read_path.call_args_list,
            [unittest.mock.call("ok-ww"), unittest.mock.call("second")],
        )
        self.assertEqual(
            read_icon.call_args_list,
            [
                unittest.mock.call("C:/鸣潮/Game.exe"),
                unittest.mock.call("D:/Game2.exe"),
            ],
        )
        self.toast.assert_not_called()

    def test_missing_path_or_icon_returns_empty_without_toast(self):
        for path in (None, "", "C:/missing.exe"):
            with (
                self.subTest(path=path),
                patch(
                    "src.gui.controllers.links._get_game_exe_path", return_value=path
                ),
                patch("src.gui.controllers.links.get_exe_icon_url", return_value=""),
            ):
                self.assertEqual(self.ctrl.gameIconSource(), "")
        self.toast.assert_not_called()

    def test_no_current_game_does_not_read_or_toast(self):
        self.games.current_game = None
        with patch("src.gui.controllers.links._get_game_exe_path") as read_path:
            self.assertEqual(self.ctrl.gameIconSource(), "")
        read_path.assert_not_called()
        self.toast.assert_not_called()


class TestLinksOpenScriptConfig(unittest.TestCase):
    """openScriptConfig：委托 AppService.config_file_path 打开当前脚本配置文件。"""

    def _make_controller(self, config_return):
        game = {
            "script_name": "ok-ww",
            "display_name": "鸣潮",
            "script_data": {"script_path": "C:/games/run.exe"},
        }
        svc = MagicMock()
        svc.config_file_path.return_value = config_return
        toast = MagicMock()
        ctrl = LinksController(
            game_list=_FakeGameList(game), toast=toast, app_service=svc
        )
        return ctrl, svc, toast

    def test_opens_resolved_config(self):
        """service 返回 config 路径：以 open_in_explorer 打开，toast 成功。"""
        ctrl, svc, toast = self._make_controller(
            ("C:/games/config/DailyTask.json", None)
        )
        with patch("src.gui.controllers.links.open_in_explorer") as mock_open:
            ctrl.openScriptConfig()
        mock_open.assert_called_once_with("C:/games/config/DailyTask.json")
        svc.config_file_path.assert_called_once_with("ok-ww")
        toast.assert_called_once_with("已打开 鸣潮 配置文件")

    def test_missing_shows_toast(self):
        """service 返回错误：不打开文件，toast 透传错误文案。"""
        ctrl, svc, toast = self._make_controller(
            (None, "该脚本暂未适配配置文件，无法打开")
        )
        with patch("src.gui.controllers.links.open_in_explorer") as mock_open:
            ctrl.openScriptConfig()
        mock_open.assert_not_called()
        toast.assert_called_once_with("鸣潮：该脚本暂未适配配置文件，无法打开")


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
