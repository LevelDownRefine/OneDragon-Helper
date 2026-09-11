"""测试 QmlBridge 任务卡后端（日常副本 / 周常周几）。

复用 test_qml_launcher 的 _make_bridge：用 mock 隔离 config / 壁纸 I/O；is_adapted / app_service.get_weekly_map / get_daily_map /
日常菜单数据按用例 patch（task_card 经 AppService 取数，patch 目标指向
真实模块函数），验证 QML 任务卡所需的数据与写回行为。
"""

import unittest
from unittest.mock import MagicMock, patch

from src.gui.controllers import task_card
from src.service import app_service
from tests.test_qml_launcher import _make_bridge


class TestTaskCard(unittest.TestCase):
    """任务卡数据 / 写回：与旧 task_card.py 对齐。"""

    @patch("src.service.app_service.get_daily_map", return_value={})
    def test_restore_refreshes_task_properties(self, _map):
        bridge = _make_bridge()
        name = bridge.games[0]["script_name"]
        bridge.task_card._daily_map_cache = {
            name: [{"display_name": "每日任务", "options": {"values": []}}]
        }
        changed = MagicMock()
        bridge.taskStateChanged.connect(changed)
        bridge.app_service.restore_backup = MagicMock(
            return_value={"restored": 1, "skipped_scripts": []}
        )
        with (
            patch.object(bridge.backup, "_pick_zip", return_value="backup.zip"),
            patch.object(
                app_service, "get_daily_task", return_value=("副本A", None)
            ) as dungeon,
        ):
            self.assertEqual(bridge.dailyItems[0]["selection_label"], "副本A")
            dungeon.return_value = ("副本B", None)
            bridge.restoreConfig()
            changed.assert_called_once_with()
            self.assertEqual(bridge.dailyItems[0]["selection_label"], "副本B")

    @patch.object(task_card, "is_adapted", return_value=False)
    @patch("src.service.app_service.get_daily_map", return_value={})
    def test_no_daily_declaration(self, *_):
        b = _make_bridge()
        self.assertFalse(b.taskAdapted)
        self.assertEqual(b.dailyItems, [])

    @patch("src.service.app_service.set_config")
    @patch("src.service.app_service.get_daily_task", return_value=(None, None))
    def test_select_second_daily_writes_named_config(self, _read, write):
        b = _make_bridge()
        name = b.games[0]["script_name"]
        b.task_card._daily_map_cache = {
            name: [
                {
                    "display_name": "资源",
                    "options": {"values": [{"display_name": "副本A"}]},
                },
                {
                    "display_name": "清理",
                    "options": {
                        "values": [
                            {
                                "display_name": "副本B",
                                "options": {
                                    "values": [
                                        {"display_name": "难1", "physical_name": "s1"}
                                    ]
                                },
                            }
                        ]
                    },
                },
            ]
        }
        self.assertEqual([row["name"] for row in b.dailyItems], ["资源", "清理"])
        self.assertEqual(
            b.dailyItems[1]["options"][0]["options"],
            [{"name": "难1", "value": "s1"}],
        )
        b.selectDailyTask("清理", "副本B", "s1")
        write.assert_called_once_with(
            name, daily_name="清理", option_name="副本B", sequence="s1"
        )

    @patch("src.gui.dialogs.SingleScriptConfigDialog")
    @patch("PySide6.QtWidgets.QDialog")
    def test_config_current_accept_saves_and_reloads(
        self, mock_qdialog, mock_dialog_cls
    ):
        b = _make_bridge()
        toasts = []
        b.toastRequested.connect(lambda t: toasts.append(t))
        dlg = mock_dialog_cls.return_value
        dlg.exec.return_value = mock_qdialog.Accepted
        dlg.pending_changes = {
            "old_script_name": "ok-ww",
            "new_display_name": "鸣潮",
            "config_patch": {"k": "v"},
            "weekly_timeouts": {"1": [1]},
            "weekly_start_day": None,
        }
        with (
            patch.object(b.app_service, "update_script") as mock_update,
            patch.object(b, "_reload_games") as mock_reload,
        ):
            b.configCurrent()
        mock_update.assert_called_once_with(
            "ok-ww", "鸣潮", {"k": "v"}, {"1": [1]}, None
        )
        mock_reload.assert_called_once()
        self.assertTrue(any("已保存" in s for s in toasts))

    def test_weekly_nested_selection_passes_native_child_value(self):
        bridge = _make_bridge()
        name = bridge.games[0]["script_name"]
        with patch.object(app_service, "set_weekly_task_option") as write:
            bridge.selectWeeklyTaskOption("周本", "材料", 2)
        write.assert_called_once_with(name, "周本", "材料", 2)

    @patch("src.gui.dialogs.SingleScriptConfigDialog")
    @patch("PySide6.QtWidgets.QDialog")
    def test_config_current_cancel_does_not_save(self, mock_qdialog, mock_dialog_cls):
        b = _make_bridge()
        dlg = mock_dialog_cls.return_value
        dlg.exec.return_value = mock_qdialog.Rejected  # 取消/关闭
        with (
            patch.object(b.app_service, "update_script") as mock_update,
            patch.object(b, "_reload_games") as mock_reload,
        ):
            b.configCurrent()
        mock_update.assert_not_called()
        mock_reload.assert_not_called()


if __name__ == "__main__":
    unittest.main()
