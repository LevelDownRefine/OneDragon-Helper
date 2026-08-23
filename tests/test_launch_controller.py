"""测试 src/gui/controllers/launch.py：LaunchController 定时运行流程。

验证：非定时立即运行、定时到点重新生成链并运行、生成失败不进入等待。
"""

import os
import unittest
from datetime import datetime
from unittest import mock

# 在导入 PySide6 之前设置 offscreen 平台插件（CI 无显示器环境）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog

from src.gui.controllers.launch import LaunchController

# widget（RunConfirmDialog）需要一个 QApplication 实例；模块级单例，
# 进程退出时随解释器销毁，避免 per-class 重建导致 offscreen 下挂起。
if QApplication.instance() is None:
    _APP = QApplication([])


def _make_controller(enabled: bool, target_time: str | None):
    """构造 LaunchController，注入 mock 依赖并设置 timed_run 配置。"""
    game_list = mock.MagicMock()
    # launchAll 依赖 game_list.games/enabled 计算启用脚本集合，提供一个启用项。
    game_list.games = [{"script_name": "demo"}]
    game_list.enabled = [True]
    task_card = mock.MagicMock()
    task_card.ui_state = {}
    service = mock.MagicMock()
    service.load_config.return_value = {
        "script_list": [],
        "timed_run": (
            {"enabled": enabled, "target_time": target_time}
            if target_time is not None
            else {"enabled": enabled}
        ),
    }
    toast = mock.MagicMock()
    ctrl = LaunchController(game_list, task_card, service, toast)
    return ctrl, service, toast


class TestLaunchAllTimed(unittest.TestCase):
    """launchAll：定时/非定时分支与 service 调用正确性（定时已下沉 spawn_schedule_run）。"""

    def _run_launch(self, ctrl):
        """让真实 launchAll 跑通到 service 层（不 mock service）。"""
        ctrl._confirm_run = mock.MagicMock(return_value=True)
        ctrl.launchAll()

    def test_not_timed_runs_immediately(self):
        ctrl, service, toast = _make_controller(enabled=False, target_time=None)
        with mock.patch("src.gui.controllers.launch.spawn_schedule_run") as mock_spawn:
            self._run_launch(ctrl)
        # 非定时：也经 spawn_schedule_run 运行（target=now，不等待），
        # 不直连 service.run_chain_once / schedule_run。
        mock_spawn.assert_called_once()
        args = mock_spawn.call_args
        self.assertEqual(args.args[0], {"demo"})  # 启用脚本集合
        self.assertEqual(args.args[1], "now")  # 即时：不等待
        self.assertFalse(args.kwargs["mute"])
        self.assertIsNone(args.kwargs["shutdown_delay"])
        service.run_chain_once.assert_not_called()
        service.schedule_run.assert_not_called()

    def test_timed_spawns_schedule_process(self):
        ctrl, service, toast = _make_controller(enabled=True, target_time="08:00")
        with (
            mock.patch("src.gui.controllers.launch.spawn_schedule_run") as mock_spawn,
            mock.patch(
                "src.gui.controllers.launch.next_target_datetime",
                return_value=datetime(2030, 1, 1, 8, 0),
            ),
        ):
            self._run_launch(ctrl)
        # 定时：不立即运行，起独立控制台进程（spawn_schedule_run），
        # 真实实现在 ChainService.schedule_run 中（独立进程内运行）。
        service.run_chain_once.assert_not_called()
        service.schedule_run.assert_not_called()
        mock_spawn.assert_called_once()
        args = mock_spawn.call_args
        self.assertEqual(args.args[0], {"demo"})  # 启用脚本集合
        self.assertEqual(args.args[1], "08:00")  # 目标时刻
        self.assertFalse(args.kwargs["mute"])
        self.assertIsNone(args.kwargs["shutdown_delay"])

    def test_timed_toast_fires(self):
        """定时：spawn 后立即弹『已设置定时运行』反馈（含目标时刻）。"""
        ctrl, service, toast = _make_controller(enabled=True, target_time="08:00")
        with (
            mock.patch("src.gui.controllers.launch.spawn_schedule_run"),
            mock.patch(
                "src.gui.controllers.launch.next_target_datetime",
                return_value=datetime(2030, 1, 1, 8, 0),
            ),
        ):
            self._run_launch(ctrl)
        toast.assert_called_once()
        self.assertIn("已设置定时运行", toast.call_args[0][0])


