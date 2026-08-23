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
    """launchAll：定时/非定时分支与 service 调用正确性（调度核心已下沉 service）。"""

    def _run_launch(self, ctrl):
        """让真实 launchAll 跑通到 service 层（不 mock service）。"""
        ctrl._confirm_run = mock.MagicMock(return_value=True)
        ctrl.launchAll()

    def test_not_timed_runs_immediately(self):
        ctrl, service, toast = _make_controller(enabled=False, target_time=None)
        self._run_launch(ctrl)
        # 非定时：直接经 service.run_chain_once 运行，不委托定时调度
        service.run_chain_once.assert_called_once()
        service.schedule_run.assert_not_called()

    def test_timed_delegates_to_service(self):
        ctrl, service, toast = _make_controller(enabled=True, target_time="08:00")
        self._run_launch(ctrl)
        # 定时：不立即运行，改委托 service.schedule_run
        # （带启动快照 keys / 目标时刻 / 关机 / 静音 / 回调）
        service.run_chain_once.assert_not_called()
        service.schedule_run.assert_called_once()
        args = service.schedule_run.call_args
        self.assertEqual(args.args[0], {"demo"})  # 快照 enabled_keys
        self.assertEqual(args.args[1], "08:00")  # 目标时刻
        self.assertIsNone(args.kwargs["shutdown"])
        self.assertFalse(args.kwargs["mute"])
        self.assertIsNotNone(args.kwargs["on_set"])
        self.assertIsNotNone(args.kwargs["post_run"])

    def test_timed_on_set_fires_gui_toast(self):
        """定时委托时 on_set 回调收到目标 datetime，驱动 GUI『已设置定时』反馈。"""
        ctrl, service, toast = _make_controller(enabled=True, target_time="08:00")

        def _capture(enabled_keys, target_time, *, shutdown, mute, on_set, post_run):
            on_set(datetime(2030, 1, 1, 8, 0))
            return mock.MagicMock()

        service.schedule_run.side_effect = _capture
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
