import unittest
from unittest.mock import MagicMock, patch

from src.gui.controllers.game_list import GameListController, ScriptIconProvider


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


class TestScriptIconProviderRefresh(unittest.TestCase):
    """refresh 应全量重算，路径变更后即时刷新（不跳过已存在的 script_name）。"""

    def test_refresh_recomputes_existing_name(self):
        """已存在的 script_name 也被重新取图标。

        旧实现 ``if name not in self._cache`` 会跳过已存在项，导致改路径
        （script_name 不变）后图标不刷新，需重启才更新。
        """
        provider = ScriptIconProvider([])
        provider._cache["x"] = MagicMock()  # 模拟既有缓存
        games = [
            {
                "script_name": "x",
                "script_data": {"script_type": "external", "script_path": "p"},
            }
        ]
        with patch("src.gui.controllers.game_list.get_script_icon") as mock_icon:
            mock_icon.return_value = MagicMock()
            provider.refresh(games)
        mock_icon.assert_called_once()


class TestDeleteScriptConfirmCancel(unittest.TestCase):
    """拖拽删除二次确认：取消必须保留数据，确认才落盘重载。

    数据层正确性（对应 QML 取消后图标视觉复位 bug 的底层保障）：
    cancel → 不调用 remove_script / on_reload；ok → 二者都被调用。
    """

    def _make_ctrl(self) -> GameListController:
        service = MagicMock()
        ctrl = GameListController(service, MagicMock(), MagicMock())
        ctrl._games = [
            {
                "display_name": "鸣潮",
                "script_name": "wu",
                "script_data": {"script_type": "external", "script_path": "C:/wu.exe"},
                "char": "鸣",
                "color": "#161C28",
            }
        ]
        return ctrl

    @patch("src.gui.controllers.game_list.QMessageBox")
    def test_cancel_keeps_data(self, mock_box):
        """取消确认时不删除、不重载（图标数据保留，仅视觉需复位）。"""
        mock_box.Ok = 1
        mock_box.Cancel = 2
        instance = mock_box.return_value
        instance.exec.return_value = 2  # Cancel
        ctrl = self._make_ctrl()
        ctrl.deleteScript(0)
        ctrl._service.remove_script.assert_not_called()
        ctrl._on_reload.assert_not_called()

    @patch("src.gui.controllers.game_list.QMessageBox")
    def test_ok_removes_and_reloads(self, mock_box):
        """确认删除时按 script_name 落盘移除并触发重载。"""
        mock_box.Ok = 1
        mock_box.Cancel = 2
        instance = mock_box.return_value
        instance.exec.return_value = 1  # Ok
        ctrl = self._make_ctrl()
        ctrl.deleteScript(0)
        ctrl._service.remove_script.assert_called_once_with("wu")
        ctrl._on_reload.assert_called_once()


class TestReloadGamesIconOrder(unittest.TestCase):
    """reload_games 必须在 set_games 之前刷新图标缓存，否则新脚本首帧空白。

    旧顺序：set_games（触发 delegate 重建并立即请求 pixmap）→ refresh 才填缓存，
    导致首帧取到空/陈旧缓存、刷新后不自动重取，须重启才显示。本测试钉死顺序。
    """

    def test_refresh_before_set_games(self):
        ctrl = GameListController(MagicMock(), MagicMock(), MagicMock())
        ctrl._service.load_config.return_value = {
            "script_list": [
                {
                    "display_name": "鸣潮",
                    "script_type": "external",
                    "script_path": "C:/wuthering.exe",
                }
            ]
        }
        order: list[str] = []
        with (
            patch.object(
                ctrl._game_model,
                "set_games",
                side_effect=lambda g: order.append("set_games"),
            ),
            patch.object(
                ctrl.icon_provider,
                "refresh",
                side_effect=lambda g: order.append("refresh"),
            ),
        ):
            ctrl.reload_games()
        self.assertEqual(order, ["refresh", "set_games"])
