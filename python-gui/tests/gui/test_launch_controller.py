"""测试 src/gui/controllers/launch.py：LaunchController 手动运行流程。

「启动全部」与 Rust 前端同一协议：run.view（校验回显）→ run.prepare /
run.saved（独立运行命令，选项经 stdin 交付）→ RunStarter 启动。验证：
确认流（告警 / 回显 / 选项经 prepare_run 落盘）、无人值守直启、名单失效
提示与启动失败反馈。
"""

import os
import unittest
from dataclasses import asdict
from unittest import mock

# 在导入 PySide6 之前设置 offscreen 平台插件（CI 无显示器环境）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from gui.controllers.launch import LaunchController
from src.service.chain_service import InvalidRunRequest
from src.service.schedule import RunOptions

# widget（RunConfirmDialog）需要一个 QApplication 实例；模块级单例，
# 进程退出时随解释器销毁，避免 per-class 重建导致 offscreen 下挂起。
if QApplication.instance() is None:
    _APP = QApplication([])


def _target(name="demo"):
    return {
        "kind": "command",
        "program": "python",
        "args": ["run"],
        "cwd": "cwd",
        "env": {},
        "console": True,
        "input": f'{{"script_names": ["{name}"]}}',
    }


def _make_controller():
    """构造 LaunchController，注入 mock 依赖与运行视图。"""
    game_list = mock.MagicMock()
    # launchAll 依赖 game_list.games/enabled 计算启用脚本集合，提供一个启用项。
    game_list.games = [{"script_name": "demo"}]
    game_list.enabled = [True]
    task_card = mock.MagicMock()
    service = mock.MagicMock()
    service.run_view.return_value = {
        "script_names": ["demo"],
        "invalid": [],
        "options": _options_dict(),
    }
    toast = mock.MagicMock()
    ctrl = LaunchController(game_list, task_card, service, toast)
    return ctrl, service, toast


def _options_dict():
    return asdict(RunOptions())


class TestLaunchAllUnattended(unittest.TestCase):
    """launchAll(confirm=False)：跳过确认，按上次选项经 saved_run 直启。"""

    def test_unattended_starts_saved_target(self):
        ctrl, service, toast = _make_controller()
        service.saved_run.return_value = _target()
        with (
            mock.patch.object(ctrl, "_confirm_and_prepare") as confirm,
            mock.patch.object(ctrl._starter, "start") as start,
        ):
            ctrl.launchAll(confirm=False)
        confirm.assert_not_called()
        service.saved_run.assert_called_once_with(["demo"])
        start.assert_called_once_with(_target())
        toast.assert_not_called()  # 启动成功回执走 started 信号

    def test_invalid_selection_toasts(self):
        """名单失效（脚本被移除）→ 提示后不启动。"""
        ctrl, service, toast = _make_controller()
        service.saved_run.side_effect = InvalidRunRequest("脚本不存在: demo")
        with mock.patch.object(ctrl._starter, "start") as start:
            ctrl.launchAll(confirm=False)
        start.assert_not_called()
        toast.assert_called_once_with("脚本不存在: demo")

    def test_empty_selection_toasts(self):
        ctrl, service, toast = _make_controller()
        ctrl._game_list.enabled = [False]
        with mock.patch.object(ctrl._starter, "start") as start:
            ctrl.launchAll(confirm=False)
        start.assert_not_called()
        toast.assert_called_once_with("没有勾选手动运行的脚本")

    def test_starter_failure_toasts(self):
        """交付失败经 RunStarter.failed 信号回报 → toast。"""
        ctrl, _service, toast = _make_controller()
        ctrl._failed_start("运行配置交付超时")
        toast.assert_called_once_with("运行配置交付超时")

    def test_started_toasts(self):
        ctrl, _service, toast = _make_controller()
        ctrl._started()
        toast.assert_called_once_with("手动运行：已在独立控制台启动，关闭控制台即取消")


