"""测试 QmlBridge 任务卡后端（日常副本 / 周常周几）。

复用 test_qml_launcher 的 _make_bridge：用 mock 隔离 ChainService 的 config /
ui_state / 壁纸 I/O；is_adapted / ScriptService.get_weekly_defs / dungeon_map /
parse_dungeon_config 按用例 patch（这些名字实际由 task_card 子模块引用，
patch 目标指向 task_card），验证 QML 任务卡所需的数据与写回行为。
"""

import unittest
from unittest.mock import MagicMock, patch

from src.gui import main_window
from src.gui.controllers import task_card
from tests.test_qml_launcher import _make_bridge


class TestTaskCard(unittest.TestCase):
    """任务卡数据 / 写回：与旧 task_card.py 对齐。"""

    @patch.object(task_card, "is_adapted", return_value=True)
    @patch.object(
        task_card.ScriptService, "get_weekly_defs", return_value=[{"name": "周常"}]
    )
    @patch.object(task_card.ScriptService, "get_weekly_start", return_value=None)
    @patch.object(main_window.ChainService, "dungeon_map", return_value={})
    def test_daily_text_default_is_placeholder(self, *_):
        b = _make_bridge()
        self.assertEqual(b.dailyDungeonText, "选择副本")
        self.assertEqual(b.weeklyStartLabel, "选择周几")

    @patch.object(task_card, "is_adapted", return_value=False)
    @patch.object(main_window.ChainService, "dungeon_map", return_value={})
    def test_task_adapted_reflects_is_adapted(self, *_):
        b = _make_bridge()
        self.assertFalse(b.taskAdapted)

    class _AnyMap(dict):
        """dungeon_map().get(name) 恒返回 truthy，模拟「该游戏有副本配置」。"""

        def get(self, key, default=None):
            return 1

    @patch.object(task_card, "is_adapted", return_value=True)
    @patch.object(main_window.ChainService, "dungeon_map", return_value=_AnyMap())
    def test_daily_supported_true_when_dungeon_cfg_present(self, *_):
        b = _make_bridge()
        self.assertTrue(b.dailySupported)

    @patch.object(task_card, "is_adapted", return_value=True)
    @patch.object(main_window.ChainService, "dungeon_map", return_value={})
    def test_daily_supported_false_when_no_dungeon_cfg(self, *_):
        b = _make_bridge()
        self.assertFalse(b.dailySupported)

    @patch.object(task_card, "is_adapted", return_value=True)
    @patch.object(task_card.ScriptService, "get_weekly_defs", return_value=[])
    @patch.object(main_window.ChainService, "dungeon_map", return_value={})
    def test_select_dungeon_persists(self, *_):
        b = _make_bridge()
        name = b.games[0]["script_name"]
        with patch.object(b.service, "save_ui_state") as m_save:
            b.selectDungeon("副本A", "seq1")
        self.assertEqual(b.task_card._ui_state[name]["dungeon"], "副本A")
        self.assertEqual(b.task_card._ui_state[name]["sequence"], "seq1")
        # 无 seq_map → chip 文字回退为副本名
        self.assertEqual(b.dailyDungeonText, "副本A")
        # 对齐旧 GUI：日常副本选择持久化到 gui_state.json
        m_save.assert_called_once()

    @patch.object(task_card, "is_adapted", return_value=True)
    @patch.object(task_card.ScriptService, "get_weekly_defs", return_value=[])
    @patch.object(main_window.ChainService, "dungeon_map", return_value={})
    def test_select_dungeon_clear_removes(self, *_):
        b = _make_bridge()
        b.selectDungeon("副本A", "seq1")
        name = b.games[0]["script_name"]
        b.selectDungeon("未选择", None)
        self.assertNotIn("dungeon", b.task_card._ui_state.get(name, {}))
        self.assertNotIn("sequence", b.task_card._ui_state.get(name, {}))
        self.assertEqual(b.dailyDungeonText, "选择副本")

    @patch.object(task_card, "is_adapted", return_value=True)
    @patch.object(
        task_card.ScriptService, "get_weekly_defs", return_value=[{"name": "周常"}]
    )
    @patch.object(main_window.ChainService, "dungeon_map", return_value={})
    @patch.object(task_card.ScriptService, "set_weekly_start")
    @patch.object(task_card.ScriptService, "get_weekly_start", return_value=3)
    def test_select_weekly_persists(self, *_):
        b = _make_bridge()
        name = b.games[0]["script_name"]
        b.selectWeekly(3)
        task_card.ScriptService.set_weekly_start.assert_called_once_with(name, 3)
        self.assertEqual(b.weeklyStartLabel, "周三起")
        # 周常起始日持久化到 weekly_start.yml（不再经 gui_state）

    @patch.object(task_card, "is_adapted", return_value=True)
    @patch.object(
        task_card,
        "parse_dungeon_config",
        return_value=(["未选择", "副本A"], {"副本A": [("难1", "s1")]}, None),
    )
    def test_dungeon_options_shape(self, *_):
        # dungeon_map().get(script_name) 恒返回 truthy，使 _build_dungeon_options 进入解析分支
        class _Map(dict):
            def get(self, key, default=None):
                return 1

        with patch.object(main_window.ChainService, "dungeon_map") as m_dm:
            m_dm.return_value = _Map()
            b = _make_bridge()
        opts = b.dungeonOptions
        self.assertEqual(opts[0], {"name": "未选择", "clear": True, "sequences": []})
        self.assertEqual(opts[1]["name"], "副本A")
        self.assertEqual(opts[1]["sequences"], [{"label": "难1", "value": "s1"}])

    @patch.object(main_window.ChainService, "dungeon_map", return_value={})
    def test_dungeon_options_empty_when_no_cfg(self, *_):
        b = _make_bridge()
        self.assertEqual(b.dungeonOptions, [])

    @patch("src.gui.dialogs.SingleScriptConfigDialog")
    @patch("PySide6.QtWidgets.QDialog")
    def test_config_current_accept_saves_and_reloads(
        self, mock_qdialog, mock_dialog_cls
    ):
        b = _make_bridge()
        toasts = []
        b.toastRequested.connect(lambda t: toasts.append(t))
        dlg = mock_dialog_cls.return_value
        dlg.delete_requested = MagicMock()
        dlg.exec.return_value = mock_qdialog.Accepted
        dlg.pending_changes = {
            "old_script_name": "ok-ww",
            "new_display_name": "鸣潮",
            "config_patch": {"k": "v"},
            "weekly_timeouts": {"1": [1]},
        }
        with (
            patch.object(b.service, "update_script") as mock_update,
            patch.object(b, "_reload_games") as mock_reload,
        ):
            b.configCurrent()
        mock_update.assert_called_once_with("ok-ww", "鸣潮", {"k": "v"}, {"1": [1]})
        mock_reload.assert_called_once()
        self.assertTrue(any("已保存" in s for s in toasts))

    @patch("src.gui.dialogs.SingleScriptConfigDialog")
    @patch("PySide6.QtWidgets.QDialog")
    def test_config_current_cancel_does_not_save(self, mock_qdialog, mock_dialog_cls):
        b = _make_bridge()
        dlg = mock_dialog_cls.return_value
        dlg.delete_requested = MagicMock()
        dlg.exec.return_value = mock_qdialog.Rejected  # 取消/关闭
        with (
            patch.object(b.service, "update_script") as mock_update,
            patch.object(b, "_reload_games") as mock_reload,
        ):
            b.configCurrent()
        mock_update.assert_not_called()
        mock_reload.assert_not_called()


if __name__ == "__main__":
    unittest.main()
