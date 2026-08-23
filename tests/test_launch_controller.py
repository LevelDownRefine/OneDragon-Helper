"""测试 src/gui/controllers/launch.py：LaunchController 定时运行流程。

验证：非定时立即运行、定时到点重新生成链并运行、生成失败不进入等待。
"""

import os
import unittest
from datetime import datetime
from unittest import mock

# 在导入 PySide6 之前设置 offscreen 平台插件（CI 无显示器环境）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication

from src.gui.controllers.launch import LaunchController


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

    _app = None

    @classmethod
    def setUpClass(cls):
        # QTimer.start() 需要存在一个 QCoreApplication 实例才能激活。
        if QCoreApplication.instance() is None:
            cls._app = QCoreApplication([])

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


if __name__ == "__main__":
    unittest.main()