class TestConfirmAndPrepare(unittest.TestCase):
    """确认流：run.view 回显 → 弹窗 → 选项经 prepare_run 落盘并取运行命令。"""

    def _ctrl(self, invalid, options=None):
        ctrl, service, _toast = _make_controller()
        service.run_view.return_value = {
            "script_names": ["demo"],
            "invalid": invalid,
            "options": asdict(options) if options is not None else _options_dict(),
        }
        return ctrl, service

    def _patch_dialog(self):
        return mock.patch("gui.controllers.launch.RunConfirmDialog")

    def test_cancel_returns_none_without_prepare(self):
        ctrl, service = self._ctrl([])
        with self._patch_dialog() as dlg_cls:
            dlg_cls.return_value.exec.return_value = QDialog.Rejected
            self.assertIsNone(ctrl._confirm_and_prepare({"demo"}))
        service.prepare_run.assert_not_called()

    def test_accept_forwards_options_to_prepare_run(self):
        """确认：弹窗选项整体经 prepare_run 落盘，confirm_invalid 随告警传递。"""
        res = RunOptions(shutdown_enabled=True, shutdown_delay=120)
        ctrl, service = self._ctrl([{"name": "demo", "reason": "exe 不存在"}])
        with (
            mock.patch("gui.controllers.launch.styled_msg_box") as msg_cls,
            self._patch_dialog() as dlg_cls,
        ):
            msg_cls.return_value.exec.return_value = QMessageBox.Yes
            dlg = dlg_cls.return_value
            dlg.exec.return_value = QDialog.Accepted
            dlg.run_options = res
            out = ctrl._confirm_and_prepare({"demo"})
        service.prepare_run.assert_called_once_with(["demo"], res, confirm_invalid=True)
        self.assertEqual(out, service.prepare_run.return_value)

    def test_invalid_warning_yes_continues(self):
        """有不合法脚本：先告警，Yes 才进确认弹窗。"""
        ctrl, _service = self._ctrl([{"name": "demo", "reason": "exe 不存在"}])
        with (
            mock.patch("gui.controllers.launch.styled_msg_box") as msg_cls,
            self._patch_dialog() as dlg_cls,
        ):
            msg_cls.return_value.exec.return_value = QMessageBox.Yes
            dlg_cls.return_value.exec.return_value = QDialog.Rejected
            ctrl._confirm_and_prepare({"demo"})
        dlg_cls.assert_called_once()

    def test_invalid_warning_no_cancels(self):
        ctrl, service = self._ctrl([{"name": "demo", "reason": "exe 不存在"}])
        with (
            mock.patch("gui.controllers.launch.styled_msg_box") as msg_cls,
            self._patch_dialog() as dlg_cls,
        ):
            msg_cls.return_value.exec.return_value = QMessageBox.No
            self.assertIsNone(ctrl._confirm_and_prepare({"demo"}))
        dlg_cls.assert_not_called()
        service.prepare_run.assert_not_called()

    def test_no_invalid_skips_warning(self):
        ctrl, _service = self._ctrl([])
        with (
            mock.patch("gui.controllers.launch.styled_msg_box") as msg_cls,
            self._patch_dialog() as dlg_cls,
        ):
            dlg_cls.return_value.exec.return_value = QDialog.Rejected
            ctrl._confirm_and_prepare({"demo"})
        msg_cls.assert_not_called()

    def test_accept_echoes_saved_options_to_dialog(self):
        """确认弹窗以 run_view 的当前值初始化（含关闭时的延迟数值回显）。"""
        options = RunOptions(shutdown_enabled=True, shutdown_delay=45)
        ctrl, _service = self._ctrl([], options)
        with self._patch_dialog() as dlg_cls:
            dlg_cls.return_value.exec.return_value = QDialog.Rejected
            ctrl._confirm_and_prepare({"demo"})
        dlg_cls.assert_called_once()
        self.assertEqual(dlg_cls.call_args.args[0], 1)  # 启用脚本数
        self.assertEqual(dlg_cls.call_args.args[1].shutdown_delay, 45)  # 回显


if __name__ == "__main__":
    unittest.main()
