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
    service = mock.MagicMock()
    service.load_config.return_value = {"script_list": []}
    service.load_schedule.return_value = {
        "timed_run": (
            {"enabled": enabled, "target_time": target_time}
            if target_time is not None
            else {"enabled": enabled}
        )
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
        # 真实实现在 chain_service.schedule_run 中（独立进程内运行）。
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
        self.assertIn("定时运行", toast.call_args[0][0])


class TestConfirmRunDialog(unittest.TestCase):
    """_confirm_run：不合法脚本告警 + 回显当前 schedule 配置 + 勾选项整体经 service 落盘。

    勾选项的合并写回（shutdown/timed/mute/... → schedule.yml）与授权码注册已下沉
    src.service.schedule.apply_run_options，其行为由 test_schedule.TestApplyRunOptions
    覆盖；此处只钉「控制器透传 result、取消不落盘、回显初始值」三个契约。
    """

    def _make_ctrl(self, config_data):
        """构造 controller，注入 mock 依赖。

        调度参数（shutdown/timed_run/mute/rerun/notify）已迁入 schedule.yml，
        经 ``load_schedule`` 读取；脚本链声明（script_list）仍经 ``load_config`` 读取。
        """
        game_list = mock.MagicMock()
        game_list.games = [{"script_name": "demo"}]
        game_list.enabled = [True]
        task_card = mock.MagicMock()
        service = mock.MagicMock()
        # script_list 留在 config；其余调度块归 schedule。
        schedule_keys = {
            "shutdown",
            "timed_run",
            "mute",
            "close_running",
            "rerun",
            "notify",
        }
        service.load_config.return_value = {
            "script_list": config_data.get("script_list", [])
        }
        service.load_schedule.return_value = {
            k: v for k, v in config_data.items() if k in schedule_keys
        }
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
        service.apply_run_options.assert_not_called()

    def test_accept_forwards_result_to_service(self):
        """确认运行：result dict 整体透传 service.apply_run_options（合并写回归 service）。"""
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
                "close_running_enabled": True,
                "rerun_enabled": True,
                "notify_enabled": True,
                "email": "123456@qq.com",
                "auth_code": "",
                "smtp_host": "",
                "smtp_port": "",
            }
            out = ctrl._confirm_run({"demo"})

        self.assertTrue(out)
        service.apply_run_options.assert_called_once_with(dlg.result)

    def test_accept_echoes_current_schedule_to_dialog(self):
        """确认弹窗以 schedule.yml 当前值初始化（含关闭时的延迟数值回显）。"""
        base = {
            "script_list": [],
            "shutdown": {"after_run": True, "delay_seconds": 45},
            "timed_run": {"enabled": True, "target_time": "08:00"},
        }
        ctrl, _service = self._make_ctrl(dict(base))
        with self._patch_run_confirm() as dlg_cls:
            dlg = dlg_cls.return_value
            dlg.exec.return_value = QDialog.Rejected
            ctrl._confirm_run({"demo"})
        kwargs = dlg_cls.call_args[1]
        self.assertTrue(kwargs["shutdown_enabled"])
        self.assertEqual(kwargs["shutdown_delay"], 45)
        self.assertTrue(kwargs["timed_enabled"])
        self.assertEqual(kwargs["timed_target"], "08:00")


class TestLaunchAllUnattended(unittest.TestCase):
    """launchAll(confirm=False)：跳过运行前确认窗，按上次配置直接启动全部。"""

    def test_unattended_skips_confirm_and_spawns(self):
        ctrl, service, toast = _make_controller(enabled=False, target_time=None)
        # 无人值守：确认窗不应被弹出（不告警、不回显调度配置）。
        ctrl._confirm_run = mock.MagicMock()
        with mock.patch("src.gui.controllers.launch.spawn_schedule_run") as mock_spawn:
            ctrl.launchAll(confirm=False)
        ctrl._confirm_run.assert_not_called()
        # 仍按上次配置经 spawn_schedule_run 启动（即时、无 special 参数）。
        mock_spawn.assert_called_once()
        args = mock_spawn.call_args
        self.assertEqual(args.args[0], {"demo"})
        self.assertEqual(args.args[1], "now")
        self.assertFalse(args.kwargs["mute"])
        self.assertIsNone(args.kwargs["shutdown_delay"])
        toast.assert_called_once()
        self.assertIn("启动全部", toast.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
