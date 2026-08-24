"""测试 GameListController 的删除脚本入口（左侧拖拽到删除区的落盘逻辑）。"""

import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.gui.controllers.game_list import GameListController

_app = QApplication.instance() or QApplication([])


def _make_controller():
    """构造 GameListController（service/toast/on_reload 全 mock），预置两条脚本。"""
    service = MagicMock()
    service.load_config.return_value = {"script_list": []}
    reload_spy = MagicMock()
    ctrl = GameListController(service=service, toast=MagicMock(), on_reload=reload_spy)
    ctrl._games = [
        {
            "display_name": "甲",
            "script_name": "a",
            "script_data": {},
            "char": "甲",
            "color": "#111111",
        },
        {
            "display_name": "乙",
            "script_name": "b",
            "script_data": {},
            "char": "乙",
            "color": "#222222",
        },
    ]
    return ctrl, service, reload_spy


class TestDeleteScript(unittest.TestCase):
    def test_delete_script_removes_and_reloads(self):
        """按 index 删除：二次确认后调 remove_script（按名字）并触发一次门面级重载。"""
        ctrl, service, reload_spy = _make_controller()
        with patch("src.gui.controllers.game_list.QMessageBox") as mock_box:
            mock_box.Ok = "OK"
            mock_box.return_value.exec.return_value = "OK"
            ctrl.deleteScript(0)
        service.remove_script.assert_called_once_with("a")
        reload_spy.assert_called_once()

    def test_delete_script_cancel_does_not_remove(self):
        """确认弹窗取消时，不删除、不重载。"""
        ctrl, service, reload_spy = _make_controller()
        with patch("src.gui.controllers.game_list.QMessageBox") as mock_box:
            mock_box.Ok = "OK"
            mock_box.return_value.exec.return_value = "CANCEL"
            ctrl.deleteScript(0)
        service.remove_script.assert_not_called()
        reload_spy.assert_not_called()

    def test_delete_script_out_of_range_asserts(self):
        """越界 index 直接断言失败，不触碰 service。"""
        ctrl, service, reload_spy = _make_controller()
        with self.assertRaises(AssertionError):
            ctrl.deleteScript(99)
        service.remove_script.assert_not_called()
        reload_spy.assert_not_called()
