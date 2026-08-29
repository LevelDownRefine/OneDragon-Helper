"""测试 src/service/scheduled_run.py：定时等待期应有即时状态日志。

核心回归：定时计划设置后、等待到点前，必须立即输出日志说明「正在等待至 XX:XX」，
避免等待期间静默无日志（用户无法判断进程是否在运行）。
"""

import unittest
from unittest import mock

from src.service.scheduled_run import ScheduledRun, build_pre_run_pipeline
from src.utils_runner import ProcessTarget


class TestPreRunWaitLogs(unittest.TestCase):
    """build_pre_run_pipeline：定时模式的等待 step 立即打日志、不静默。"""

    def test_wait_step_emits_log_before_sleeping(self):
        # 让目标时刻恒为「未来」，进入等待分支打印「将等待至」；time.sleep 被 mock
        # 掉避免真实长睡，随后仍打印「已到达」。验证等待期不再静默。
        future = __import__("datetime").datetime(2099, 1, 1, 0, 0)
        with (
            mock.patch(
                "src.service.run_actions.next_target_datetime", return_value=future
            ),
            mock.patch("src.service.run_actions.time.sleep") as mock_sleep,
            self.assertLogs("src.service.run_actions", level="INFO") as cm,
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


class TestBuildPreRunWriteConfig(unittest.TestCase):
    """build_pre_run_pipeline 的写子脚本 config step：把 weekly_start 写回各子脚本 config。

    原内联于 generate_chain_config 的 set_config(weekly_start=...) 已并入单一工厂；
    即时/定时两条路径统一经 ScheduledRun，故一次应用即覆盖。
    """

    def test_applies_weekly_start_per_enabled_script(self):
        weekly_start_map = {"A": 3, "B": 4}
        with mock.patch("src.service.run_actions.set_config") as mock_set:
            # target=now / close_running=False → 仅产生写 config step
            steps = build_pre_run_pipeline(
                target_time="now",
                enabled_keys={"A", "B"},
                weekly_start_map=weekly_start_map,
            )
            self.assertEqual(len(steps), 1)
            steps[0]()  # 执行 step
        mock_set.assert_any_call("A", weekly_start=3)
        mock_set.assert_any_call("B", weekly_start=4)

    def test_missing_from_map_passes_none(self):
        # 未设周常起始日的脚本：weekly_start=None 透传（由 set_config 内部跳过）。
        with mock.patch("src.service.run_actions.set_config") as mock_set:
            steps = build_pre_run_pipeline(
                target_time="now", enabled_keys={"A", "C"}, weekly_start_map={"A": 2}
            )
            steps[0]()
        mock_set.assert_any_call("A", weekly_start=2)
        mock_set.assert_any_call("C", weekly_start=None)

    def test_empty_keys_returns_no_steps(self):
        # 无启用脚本：不写盘、不产生 step。
        with mock.patch("src.service.run_actions.set_config") as mock_set:
            steps = build_pre_run_pipeline(target_time="now", enabled_keys=set())
        self.assertEqual(steps, [])
        mock_set.assert_not_called()


class TestBuildPreRunClose(unittest.TestCase):
    """build_pre_run_pipeline 的关闭残留进程 step（受 close_running 控制）。"""

    def test_empty_scripts_returns_no_steps(self):
        steps = build_pre_run_pipeline(
            target_time="now", scripts=[], close_running=True
        )
        self.assertEqual(steps, [])

    def test_step_kills_collected_targets(self):
        scripts = [
            {
                "display_name": "A",
                "script_process_name": "ABot.exe",
                "game_process_name": "AGame.exe",
            },
        ]
        with mock.patch("src.service.run_actions.kill_processes") as mock_kill:
            steps = build_pre_run_pipeline(
                target_time="now", scripts=scripts, close_running=True
            )
            self.assertEqual(len(steps), 1)
            steps[0]()  # 执行 step
        mock_kill.assert_called_once_with(
            [ProcessTarget(name="ABot.exe"), ProcessTarget(name="AGame.exe")]
        )

    def test_no_names_script_skips_kill(self):
        scripts = [{"display_name": "A"}]
        with mock.patch("src.service.run_actions.kill_processes") as mock_kill:
            steps = build_pre_run_pipeline(
                target_time="now", scripts=scripts, close_running=True
            )
            steps[0]()
        mock_kill.assert_not_called()

    def test_close_running_false_excludes_close_step(self):
        # close_running=False：即便给了 enabled_scripts 也不产生关闭 step。
        scripts = [{"display_name": "A", "script_process_name": "ABot.exe"}]
        with mock.patch("src.service.run_actions.kill_processes") as mock_kill:
            steps = build_pre_run_pipeline(
                target_time="now", scripts=scripts, close_running=False
            )
        self.assertEqual(steps, [])
        mock_kill.assert_not_called()


class TestPreRunOrder(unittest.TestCase):
    """build_pre_run_pipeline 组装顺序：等待+静音 → 关闭残留 → 写子脚本 config。"""

    def test_wait_mute_before_close_before_config(self):
        svc_scripts = [{"display_name": "A", "script_process_name": "ABot.exe"}]
        calls: list[str] = []
        past = __import__("datetime").datetime(2000, 1, 1, 0, 0)
        with (
            mock.patch(
                "src.service.scheduled_run.mute_on", lambda: calls.append("mute")
            ),
            mock.patch(
                "src.service.run_actions.kill_processes",
                lambda names: calls.append("kill"),
            ),
            mock.patch(
                "src.service.run_actions.set_config",
                lambda name, weekly_start=None: calls.append("config"),
            ),
            mock.patch(
                "src.service.run_actions.next_target_datetime", return_value=past
            ),
            mock.patch("src.service.run_actions.time.sleep"),
        ):
            steps = build_pre_run_pipeline(
                target_time="08:00",
                scripts=svc_scripts,
                enabled_keys={"A"},
                weekly_start_map={"A": 3},
                close_running=True,
                mute=True,
            )
            for step in steps:
                step()
        # 顺序应为：静音 → 关闭 → 写 config（_wait 不向 calls 追加）。
        self.assertEqual(calls, ["mute", "kill", "config"])

    def test_close_running_false_excludes_close_step(self):
        """close_running=False：跳过关闭残留 step，但等待与写 config 仍保留。"""
        calls: list[str] = []
        with (
            mock.patch(
                "src.service.run_actions.kill_processes",
                lambda names: calls.append("kill"),
            ),
            mock.patch(
                "src.service.run_actions.set_config",
                lambda name, weekly_start=None: calls.append("config"),
            ),
            mock.patch(
                "src.service.run_actions.next_target_datetime",
                return_value=__import__("datetime").datetime(2000, 1, 1, 0, 0),
            ),
            mock.patch("src.service.run_actions.time.sleep"),
        ):
            steps = build_pre_run_pipeline(
                target_time="08:00",
                scripts=[{"display_name": "A", "script_process_name": "ABot.exe"}],
                enabled_keys={"A"},
                weekly_start_map={"A": 3},
                close_running=False,
            )
            for step in steps:
                step()
        # 仅 [等待, 写config]：无关闭调用。
        self.assertEqual(calls, ["config"])


class TestClosePassesAllConfigScripts(unittest.TestCase):
    """close 步骤拿到的是 config 全量脚本，不按本次启用集合过滤。

    回归：残留多为「昨天跑、今天不跑」的脚本遗留，按启用集合过滤恰好抓不住这类。
    """

    def _make_service(self, script_list):
        svc = mock.MagicMock()
        svc.load_config.return_value = {"script_list": script_list}
        svc.load_schedule.return_value = {
            "rerun": {"enabled": False},
            "notify": {"enabled": False},
        }
        svc.get_weekly_start_map.return_value = {}
        return svc

    def test_all_scripts_passed_even_when_not_enabled(self):
        # A 在启用集合内、B 不在；两者（含 B）都应出现在 scripts 中。
        all_scripts = [
            {"display_name": "A", "script_path": "C:/a/run.py"},
            {"display_name": "B", "script_path": "C:/b/run.py"},
        ]
        svc = self._make_service(all_scripts)
        with mock.patch(
            "src.service.scheduled_run.build_pre_run_pipeline", return_value=[]
        ) as mock_build:
            ScheduledRun(svc, {"A"}, "now", close_running=True)
        self.assertEqual(mock_build.call_args.kwargs["scripts"], all_scripts)


if __name__ == "__main__":
    unittest.main()
