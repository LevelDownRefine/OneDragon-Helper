"""测试 src/service/scheduled_run.py：定时等待期应有即时状态日志。

核心回归：定时计划设置后、等待到点前，必须立即输出日志说明「正在等待至 XX:XX」，
避免等待期间静默无日志（用户无法判断进程是否在运行）。
"""

import unittest
from unittest import mock

from src.service.scheduled_run import (
    ScheduledRun,
    build_post_run_pipeline,
    build_pre_run_pipeline,
)
from src.utils_runner import ProcessTarget
from tests.process_sim import ProcessSim


def _make_service(script_list=None, *, schedule=None):
    """构造 ScheduledRun 用的 service 桩：只提供编排读取的几个入口。"""
    svc = mock.MagicMock()
    svc.load_config.return_value = {"script_list": script_list or []}
    default = {"rerun": {"enabled": False}, "notify": {"enabled": False}}
    svc.load_schedule.return_value = default if schedule is None else schedule
    svc.get_weekly_start_map.return_value = {}
    return svc


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


class TestCloseRunningScenario(unittest.TestCase):
    """运行前清场的真实场景：多个脚本，每个脚本各启动了自己的游戏。

    进程表按真机残留形态模拟（详见 tests/process_sim.py）：每个脚本一个启动器真身
    （多脚本共用 pythonw.exe，只能靠命令行里的安装根目录认出）+ 一个由它启动的
    游戏；另有两个无关进程（未纳入 config 的同名解释器、系统进程）不得误伤。

    跑的是 pre_run 产出的 step 本身，故「按配置收集条件 → 扫描 → 终止」整条链
    都在内，而非只断言传给 kill_processes 的参数。
    """

    KEYS = ("ok-ww", "ok-ef", "BetterGI")

    def _scenario(self, **kwargs):
        """造 3 脚本场景，返回 (sim, 未纳入 config 的解释器进程, 系统进程)。"""
        sim = ProcessSim()
        for key in self.KEYS:
            sim.add_script(key, **kwargs)
        foreign = sim.add_other(
            "pythonw.exe", [r"D:\OtherTool\pythonw.exe", r"D:\OtherTool\main.py"]
        )
        system = sim.add_other("explorer.exe")
        return sim, foreign, system

    @staticmethod
    def _run_pre_run(sim: ProcessSim) -> None:
        """执行 pre_run 的关闭 step（now + 无启用集合 → 只产出这一个 step）。"""
        steps = build_pre_run_pipeline(
            target_time="now", scripts=sim.scripts, close_running=True
        )
        assert len(steps) == 1, f"预期只有关闭 step，实际 {len(steps)} 个"
        steps[0]()

    def test_each_script_body_and_game_killed(self):
        """每个脚本的真身与它启动的游戏都被关掉。"""
        sim, _, _ = self._scenario()
        with sim.install():
            self._run_pre_run(sim)
        for key in self.KEYS:
            self.assertTrue(sim.bodies[key].terminated, f"{key} 真身未被关")
            self.assertTrue(sim.games[key].terminated, f"{key} 游戏未被关")

    def test_unrelated_processes_survive(self):
        """无关进程不得误杀：同名的 pythonw.exe 靠安装根目录区分。"""
        sim, foreign, system = self._scenario()
        with sim.install():
            self._run_pre_run(sim)
        self.assertFalse(foreign.terminated, "未纳入 config 的脚本被误杀")
        self.assertFalse(system.terminated, "系统进程被误杀")

    def test_orphan_game_killed_by_name(self):
        """脚本已退出、游戏成孤儿：没有父进程可连带，仍按进程名命中。"""
        sim, _, _ = self._scenario(orphan_game=True)
        with sim.install():
            self._run_pre_run(sim)
        for key in self.KEYS:
            self.assertTrue(sim.games[key].terminated, f"{key} 孤儿游戏未被关")

    def test_body_child_killed_with_tree(self):
        """真身拉起的、不匹配任何条件的子进程随进程树一并清掉。"""
        sim, _, _ = self._scenario()
        helper = sim.add_other("helper.exe", parent=sim.bodies["ok-ww"])
        with sim.install():
            self._run_pre_run(sim)
        self.assertTrue(helper.terminated)

    def test_shared_game_killed_once(self):
        """两脚本配同一游戏（真机 ok-ef 与 MAS 同为 Endfield.exe）：只关一次。

        两脚本各贡献一条同名条件，但同一游戏只有一个进程；日志里该进程只应出现
        一次——按 pid 去重，而非按条件数重复终止。
        """
        sim = ProcessSim()
        for key in ("ok-ef", "MAS"):
            sim.add_script(key, game_name="Endfield.exe")
        with (
            self.assertLogs("src.service.run_actions", level="INFO") as cm,
            sim.install(),
        ):
            self._run_pre_run(sim)
        joined = "\n".join(cm.output)
        self.assertIn("已关闭残留进程 3 个", joined)  # 2 真身 + 1 共用游戏
        self.assertEqual(joined.count("Endfield.exe"), 1)


