import unittest
from unittest.mock import MagicMock, patch

from src.gui.controllers.game_list import GameListController


class TestSyncWeeklyStartDay(unittest.TestCase):
    """游戏侧周几起同步应在 config.yml 落盘后、用新 script_name 触发。

    save_data 内 config.yml 尚未落盘新路径，目录解析会指向旧目录；故同步推迟到
    ChainService.update_script 之后（见 configCurrent → _sync_weekly_start_day）。
    """

    def _make_ctrl(self) -> GameListController:
        service = MagicMock()
        toast = MagicMock()
        on_reload = MagicMock()
        return GameListController(service, toast, on_reload)

    def test_sync_calls_set_weekly_start_day(self):
        """落盘后应以新 script_name 触发游戏侧原生 config 同步。"""
        ctrl = self._make_ctrl()
        with patch("src.gui.controllers.game_list.set_weekly_start_day") as mock_set:
            ctrl._sync_weekly_start_day("run", 3)
        mock_set.assert_called_once_with("run", 3)

    def test_sync_oserror_toasts_and_does_not_raise(self):
        """原生 config 目录缺失（OSError）时仅提示，不阻塞已完成的保存。"""
        ctrl = self._make_ctrl()
        with patch(
            "src.gui.controllers.game_list.set_weekly_start_day",
            side_effect=OSError("no such dir"),
        ):
            ctrl._sync_weekly_start_day("run", 3)  # 不应抛出
        ctrl._toast.assert_called_once()
