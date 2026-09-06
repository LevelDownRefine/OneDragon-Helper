import unittest
from unittest.mock import MagicMock, patch

from src.gui.controllers.game_list import GameListController, ScriptIconProvider


class TestConfigCurrentWeeklyStartSync(unittest.TestCase):
    """周几起随 update_script 统一落盘：游戏侧 OSError 属部分失败，提示不回滚。"""

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

    def test_update_script_receives_weekly_start_day(self):
        ctrl = self._make_ctrl()
        with patch("src.gui.controllers.game_list.QMessageBox") as mock_box:
            mock_box.Ok = 1
            mock_box.Cancel = 2
            mock_box.return_value.exec.return_value = 1
            with patch("src.gui.dialogs.SingleScriptConfigDialog") as mock_dialog_cls:
                mock_dialog_cls.return_value.exec.return_value = 1
                mock_dialog_cls.return_value.pending_changes = {
                    "old_script_name": "wu",
                    "new_display_name": "鸣潮",
                    "config_patch": {"script_path": "C:/wu.exe"},
                    "weekly_timeouts": [60] * 7,
                    "weekly_start_day": 3,
                }
                ctrl.configCurrent()
        ctrl._app_service.update_script.assert_called_once_with(
            "wu", "鸣潮", {"script_path": "C:/wu.exe"}, [60] * 7, 3
        )

    def test_update_script_oserror_toasts_and_still_reloads(self):
        """游戏侧同步 OSError：toast 提示，但 config.yml 已落盘故仍重载。"""
        ctrl = self._make_ctrl()
        ctrl._app_service.update_script.side_effect = OSError("no such dir")
        with patch("src.gui.controllers.game_list.QMessageBox") as mock_box:
            mock_box.Ok = 1
            mock_box.Cancel = 2
            mock_box.return_value.exec.return_value = 1
            with patch("src.gui.dialogs.SingleScriptConfigDialog") as mock_dialog_cls:
                mock_dialog_cls.return_value.exec.return_value = 1
                mock_dialog_cls.return_value.pending_changes = {
                    "old_script_name": "wu",
                    "new_display_name": "鸣潮",
                    "config_patch": {},
                    "weekly_timeouts": [60] * 7,
                    "weekly_start_day": 3,
                }
                ctrl.configCurrent()  # 不应抛出
        ctrl._on_reload.assert_called_once()
        # 部分失败提示 + 成功提示并存（与旧行为一致）
        self.assertTrue(any("周几起" in c[0][0] for c in ctrl._toast.call_args_list))


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
            },
            {
                "display_name": "测试脚本",
                "script_name": "demo",
                "script_data": {"script_type": "python", "script_path": "demo.py"},
                "char": "测",
                "color": "#161C28",
            },
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
        ctrl._app_service.remove_script.assert_not_called()
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
        ctrl._app_service.remove_script.assert_called_once_with("wu")
        ctrl._on_reload.assert_called_once()


class TestDeleteScriptLastGuard(unittest.TestCase):
    """最后一个脚本不可删：删光会让列表/任务卡失去当前项，拦截并提示。"""

    @patch("src.gui.controllers.game_list.QMessageBox")
    def test_last_script_delete_blocked_with_toast(self, mock_box):
        ctrl = GameListController(MagicMock(), MagicMock(), MagicMock())
        ctrl._games = [
            {
                "display_name": "鸣潮",
                "script_name": "wu",
                "script_data": {"script_type": "external", "script_path": "C:/wu.exe"},
                "char": "鸣",
                "color": "#161C28",
            }
        ]
        ctrl.deleteScript(0)
        # 不弹确认框、不落盘、不重载，仅 toast 提示
        mock_box.assert_not_called()
        ctrl._app_service.remove_script.assert_not_called()
        ctrl._on_reload.assert_not_called()
        ctrl._toast.assert_called_once()


class TestReloadGamesIconOrder(unittest.TestCase):
    """reload_games 必须在 set_games 之前刷新图标缓存，否则新脚本首帧空白。

    旧顺序：set_games（触发 delegate 重建并立即请求 pixmap）→ refresh 才填缓存，
    导致首帧取到空/陈旧缓存、刷新后不自动重取，须重启才显示。本测试钉死顺序。
    """

    def test_refresh_before_set_games(self):
        ctrl = GameListController(MagicMock(), MagicMock(), MagicMock())
        ctrl._app_service.load_config.return_value = {
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


class TestReloadGamesEmpty(unittest.TestCase):
    """config.yml 无脚本（手改删空）属可恢复外部输入：降级空列表，不崩。"""

    def test_empty_config_downgrades_gracefully(self):
        ctrl = GameListController(MagicMock(), MagicMock(), MagicMock())
        ctrl._app_service.load_config.return_value = {"script_list": []}
        ctrl.reload_games()  # 不应抛出
        self.assertEqual(ctrl.games, [])
        self.assertEqual(ctrl.current_index, 0)
