"""测试 QmlBridge 任务卡后端（日常副本 / 周常周几）。

复用 test_qml_launcher 的 _make_bridge：用 mock 隔离 config / 壁纸 I/O；is_adapted / daily_task_config.get_weekly_map / get_daily_task_map /
parse_daily_task_config 按用例 patch（task_card 经 AppService 取数，patch 目标指向
真实模块函数），验证 QML 任务卡所需的数据与写回行为。
"""

import unittest
from unittest.mock import MagicMock, patch

from src.gui.controllers import task_card
from src.service import app_service
from tests.test_qml_launcher import _make_bridge


class TestTaskCard(unittest.TestCase):
    """任务卡数据 / 写回：与旧 task_card.py 对齐。"""

    @patch("src.service.app_service.get_daily_task_map", return_value={})
    def test_restore_refreshes_task_properties(self, _map):
        bridge = _make_bridge()
        name = bridge.games[0]["script_name"]
        bridge.task_card._daily_task_options_cache = {
            name: [
                {"name": "每日任务", "options": [{"name": "副本A", "sequences": []}]}
            ]
        }
        changed = MagicMock()
        bridge.taskStateChanged.connect(changed)
        bridge.app_service.restore_backup = MagicMock(
            return_value={"restored": 1, "skipped_scripts": []}
        )
        with (
            patch.object(bridge.backup, "_pick_zip", return_value="backup.zip"),
            patch.object(task_card, "get_daily_readback") as readback,
        ):
            readback.return_value = [
                {"name": "每日任务", "task": "副本A", "sequence": None, "enabled": None}
            ]
            self.assertEqual(bridge.dailyItems[0]["task_label"], "副本A")
            readback.return_value = [
                {"name": "每日任务", "task": "副本B", "sequence": None, "enabled": None}
            ]
            bridge.restoreConfig()
            changed.assert_called_once_with()
            self.assertEqual(bridge.dailyItems[0]["task_label"], "副本B")

    @patch.object(task_card, "is_adapted", return_value=True)
    @patch("src.service.app_service.get_weekly_map", return_value=[{"name": "周常"}])
    @patch.object(app_service, "get_weekly_start", return_value=None)
    @patch("src.service.app_service.get_daily_task_map", return_value={})
    @patch.object(task_card, "get_daily_readback", return_value=[])
    def test_daily_items_default_is_empty(self, *_):
        b = _make_bridge()
        self.assertEqual(b.dailyItems, [])
        self.assertEqual(b.weeklyStartLabel, "选择周几")

    @patch("src.service.app_service.get_daily_task_map", return_value={})
    def test_set_daily_enabled_writes_through_service(self, *_):
        """日常开关经 Bridge → service 落盘（开关无副本名可反查，显式带日常）。"""
        b = _make_bridge()
        name = b.games[0]["script_name"]
        b.app_service.set_script_daily_enabled = MagicMock()
        b.setDailyEnabled("追猎目标", False)
        b.app_service.set_script_daily_enabled.assert_called_once_with(
            name, "追猎目标", False
        )

    @patch.object(task_card, "is_adapted", return_value=False)
    @patch("src.service.app_service.get_daily_task_map", return_value={})
    def test_task_adapted_reflects_is_adapted(self, *_):
        b = _make_bridge()
        self.assertFalse(b.taskAdapted)

    class _AnyMap(dict):
        """get_daily_task_map().get(name) 恒返回 truthy，模拟「该游戏有副本配置」。"""

        def get(self, key, default=None):
            return 1

    @patch.object(task_card, "is_adapted", return_value=True)
    @patch("src.service.app_service.get_daily_task_map", return_value=_AnyMap())
    def test_daily_supported_true_when_task_cfg_present(self, *_):
        b = _make_bridge()
        self.assertTrue(b.dailySupported)

    @patch.object(task_card, "is_adapted", return_value=True)
    @patch("src.service.app_service.get_daily_task_map", return_value={})
    def test_daily_supported_false_when_no_task_cfg(self, *_):
        b = _make_bridge()
        self.assertFalse(b.dailySupported)

    @patch("src.service.app_service.set_config")  # 实时落盘子脚本 config（经 service）
    @patch.object(task_card, "is_adapted", return_value=True)
    @patch("src.service.app_service.get_weekly_map", return_value=[])
    @patch("src.service.app_service.get_daily_task_map", return_value={})
    @patch.object(task_card, "get_daily_readback")
    def test_select_daily_task_writes_config(self, readback, *_):
        b = _make_bridge()
        name = b.games[0]["script_name"]
        # 反读无真相 → chip 回退声明的首个选项
        b.task_card._daily_task_options_cache = {
            name: [
                {"name": "每日任务", "options": [{"name": "副本A", "sequences": []}]}
            ]
        }
        readback.return_value = [
            {"name": "每日任务", "task": None, "sequence": None, "enabled": None}
        ]
        b.selectDailyTask("每日任务", "副本A", "seq1")
        self.assertEqual(b.dailyItems[0]["task_label"], "副本A")
        # 实时落盘子脚本 config（日常副本编辑期即生效，不再依赖运行全体），经 service 入口；
        # 日常名由该行（GUI 手上就有）带出
        app_service.set_config.assert_called_once_with(
            name,
            task_name="副本A",
            sequence="seq1",
            daily_display_name="每日任务",
        )

    @patch("src.service.app_service.get_weekly_map", return_value=[])
    @patch.object(task_card, "is_adapted", return_value=True)
    @patch.object(task_card, "get_daily_readback")
    def test_nte_menu_yields_two_daily_rows(self, readback, *_):
        """多日常（异环形态）：菜单按日常分组 → 两行，且下拉数据按日常取。"""
        menu = {
            "ok-ww": {
                "dailies": [
                    {"name": "异象界域", "tasks": [{"name": "空幕", "sequences": []}]},
                    {
                        "name": "追猎目标",
                        "tasks": [{"name": "追猎目标", "sequences": []}],
                    },
                ]
            }
        }
        readback.return_value = [
            {"name": "异象界域", "task": "空幕", "sequence": None, "enabled": True},
            {
                "name": "追猎目标",
                "task": "追猎目标",
                "sequence": None,
                "enabled": False,
            },
        ]
        with patch("src.service.app_service.get_daily_task_map", return_value=menu):
            b = _make_bridge()
        self.assertEqual(
            [item["name"] for item in b.dailyItems], ["异象界域", "追猎目标"]
        )
        self.assertEqual(
            b.dailyTaskOptions("追猎目标"), [{"name": "追猎目标", "sequences": []}]
        )

    @patch.object(task_card, "is_adapted", return_value=True)
    def test_daily_task_options_shape(self, *_):
        menu = {
            "ok-ww": {
                "dailies": [
                    {
                        "name": "每日任务",
                        "tasks": [
                            {
                                "name": "副本A",
                                "sequences": [{"display": "难1", "value": "s1"}],
                            }
                        ],
                    }
                ]
            }
        }
        with patch("src.service.app_service.get_daily_task_map", return_value=menu):
            b = _make_bridge()
        opts = b.dailyTaskOptions("每日任务")
        self.assertEqual(opts[0]["name"], "副本A")
        self.assertEqual(opts[0]["sequences"], [{"label": "难1", "value": "s1"}])

    @patch("src.service.app_service.get_daily_task_map", return_value={})
    def test_daily_task_options_empty_when_no_cfg(self, *_):
        b = _make_bridge()
        self.assertEqual(b.dailyTaskOptions("每日任务"), [])

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
