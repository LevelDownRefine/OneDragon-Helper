"""测试 src/gui/controllers/links.py：LinksController 各跳转动作。"""

import unittest
from unittest.mock import MagicMock, patch

from src.gui.controllers.links import LinksController


class _FakeGameList:
    """极简 game_list 替身：仅提供 current_game。"""

    def __init__(self, game):
        self.current_game = game


class TestLinksOpenScriptConfig(unittest.TestCase):
    """openScriptConfig：委托 ScriptService.config_file_path 打开当前脚本配置文件。"""

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


if __name__ == "__main__":
    unittest.main()