class TestConfirmRunDialog(unittest.TestCase):
    """_confirm_run：保留不合法脚本告警，新增自动关机/定时计划回显与写回。"""

    def _make_ctrl(self, config_data):
        """构造 controller，注入 mock 依赖并给定 load_config 返回值。"""
        game_list = mock.MagicMock()
        game_list.games = [{"script_name": "demo"}]
        game_list.enabled = [True]
        task_card = mock.MagicMock()
        task_card.ui_state = {}
        service = mock.MagicMock()
        service.load_config.return_value = config_data
        # 避免 collect_invalid_scripts 默认返回 truthy 的 MagicMock，误触发真实
        # QMessageBox.warning（offscreen 下会阻塞/崩溃）。
        service.collect_invalid_scripts.return_value = []
        toast = mock.MagicMock()
        return LaunchController(game_list, task_card, service, toast), service

    def _patch_run_confirm(self):
        """patch RunConfirmDialog，返回可控的 dialog mock（exec/result）。"""
        return mock.patch("src.gui.controllers.launch.RunConfirmDialog")

    def test_cancel_returns_false(self):
        ctrl, service = self._make_ctrl({"script_list": []})
        with self._patch_run_confirm() as dlg_cls:
            dlg = dlg_cls.return_value
            # exec 返回非 Accepted（模拟 cancel/reject）
            dlg.exec.return_value = QDialog.Rejected
            out = ctrl._confirm_run({"demo"})
        self.assertFalse(out)
        service.save_config.assert_not_called()

    def test_accept_writes_shutdown_and_timed_config(self):
        """确认运行：把弹窗勾选项写回 config.yml（经 service.save_config）。"""
        base = {
            "script_list": [],
            "shutdown": {"after_run": False, "delay_seconds": 0},
            "timed_run": {"enabled": False, "target_time": ""},
        }
        ctrl, service = self._make_ctrl(dict(base))
        with self._patch_run_confirm() as dlg_cls:
            dlg = dlg_cls.return_value
            dlg.exec.return_value = QDialog.Accepted
            dlg.result = {
                "shutdown_enabled": True,
                "shutdown_delay": 120,
                "timed_enabled": True,
                "timed_target": "04:10",
                "mute_enabled": True,
            }
            out = ctrl._confirm_run({"demo"})

        self.assertTrue(out)
        saved = service.save_config.call_args[0][0]
        self.assertEqual(saved["shutdown"], {"after_run": True, "delay_seconds": 120})
        self.assertEqual(saved["timed_run"], {"enabled": True, "target_time": "04:10"})
        self.assertEqual(saved["mute"], {"enabled": True})

    def test_accept_disabled_drops_delay_and_target(self):
        """关闭自动关机/定时：delay 归 0、target 置空，不残留旧值。"""
        base = {
            "script_list": [],
            "shutdown": {"after_run": True, "delay_seconds": 45},
            "timed_run": {"enabled": True, "target_time": "08:00"},
        }
        ctrl, service = self._make_ctrl(dict(base))
        with self._patch_run_confirm() as dlg_cls:
            dlg = dlg_cls.return_value
            dlg.exec.return_value = QDialog.Accepted
            dlg.result = {
                "shutdown_enabled": False,
                "shutdown_delay": 45,  # 关闭后不应写回
                "timed_enabled": False,
                "timed_target": "08:00",  # 关闭后不应写回
                "mute_enabled": False,
            }
            ctrl._confirm_run({"demo"})

        saved = service.save_config.call_args[0][0]
        self.assertEqual(saved["shutdown"], {"after_run": False, "delay_seconds": 0})
        self.assertEqual(saved["timed_run"], {"enabled": False, "target_time": ""})
        self.assertEqual(saved["mute"], {"enabled": False})


if __name__ == "__main__":
    unittest.main()
