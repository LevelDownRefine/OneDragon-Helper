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
from src.service.schedule import RunOptions

# widget（RunConfirmDialog）需要一个 QApplication 实例；模块级单例，
# 进程退出时随解释器销毁，避免 per-class 重建导致 offscreen 下挂起。
if QApplication.instance() is None:
    _APP = QApplication([])


def _make_controller(enabled: bool, target_time: str | None):
    """构造 LaunchController，注入 mock 依赖并设置 timed_run 选项。"""
    game_list = mock.MagicMock()
    # launchAll 依赖 game_list.games/enabled 计算启用脚本集合，提供一个启用项。
    game_list.games = [{"script_name": "demo"}]
    game_list.enabled = [True]
    task_card = mock.MagicMock()
    service = mock.MagicMock()
    service.load_config.return_value = {"script_list": []}
    # launchAll 经 load_run_options 读取运行选项（RunOptions 为单一 schema）。
    service.load_run_options.return_value = RunOptions(
        timed_enabled=enabled,
        timed_target=target_time if target_time is not None else "",
    )
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
        self.assertFalse(args.kwargs["unmute"])
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
        self.assertFalse(args.kwargs["unmute"])
        self.assertIsNone(args.kwargs["shutdown_delay"])

    def test_spawn_failure_toasts_error(self):
        """起进程失败（spawn 返回 None）：报失败引导看日志，不报成功。"""
        ctrl, service, toast = _make_controller(enabled=False, target_time=None)
        ctrl._confirm_run = mock.MagicMock(return_value=True)
        with mock.patch(
            "src.gui.controllers.launch.spawn_schedule_run", return_value=None
        ) as mock_spawn:
            ctrl.launchAll()
        mock_spawn.assert_called_once()
        self.assertTrue(any("启动失败" in c[0][0] for c in toast.call_args_list))

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
    """_confirm_run：不合法脚本告警 + 回显当前运行选项 + 勾选项整体经 service 落盘。

    选项的合并写回与授权码注册已下沉 src.service.schedule（RunOptions 单一 schema），
    行为由 test_schedule.TestLoadRunOptions / TestApplyRunOptions 覆盖；此处只钉
    「控制器透传 RunOptions、取消不落盘、回显初始值」三个契约。
    """

    def _make_ctrl(self, options: RunOptions | None = None):
        """构造 controller，注入 mock 依赖（load_run_options 可指定回显值）。"""
        game_list = mock.MagicMock()
        game_list.games = [{"script_name": "demo"}]
        game_list.enabled = [True]
        task_card = mock.MagicMock()
        service = mock.MagicMock()
        service.load_config.return_value = {"script_list": []}
        service.load_run_options.return_value = options or RunOptions()
        # 避免 collect_invalid_scripts 默认返回 truthy 的 MagicMock，误触发真实
        # QMessageBox.warning（offscreen 下会阻塞/崩溃）。
        service.collect_invalid_scripts.return_value = []
        toast = mock.MagicMock()
        return LaunchController(game_list, task_card, service, toast), service

    def _patch_run_confirm(self):
        """patch RunConfirmDialog，返回可控的 dialog mock（exec/result）。"""
        return mock.patch("src.gui.controllers.launch.RunConfirmDialog")

    def test_cancel_returns_false(self):
        ctrl, service = self._make_ctrl()
        with self._patch_run_confirm() as dlg_cls:
            dlg = dlg_cls.return_value
            # exec 返回非 Accepted（模拟 cancel/reject）
            dlg.exec.return_value = QDialog.Rejected
            out = ctrl._confirm_run({"demo"})
        self.assertFalse(out)
        service.apply_run_options.assert_not_called()

    def test_accept_forwards_result_to_service(self):
        """确认运行：弹窗 result（RunOptions）整体透传 service.apply_run_options。"""
        res = RunOptions(shutdown_enabled=True, shutdown_delay=120)
        ctrl, service = self._make_ctrl()
        with self._patch_run_confirm() as dlg_cls:
            dlg = dlg_cls.return_value
            dlg.exec.return_value = QDialog.Accepted
            dlg.result = res
            out = ctrl._confirm_run({"demo"})

        self.assertTrue(out)
        service.apply_run_options.assert_called_once_with(res)

    def test_accept_echoes_current_options_to_dialog(self):
        """确认弹窗以 load_run_options 的当前值初始化（含关闭时的延迟数值回显）。"""
        options = RunOptions(
            shutdown_enabled=True,
            shutdown_delay=45,
            timed_enabled=True,
            timed_target="08:00",
        )
        ctrl, _service = self._make_ctrl(options)
        with self._patch_run_confirm() as dlg_cls:
            dlg = dlg_cls.return_value
            dlg.exec.return_value = QDialog.Rejected
            ctrl._confirm_run({"demo"})
        dlg_cls.assert_called_once()
        self.assertEqual(dlg_cls.call_args.args[0], 1)  # 启用脚本数
        self.assertIs(dlg_cls.call_args.args[1], options)  # 回显原对象


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
        self.assertFalse(args.kwargs["unmute"])
        self.assertIsNone(args.kwargs["shutdown_delay"])
        toast.assert_called_once()
        self.assertIn("启动全部", toast.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
