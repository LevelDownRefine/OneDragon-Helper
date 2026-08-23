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

# widget（RunConfirmDialog）/ QTimer 需要一个 QApplication 实例；模块级单例，
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
    """launchAll：定时/非定时分支与外部进程触发正确性。"""

    def _patch_launch(self, ctrl):
        """统一 patch launchAll 内的依赖：确认/生成链/运行链。"""
        return mock.patch.multiple(
            ctrl,
            _confirm_run=mock.DEFAULT,
            _generate_chain=mock.DEFAULT,
            _run_chain=mock.DEFAULT,
        )

    def test_not_timed_runs_immediately(self):
        ctrl, service, toast = _make_controller(enabled=False, target_time=None)
        with self._patch_launch(ctrl) as m:
            m["_confirm_run"].return_value = True
            m["_generate_chain"].return_value = "config/script_chain/01.yml"
            ctrl.launchAll()
            gen, run = m["_generate_chain"], m["_run_chain"]

        # 只生成一次（校验性），立即运行，定时器未启动
        self.assertEqual(gen.call_count, 1)
        run.assert_called_once()
        self.assertFalse(ctrl._timed_timer.isActive())

    def test_timed_starts_timer_and_regenerates_on_tick(self):
        ctrl, service, toast = _make_controller(enabled=True, target_time="08:00")
        with self._patch_launch(ctrl) as m:
            m["_confirm_run"].return_value = True
            m["_generate_chain"].return_value = "config/script_chain/01.yml"
            ctrl.launchAll()
            gen, run = m["_generate_chain"], m["_run_chain"]

            # 进入等待：生成一次（校验）+ 启动定时器，但未立即运行
            self.assertEqual(gen.call_count, 1)
            run.assert_not_called()
            self.assertTrue(ctrl._timed_timer.isActive())

            # 模拟到点：注入一个明确的过去时刻，手动触发 tick（仍在 patch 上下文内）
            ctrl._timed_target = datetime(2000, 1, 1, 0, 0)
            ctrl._on_timed_tick()

            # 到点后重新生成（第 2 次，按当时星期重挑脚本）+ 运行，定时器停止
            self.assertEqual(gen.call_count, 2)
            run.assert_called_once()
            self.assertFalse(ctrl._timed_timer.isActive())

    def test_generate_failure_blocks_wait(self):
        ctrl, service, toast = _make_controller(enabled=True, target_time="08:00")
        with self._patch_launch(ctrl) as m:
            m["_confirm_run"].return_value = True
            m["_generate_chain"].side_effect = RuntimeError("boom")
            ctrl.launchAll()
            run = m["_run_chain"]

        # 生成失败：不运行、不进入定时调度、给出反馈
        run.assert_not_called()
        toast.assert_called_once()
        self.assertIn("生成脚本链失败", toast.call_args[0][0])
        self.assertFalse(ctrl._timed_timer.isActive())

    def test_timed_regenerates_today_yml_on_tick(self):
        """定时到点重新生成 today.yml（而非复用启动时的链文件）。"""
        ctrl, service, toast = _make_controller(enabled=True, target_time="08:00")
        with self._patch_launch(ctrl) as m:
            m["_confirm_run"].return_value = True
            m["_generate_chain"].side_effect = [
                "config/script_chain/01.yml",  # 启动时校验性生成
                "config/script_chain/today.yml",  # 到点重新生成
            ]
            ctrl.launchAll()
            gen, run = m["_generate_chain"], m["_run_chain"]

            ctrl._timed_target = datetime(2000, 1, 1, 0, 0)
            ctrl._on_timed_tick()

        # 到点调用应传入 today.yml 输出（chain_name 默认 today），而非 01.yml
        self.assertEqual(gen.call_count, 2)
        run.assert_called_once_with(
            "config/script_chain/today.yml", {"demo"}, "定时运行"
        )

    def test_real_generate_chain_called_with_one_arg(self):
        """launchAll 必须以单参调用 _generate_chain（回归 64 行传错 2 参的 TypeError）。

        不 mock _generate_chain，让真实方法跑通到 self._service.generate_chain；
        若签名再写错（如 _generate_chain(config_data, keys)），本用例立即 TypeError。
        _run_chain 仍要 mock 掉，避免真 subprocess.Popen。
        """
        ctrl, service, toast = _make_controller(enabled=False, target_time=None)
        service.generate_chain.return_value = "config/script_chain/today.yml"
        with mock.patch.object(ctrl, "_run_chain") as run:
            ctrl._confirm_run = mock.MagicMock(return_value=True)
            ctrl.launchAll()
        # _service.generate_chain 真实被调用，_run_chain 被 mock
        service.generate_chain.assert_called_once()
        run.assert_called_once_with(
            "config/script_chain/today.yml", {"demo"}, "启动全部"
        )


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


class TestRunChainMute(unittest.TestCase):
    """_run_chain：运行中静音仅做参数转发，把 mute 意图拼成 runner 的 --mute。

    静音执行已下沉 runner（run_chain(mute=...)），主仓不再触碰音频 API、
    不再起守护线程；本类验证「mute 配置 -> 命令行参数」这一薄封装层。
    """

    def _make_ctrl(self, config_data):
        game_list = mock.MagicMock()
        game_list.games = [{"script_name": "demo"}]
        game_list.enabled = [True]
        task_card = mock.MagicMock()
        task_card.ui_state = {}
        service = mock.MagicMock()
        service.load_config.return_value = config_data
        toast = mock.MagicMock()
        return LaunchController(game_list, task_card, service, toast), service

    def test_mute_enabled_passes_flag(self):
        """mute.enabled=True：runner 命令含 --mute。"""
        ctrl, service = self._make_ctrl({"script_list": [], "mute": {"enabled": True}})
        with mock.patch("src.gui.controllers.launch.subprocess.Popen") as popen:
            ctrl._run_chain("config/script_chain/today.yml", {"demo"}, "启动全部")
            cmd = popen.call_args[0][0]
        self.assertIn("--mute", cmd)
        self.assertIn("--chain", cmd)

    def test_mute_disabled_omits_flag(self):
        """mute.enabled=False：runner 命令不含 --mute。"""
        ctrl, service = self._make_ctrl({"script_list": [], "mute": {"enabled": False}})
        with mock.patch("src.gui.controllers.launch.subprocess.Popen") as popen:
            ctrl._run_chain("config/script_chain/today.yml", {"demo"}, "启动全部")
            cmd = popen.call_args[0][0]
        self.assertNotIn("--mute", cmd)

    def test_shutdown_and_mute_flags_coexist(self):
        """shutdown 与 mute 同时启用：命令同时含 --shutdown N 与 --mute。"""
        ctrl, service = self._make_ctrl(
            {
                "script_list": [],
                "shutdown": {"after_run": True, "delay_seconds": 60},
                "mute": {"enabled": True},
            }
        )
        with mock.patch("src.gui.controllers.launch.subprocess.Popen") as popen:
            ctrl._run_chain("config/script_chain/today.yml", {"demo"}, "启动全部")
            cmd = popen.call_args[0][0]
        self.assertIn("--shutdown", cmd)
        self.assertIn("60", cmd)
        self.assertIn("--mute", cmd)


if __name__ == "__main__":
    unittest.main()