class TestBuildPreRunClose(unittest.TestCase):
    """build_pre_run_pipeline 的关闭残留进程 step（受 close_running 控制）。"""

    def test_empty_scripts_returns_no_steps(self):
        steps = build_pre_run_pipeline(
            target_time="now", scripts=[], close_running=True
        )
        self.assertEqual(steps, [])

    def test_multiple_scripts_merge_into_one_kill(self):
        # 每个脚本各扫一遍全系统是 8× 开销（实测 17s），故合并成一次调用。
        scripts = [
            {"display_name": "A", "script_process_name": "ABot.exe"},
            {"display_name": "B", "script_process_name": "BBot.exe"},
        ]
        with mock.patch("src.service.run_actions.kill_processes") as mock_kill:
            steps = build_pre_run_pipeline(
                target_time="now", scripts=scripts, close_running=True
            )
            steps[0]()
        mock_kill.assert_called_once_with(
            [ProcessTarget(name="ABot.exe"), ProcessTarget(name="BBot.exe")]
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
                lambda targets: calls.append("kill") or ["ABot.exe(1)"],
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
                lambda targets: calls.append("kill") or ["ABot.exe(1)"],
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


class TestScheduledRunOrder(unittest.TestCase):
    """ScheduledRun.run：pre_run → 核心编排 → post_run。"""

    def test_pre_core_post_in_order(self):
        calls: list[str] = []
        svc = _make_service([{"display_name": "A"}])
        with mock.patch.object(
            ScheduledRun, "_run_core", lambda self: calls.append("core")
        ):
            sched = ScheduledRun(svc, {"A"}, "now")
            sched.pre_run = [lambda: calls.append("pre")]
            sched.post_run = [lambda: calls.append("post")]
            sched.run()
        self.assertEqual(calls, ["pre", "core", "post"])


class TestScheduledRunCore(unittest.TestCase):
    """ScheduledRun._run_core：先跑链，再按 schedule.rerun.enabled 决定是否重跑。"""

    def test_runs_chain_then_rerun_when_enabled(self):
        svc = _make_service(
            [{"display_name": "A"}],
            schedule={"rerun": {"enabled": True}, "notify": {"enabled": False}},
        )
        ScheduledRun(svc, {"A"}, "now", chain_name="today")._run_core()
        svc.run_chain_once.assert_called_once_with({"A"}, chain_name="today")
        svc._rerun_round.assert_called_once()
        kwargs = svc._rerun_round.call_args.kwargs
        self.assertEqual(kwargs["enabled_keys"], {"A"})
        self.assertIn("all_config", kwargs)

    def test_rerun_skipped_when_disabled(self):
        svc = _make_service(
            [{"display_name": "A"}],
            schedule={"rerun": {"enabled": False}, "notify": {"enabled": False}},
        )
        ScheduledRun(svc, {"A"}, "now")._run_core()
        svc.run_chain_once.assert_called_once()
        svc._rerun_round.assert_not_called()

    def test_missing_rerun_block_asserts(self):
        """schedule 缺 rerun.enabled 是契约错误：直接崩，不降级跳过。"""
        svc = _make_service(
            [{"display_name": "A"}], schedule={"notify": {"enabled": False}}
        )
        with self.assertRaises(AssertionError):
            ScheduledRun(svc, {"A"}, "now")._run_core()


class TestPostRunMuteRestore(unittest.TestCase):
    """build_post_run_pipeline 的静音恢复 step：须在关机之前（关机后恢复无意义）。"""

    def _run(self, **kwargs) -> list[str]:
        """构建并执行 post_run，返回各 step 的调用记号。"""
        calls: list[str] = []
        with (
            mock.patch(
                "src.service.run_actions.parse_logs",
                return_value={"rerun": [], "notify": [], "report": "", "entries": []},
            ),
            mock.patch(
                "src.service.scheduled_run.mute_off", lambda: calls.append("mute_off")
            ),
            mock.patch(
                "src.service.scheduled_run.shutdown_sys",
                lambda delay: calls.append("shutdown"),
            ),
        ):
            for step in build_post_run_pipeline(**kwargs):
                step()
        return calls

    def test_mute_off_before_shutdown(self):
        self.assertEqual(
            self._run(shutdown_delay=60, mute=True, enabled_keys={"A"}),
            ["mute_off", "shutdown"],
        )

    def test_mute_off_absent_when_not_muted(self):
        self.assertEqual(self._run(shutdown_delay=60, enabled_keys={"A"}), ["shutdown"])


class TestClosePassesAllConfigScripts(unittest.TestCase):
    """close 步骤拿到的是 config 全量脚本，不按本次启用集合过滤。

    回归：残留多为「昨天跑、今天不跑」的脚本遗留，按启用集合过滤恰好抓不住这类。
    """

    def test_all_scripts_passed_even_when_not_enabled(self):
        # A 在启用集合内、B 不在；两者（含 B）都应出现在 scripts 中。
        all_scripts = [
            {"display_name": "A", "script_path": "C:/a/run.py"},
            {"display_name": "B", "script_path": "C:/b/run.py"},
        ]
        svc = _make_service(all_scripts)
        with mock.patch(
            "src.service.scheduled_run.build_pre_run_pipeline", return_value=[]
        ) as mock_build:
            ScheduledRun(svc, {"A"}, "now", close_running=True)
        self.assertEqual(mock_build.call_args.kwargs["scripts"], all_scripts)


if __name__ == "__main__":
    unittest.main()
