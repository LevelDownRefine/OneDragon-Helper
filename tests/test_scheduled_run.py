"""测试 src/service/scheduled_run.py：定时等待期应有即时状态日志。

核心回归：定时计划设置后、等待到点前，必须立即输出日志说明「正在等待至 XX:XX」，
避免等待期间静默无日志（用户无法判断进程是否在运行）。
"""

import unittest
from unittest import mock

from src.service.chain_service import ChainService
from src.service.scheduled_run import (
    ScheduledRun,
    build_close_running_pipeline,
    build_pre_run_pipeline,
    build_subscript_config_pipeline,
)


class TestPreRunWaitLogs(unittest.TestCase):
    """build_pre_run_pipeline：定时模式的等待 step 立即打日志、不静默。"""

    def test_wait_step_emits_log_before_sleeping(self):
        # 让目标时刻恒为「未来」，进入等待分支打印「将等待至」；time.sleep 被 mock
        # 掉避免真实长睡，随后仍打印「已到达」。验证等待期不再静默。
        future = __import__("datetime").datetime(2099, 1, 1, 0, 0)
        with (
            mock.patch(
                "src.service.scheduled_run.next_target_datetime", return_value=future
            ),
            mock.patch("src.service.scheduled_run.time.sleep") as mock_sleep,
            self.assertLogs("src.service.scheduled_run", level="INFO") as cm,
        ):
            steps = build_pre_run_pipeline(target_time="00:00")
            # 定时模式应含一个等待 step（此处 mute=False，仅 _wait）。
            self.assertTrue(steps, "定时模式应产出至少一个等待 step")
            for step in steps:
                step()

        # 未真正沉睡（sleep 被 mock 替换）。
        mock_sleep.assert_called_once()
        # 关键断言：等待前/到点均有状态日志，而非静默。
        joined = "\n".join(cm.output)
        self.assertIn("定时运行已设置", joined)
        self.assertIn("已到达目标时刻", joined)

    def test_now_mode_has_no_wait_step(self):
        # 即时运行（target=now）：不应有等待 step，也就不会打等待日志。
        steps = build_pre_run_pipeline(target_time="now")
        self.assertEqual(steps, [])


class TestBuildSubscriptConfigPipeline(unittest.TestCase):
    """build_subscript_config_pipeline：运行前把 weekly_start 写回各子脚本 config。

    原内联于 generate_chain_config 的 set_config(weekly_start=...) 已抽出到此；
    即时/定时两条路径统一经 ScheduledRun，故一次应用即覆盖。
    """

    def test_applies_weekly_start_per_enabled_script(self):
        weekly_start_map = {"A": 3, "B": 4}
        with mock.patch("src.service.scheduled_run.set_config") as mock_set:
            steps = build_subscript_config_pipeline({"A", "B"}, weekly_start_map)
            self.assertEqual(len(steps), 1)
            steps[0]()  # 执行 step
        mock_set.assert_any_call("A", weekly_start=3)
        mock_set.assert_any_call("B", weekly_start=4)

    def test_missing_from_map_passes_none(self):
        # 未设周常起始日的脚本：weekly_start=None 透传（由 set_config 内部跳过）。
        with mock.patch("src.service.scheduled_run.set_config") as mock_set:
            steps = build_subscript_config_pipeline({"A", "C"}, {"A": 2})
            steps[0]()
        mock_set.assert_any_call("A", weekly_start=2)
        mock_set.assert_any_call("C", weekly_start=None)

    def test_empty_keys_returns_no_steps(self):
        # 无启用脚本：不写盘、不产生 step。
        with mock.patch("src.service.scheduled_run.set_config") as mock_set:
            steps = build_subscript_config_pipeline(set(), {})
        self.assertEqual(steps, [])
        mock_set.assert_not_called()


class TestBuildCloseRunningPipeline(unittest.TestCase):
    """build_close_running_pipeline：运行前关闭残留脚本/游戏进程。"""

    def test_empty_scripts_returns_no_steps(self):
        self.assertEqual(build_close_running_pipeline([]), [])

    def test_step_kills_collected_names(self):
        scripts = [
            {
                "display_name": "A",
                "script_process_name": "ABot.exe",
                "game_process_name": "AGame.exe",
            },
        ]
        with mock.patch(
            "src.service.scheduled_run.kill_processes_by_names"
        ) as mock_kill:
            steps = build_close_running_pipeline(scripts)
            self.assertEqual(len(steps), 1)
            steps[0]()  # 执行 step
        mock_kill.assert_called_once_with(["ABot.exe", "AGame.exe"])

    def test_no_names_script_skips_kill(self):
        scripts = [{"display_name": "A"}]
        with mock.patch(
            "src.service.scheduled_run.kill_processes_by_names"
        ) as mock_kill:
            steps = build_close_running_pipeline(scripts)
            steps[0]()
        mock_kill.assert_not_called()


class TestPreRunOrder(unittest.TestCase):
    """ScheduledRun.pre_run 组装顺序：关闭残留 → 写子脚本 config → 等待+静音。"""

    def _make_service(self, script_list):
        svc = ChainService()
        svc.load_config = mock.MagicMock(return_value={"script_list": script_list})
        svc.load_schedule = mock.MagicMock(
            return_value={"rerun": {"enabled": True}, "notify": {"enabled": False}}
        )
        svc.get_weekly_start_map = mock.MagicMock(return_value={})
        return svc

    def test_close_before_config_before_wait(self):
        svc = self._make_service([{"display_name": "demo"}])
        close_step = object()
        config_step = object()
        pre_step = object()
        with (
            mock.patch(
                "src.service.scheduled_run.build_close_running_pipeline",
                return_value=[close_step],
            ),
            mock.patch(
                "src.service.scheduled_run.build_subscript_config_pipeline",
                return_value=[config_step],
            ),
            mock.patch(
                "src.service.scheduled_run.build_pre_run_pipeline",
                return_value=[pre_step],
            ),
        ):
            run = ScheduledRun(svc, {"demo"}, "08:00")
        self.assertEqual(run.pre_run, [close_step, config_step, pre_step])


if __name__ == "__main__":
    unittest.main()
