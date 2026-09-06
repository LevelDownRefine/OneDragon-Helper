"""测试 src/service/schedule.py：定时运行的 pre_run / core / post_run 流水线。

覆盖：
- 工厂装配契约（build_pre_run_pipeline 合并成一次 kill、写配置按启用集、
  定时等待期应即时输出日志）；
- close 场景（多脚本各启一个游戏，经 ScheduledRun.run() 真实清场，含误杀防护/树杀/
  共用游戏只杀一次/关闭开关负路径）；
- core 重跑决策（启用/禁用/缺块契约错误）；
- 全流水线顺序（mute→wait→close→config→core→rerun→analyze→mail→mute_off→shutdown，
  经 run() 真实装配断言）；
- apply_run_options（确认窗勾选项合并写回 schedule.yml + 授权码最佳努力注册）。
"""

import datetime
import os
import tempfile
import unittest
from dataclasses import replace
from unittest import mock

from src.service.schedule import (
    RunOptions,
    ScheduledRun,
    apply_run_options,
    build_pre_run_pipeline,
    load_run_options,
)
from src.utils.utils_runner import ProcessTarget
from src.utils.utils_yaml import dump_yaml, load_yaml
from tests.process_sim import ProcessSim


def _make_service(testcase, script_list=None, *, schedule=None):
    """构造 ScheduledRun 用的 service 桩：只提供编排读取的几个入口。

    load_config / get_weekly_start_map 现由 schedule 直接 import 对应 utils 调用，
    故在此 patch 真实模块属性（随 testcase 退出自动 stop）。
    """
    svc = mock.MagicMock()
    default = {"rerun": {"enabled": False}, "notify": {"enabled": False}}
    # schedule 数据不再经 service 桩注入（ScheduledRun 直接调本模块 load_schedule），
    # 挂到 svc 上供用例 patch src.service.schedule.load_schedule 时取用。
    svc.schedule_data = default if schedule is None else schedule
    p_cfg = mock.patch(
        "src.utils.utils_config.load_config",
        return_value={"script_list": script_list or []},
    )
    p_cfg.start()
    testcase.addCleanup(p_cfg.stop)
    p_weekly = mock.patch(
        "src.utils.utils_weekly.get_weekly_start_map", return_value={}
    )
    p_weekly.start()
    testcase.addCleanup(p_weekly.stop)
    return svc


class TestPreRunWaitLogs(unittest.TestCase):
    """build_pre_run_pipeline：定时模式的等待 step 立即打日志、不静默。"""

    def test_wait_step_emits_log_before_sleeping(self):
        # 让目标时刻恒为「未来」，进入等待分支打印「将等待至」；time.sleep 被 mock
        # 掉避免真实长睡，随后仍打印「已到达」。验证等待期不再静默。
        future = datetime.datetime(2099, 1, 1, 0, 0)
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
            # target=now、未传 scripts → 仅产生写 config step（关闭残留需 scripts 非空）
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
    """build_pre_run_pipeline 的关闭残留进程 step（受 close_running 控制）。

    工厂级装配契约：合并成一次 kill_processes 调用、无进程名跳过、close_running=False
    不产 step。经 ScheduledRun.run() 的「真实杀伤」由 TestScheduledRunPreRunClose 覆盖，
    此处只断言工厂产出/合并，不碰真实进程。
    """

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
        # close_running=False：即便给了 scripts 也不产生关闭 step。
        scripts = [{"display_name": "A", "script_process_name": "ABot.exe"}]
        with mock.patch("src.service.run_actions.kill_processes") as mock_kill:
            steps = build_pre_run_pipeline(
                target_time="now", scripts=scripts, close_running=False
            )
        self.assertEqual(steps, [])
        mock_kill.assert_not_called()


class TestScheduledRunPreRunClose(unittest.TestCase):
    """集成：ScheduledRun.run() 端到端跑 pre_run 清场 → 核心编排 → post_run。

    清场场景用 ProcessSim 造「多脚本、每个脚本各启一个游戏」的真实残留，作为 pre_run
    的关闭 step 输入，经 ScheduledRun.run() 真实触发（而非直接调 build_pre_run_pipeline）——
    证明 ScheduledRun 真的把清场装配进 pre_run 并跑掉。core 与 post_run 用桩（runner
    不关心）。每个 pipeline 只含 core 以外的 1 个 step：pre_run 仅关闭残留、post_run 仅 1 步。
    """

    KEYS = ("ok-ww", "ok-ef", "MAS")

    def _run(self, sim: ProcessSim, *, close_running: bool = True):
        """经 ScheduledRun.run() 触发清场；post_run 用 1 步桩挡掉真实 parse_logs。"""
        svc = _make_service(self, sim.scripts)
        post_done: list[str] = []
        with (
            mock.patch(
                "src.service.schedule.load_schedule",
                return_value=svc.schedule_data,
            ),
            mock.patch(
                "src.service.schedule.build_post_run_pipeline",
                return_value=[lambda: post_done.append("post")],
            ),
            sim.install(),
        ):
            ScheduledRun(svc, None, "now", close_running=close_running).run()
        return svc, post_done

    def test_run_kills_each_body_and_game(self):
        """每个脚本的真身与它启动的游戏都被关掉（经 run() 真实装配）。"""
        sim = ProcessSim()
        for key in self.KEYS:
            sim.add_script(key)
        self._run(sim)
        for key in self.KEYS:
            self.assertTrue(sim.bodies[key].terminated, f"{key} 真身未被关")
            self.assertTrue(sim.games[key].terminated, f"{key} 游戏未被关")

    def test_run_leaves_unrelated_alive(self):
        """无关进程不得误杀：同名的 pythonw.exe 靠安装根目录区分（经 run()）。"""
        sim = ProcessSim()
        for key in self.KEYS:
            sim.add_script(key)
        foreign = sim.add_other(
            "pythonw.exe", [r"D:\OtherTool\pythonw.exe", r"D:\OtherTool\main.py"]
        )
        system = sim.add_other("explorer.exe")
        self._run(sim)
        self.assertFalse(foreign.terminated, "未纳入 config 的脚本被误杀")
        self.assertFalse(system.terminated, "系统进程被误杀")

    def test_run_kills_orphan_game_by_name(self):
        """脚本已退出、游戏成孤儿：无父进程可连带，仍按进程名命中（经 run()）。"""
        sim = ProcessSim()
        for key in self.KEYS:
            sim.add_script(key, orphan_game=True)
        self._run(sim)
        for key in self.KEYS:
            self.assertTrue(sim.games[key].terminated, f"{key} 孤儿游戏未被关")

    def test_run_kills_child_with_tree(self):
        """真身拉起的、不匹配任何条件的子进程随进程树一并清掉（经 run()）。"""
        sim = ProcessSim()
        for key in self.KEYS:
            sim.add_script(key)
        helper = sim.add_other("helper.exe", parent=sim.bodies["ok-ww"])
        self._run(sim)
        self.assertTrue(helper.terminated)

    def test_run_kills_shared_game_once(self):
        """两脚本配同一游戏（ok-ef 与 MAS 同为 Endfield.exe）：经 run() 全链路只关一次。

        按 pid 去重，而非按脚本条件数重复终止。
        """
        sim = ProcessSim()
        for key in ("ok-ef", "MAS"):
            sim.add_script(key, game_name="Endfield.exe")
        svc = _make_service(self, sim.scripts)
        with (
            mock.patch(
                "src.service.schedule.load_schedule",
                return_value=svc.schedule_data,
            ),
            mock.patch(
                "src.service.schedule.build_post_run_pipeline",
                return_value=[lambda: None],
            ),
            self.assertLogs("src.service.run_actions", level="INFO") as cm,
            sim.install(),
        ):
            ScheduledRun(svc, None, "now", close_running=True).run()
        joined = "\n".join(cm.output)
        self.assertIn("已关闭残留进程 3 个", joined)  # 2 真身 + 1 共用游戏
        self.assertEqual(joined.count("Endfield.exe"), 1)

    def test_run_close_disabled_leaves_games_alive(self):
        """close_running=False：pre_run 不含关闭 step，残留游戏活过 run()；core/post 仍走。"""
        sim = ProcessSim()
        for key in self.KEYS:
            sim.add_script(key)
        svc, _ = self._run(sim, close_running=False)
        for key in self.KEYS:
            self.assertFalse(sim.bodies[key].terminated, f"{key} 真身不应被关")
            self.assertFalse(sim.games[key].terminated, f"{key} 游戏不应被关")
        svc.run_chain_once.assert_called_once_with(None, chain_name="today")

    def test_run_lifecycle_wiring(self):
        """纯生命周期：pre_run 恰好 1 步关闭、core 跑一次、post_run 收尾 1 步。"""
        sim = ProcessSim()
        sim.add_script("ok-ww")
        svc = _make_service(self, sim.scripts)
        post_done: list[str] = []
        with (
            mock.patch(
                "src.service.schedule.load_schedule",
                return_value=svc.schedule_data,
            ),
            mock.patch(
                "src.service.schedule.build_post_run_pipeline",
                return_value=[lambda: post_done.append("post")],
            ),
            sim.install(),
        ):
            sched = ScheduledRun(svc, None, "now", close_running=True)
            self.assertEqual(len(sched.pre_run), 1)
            sched.run()
        svc.run_chain_once.assert_called_once_with(None, chain_name="today")
        self.assertEqual(post_done, ["post"])


class TestScheduledRunOrder(unittest.TestCase):
    """ScheduledRun 全链路 step 顺序：pre_run 内部 → 生命周期 → post_run 内部，一次跑通。

    经 ScheduledRun.run() 真实装配并运行（pre_run/post_run 由工厂产出真实 step，仅叶子
    动作 mock），记录各 step 调用记号并断言全局顺序。取代原先分散在 TestPreRunOrder /
    TestScheduledRunOrder / TestPostRunMuteRestore 的三处顺序测试——它们各自只验一段，
    且 pre_run/post_run 用手塞 lambda，不证明真实装配顺序。
    """

    def _run_and_record(self, *, close_running=True, mute=True, shutdown_delay=60):
        calls: list[str] = []
        svc = _make_service(
            self,
            [{"display_name": "A", "script_process_name": "ABot.exe"}],
            schedule={
                "rerun": {"enabled": True},
                "notify": {"enabled": True, "email": "a@b.c", "password": "x"},
            },
        )
        svc.run_chain_once.side_effect = lambda *a, **k: calls.append("core")
        svc.rerun_round.side_effect = lambda *a, **k: calls.append("rerun")
        with (
            mock.patch(
                "src.service.schedule.load_schedule",
                return_value=svc.schedule_data,
            ),
            mock.patch("src.service.schedule.mute_on", lambda: calls.append("mute_on")),
            mock.patch(
                "src.service.schedule.mute_off", lambda: calls.append("mute_off")
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
                "src.service.run_actions.next_target_datetime",
                return_value=datetime.datetime(2000, 1, 1, 0, 0),
            ),
            mock.patch("src.service.run_actions.time.sleep"),
            mock.patch(
                "src.service.schedule.analyze_logs",
                lambda enabled_keys: calls.append("analyze") or {"entries": []},
            ),
            mock.patch(
                "src.service.schedule.send_summary_mail",
                lambda result, smtp_config: calls.append("mail"),
            ),
            mock.patch(
                "src.service.schedule.shutdown_sys",
                lambda delay: calls.append("shutdown"),
            ),
        ):
            ScheduledRun(
                svc,
                {"A"},
                "08:00",
                close_running=close_running,
                mute=mute,
                shutdown_delay=shutdown_delay,
            ).run()
        return calls

    def test_full_pipeline_order(self):
        # 定时+静音+关闭+启用+重跑+通知+关机 全开：全局顺序。
        # _wait 只打日志不进 calls，故序列从 mute_on 起。
        self.assertEqual(
            self._run_and_record(),
            [
                "mute_on",
                "kill",
                "config",
                "core",
                "rerun",
                "analyze",
                "mail",
                "mute_off",
                "shutdown",
            ],
        )

    def test_close_running_false_drops_close(self):
        # close_running=False：关闭 step 被排除，其余顺序不变。
        calls = self._run_and_record(close_running=False)
        self.assertNotIn("kill", calls)
        self.assertIn("config", calls)
        self.assertIn("shutdown", calls)

    def test_not_muted_skips_mute_restore(self):
        # mute=False：post_run 无恢复声音 step（须在关机前，但本就不静音）。
        calls = self._run_and_record(mute=False)
        self.assertNotIn("mute_off", calls)
        self.assertIn("shutdown", calls)


class TestScheduledRunCore(unittest.TestCase):
    """ScheduledRun._run_core：先跑链，再按 schedule.rerun.enabled 决定是否重跑。"""

    def test_runs_chain_then_rerun_when_enabled(self):
        svc = _make_service(
            self,
            [{"display_name": "A"}],
            schedule={"rerun": {"enabled": True}, "notify": {"enabled": False}},
        )
        with mock.patch(
            "src.service.schedule.load_schedule", return_value=svc.schedule_data
        ):
            ScheduledRun(svc, {"A"}, "now", chain_name="today")._run_core()
        svc.run_chain_once.assert_called_once_with({"A"}, chain_name="today")
        svc.rerun_round.assert_called_once()
        kwargs = svc.rerun_round.call_args.kwargs
        self.assertEqual(kwargs["enabled_keys"], {"A"})
        self.assertIn("all_config", kwargs)

    def test_rerun_skipped_when_disabled(self):
        svc = _make_service(
            self,
            [{"display_name": "A"}],
            schedule={"rerun": {"enabled": False}, "notify": {"enabled": False}},
        )
        with mock.patch(
            "src.service.schedule.load_schedule", return_value=svc.schedule_data
        ):
            ScheduledRun(svc, {"A"}, "now")._run_core()
        svc.run_chain_once.assert_called_once()
        svc.rerun_round.assert_not_called()

    def test_missing_rerun_block_asserts(self):
        """schedule 缺 rerun.enabled 是契约错误：直接崩，不降级跳过。"""
        svc = _make_service(
            self, [{"display_name": "A"}], schedule={"notify": {"enabled": False}}
        )
        with (
            mock.patch(
                "src.service.schedule.load_schedule", return_value=svc.schedule_data
            ),
            self.assertRaises(AssertionError),
        ):
            ScheduledRun(svc, {"A"}, "now")._run_core()


class TestLoadRunOptions(unittest.TestCase):
    """load_run_options：schedule.yml 六块 → RunOptions 的解析与安全降级。"""

    def test_defaults_on_empty_schedule(self):
        opts = load_run_options({})
        self.assertFalse(opts.shutdown_enabled)
        self.assertEqual(opts.shutdown_delay, 0)
        self.assertFalse(opts.timed_enabled)
        self.assertEqual(opts.timed_target, "")
        self.assertFalse(opts.mute_enabled)
        self.assertTrue(opts.close_running_enabled)  # 历史默认：运行前始终清场
        self.assertFalse(opts.rerun_enabled)
        self.assertFalse(opts.notify_enabled)

    def test_shutdown_enabled_with_positive_delay(self):
        opts = load_run_options({"shutdown": {"after_run": True, "delay_seconds": 45}})
        self.assertTrue(opts.shutdown_enabled)
        self.assertEqual(opts.shutdown_delay, 45)

    def test_shutdown_invalid_delay_clamped_to_zero(self):
        """delay 非法（<=0/非 int）→ delay 归 0；开关仍反映 after_run（启动侧再按 >0 判定）。"""
        for bad in (0, -1, "45", None):
            with self.subTest(bad=bad):
                opts = load_run_options(
                    {"shutdown": {"after_run": True, "delay_seconds": bad}}
                )
                self.assertTrue(opts.shutdown_enabled)
                self.assertEqual(opts.shutdown_delay, 0)

    def test_shutdown_switch_non_bool_is_off(self):
        opts = load_run_options(
            {"shutdown": {"after_run": "false", "delay_seconds": 45}}
        )
        self.assertFalse(opts.shutdown_enabled)

    def test_timed_enabled_with_valid_target(self):
        opts = load_run_options(
            {"timed_run": {"enabled": True, "target_time": "08:30"}}
        )
        self.assertTrue(opts.timed_enabled)
        self.assertEqual(opts.timed_target, "08:30")

    def test_timed_illegal_target_degrades(self):
        for bad in ("25:99", 480.0, None):
            with self.subTest(bad=bad):
                opts = load_run_options(
                    {"timed_run": {"enabled": True, "target_time": bad}}
                )
                self.assertFalse(opts.timed_enabled)
                self.assertEqual(opts.timed_target, "")

    def test_mute_block_non_bool_disabled(self):
        self.assertFalse(load_run_options({"mute": {"enabled": "yes"}}).mute_enabled)
        self.assertTrue(load_run_options({"mute": {"enabled": True}}).mute_enabled)

    def test_close_running_explicit_false_respected(self):
        opts = load_run_options({"close_running": {"enabled": False}})
        self.assertFalse(opts.close_running_enabled)

    def test_notify_fields_extracted(self):
        opts = load_run_options(
            {
                "notify": {
                    "enabled": True,
                    "email": "a@qq.com",
                    "smtp_host": "smtp.163.com",
                    "smtp_port": 994,
                }
            }
        )
        self.assertTrue(opts.notify_enabled)
        self.assertEqual(opts.email, "a@qq.com")
        self.assertEqual(opts.smtp_host, "smtp.163.com")
        self.assertEqual(opts.smtp_port, "994")


class TestApplyRunOptions(unittest.TestCase):
    """apply_run_options：运行选项合并写回 schedule.yml + 授权码注册（最佳努力）。

    GUI 控制器只透传 RunOptions（确认窗 result，见 test_launch_controller /
    test_run_confirm_dialog）；合并规则在此验证。
    """

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.schedule_path = os.path.join(self.tmp_dir.name, "schedule.yml")
        dump_yaml(self.schedule_path, {"notify": {"enabled": False, "email": ""}})
        patcher = mock.patch(
            "src.service.schedule.get_schedule_yml_path_under_root",
            return_value=self.schedule_path,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _read(self):
        return load_yaml(self.schedule_path)

    @staticmethod
    def _options(**overrides) -> RunOptions:
        base = RunOptions(
            shutdown_enabled=True,
            shutdown_delay=120,
            timed_enabled=True,
            timed_target="04:10",
            mute_enabled=True,
            close_running_enabled=True,
            rerun_enabled=True,
            notify_enabled=True,
            email="123456@qq.com",
        )
        return replace(base, **overrides) if overrides else base

    def test_writes_all_blocks(self):
        apply_run_options(self._options())
        data = self._read()
        self.assertEqual(data["shutdown"], {"after_run": True, "delay_seconds": 120})
        self.assertEqual(data["timed_run"], {"enabled": True, "target_time": "04:10"})
        self.assertEqual(data["mute"], {"enabled": True})
        self.assertEqual(data["close_running"], {"enabled": True})
        self.assertEqual(data["rerun"], {"enabled": True})
        self.assertEqual(data["notify"], {"enabled": True, "email": "123456@qq.com"})

    def test_disabled_drops_target_and_keeps_delay(self):
        """关闭定时清空 target；关闭关机保留弹窗给定的延迟值（不归零）。"""
        apply_run_options(
            self._options(
                timed_enabled=False, shutdown_enabled=False, shutdown_delay=45
            )
        )
        data = self._read()
        self.assertEqual(data["timed_run"], {"enabled": False, "target_time": ""})
        self.assertEqual(data["shutdown"], {"after_run": False, "delay_seconds": 45})

    def test_enabled_with_illegal_target_falls_back(self):
        apply_run_options(self._options(timed_target="25:99"))
        self.assertEqual(
            self._read()["timed_run"], {"enabled": True, "target_time": "04:10"}
        )

    def test_smtp_written_when_filled(self):
        apply_run_options(self._options(smtp_host="smtp.163.com", smtp_port="994"))
        notify = self._read()["notify"]
        self.assertEqual(notify["smtp_host"], "smtp.163.com")
        self.assertEqual(notify["smtp_port"], 994)

    def test_empty_notify_fields_not_written(self):
        """email/smtp 留空 = 不覆盖既有值。"""
        apply_run_options(self._options(smtp_host="", smtp_port="", email=""))
        self.assertEqual(self._read()["notify"], {"enabled": True, "email": ""})

    def test_invalid_smtp_port_keeps_old_value(self):
        dump_yaml(self.schedule_path, {"notify": {"smtp_port": 465}})
        apply_run_options(self._options(smtp_port="abc"))
        self.assertEqual(self._read()["notify"]["smtp_port"], 465)

    def test_registers_auth_code(self):
        with mock.patch("src.service.schedule.register_credentials") as reg:
            apply_run_options(self._options(auth_code="authcode16"))
        reg.assert_called_once_with("123456@qq.com", "authcode16")
        # 授权码只进凭据管理器，不落 schedule.yml
        self.assertNotIn("auth_code", self._read().get("notify", {}))

    def test_empty_auth_code_skips_keyring(self):
        """授权码留空：不调凭据管理器（保留既有凭据）。"""
        with mock.patch("src.service.schedule.register_credentials") as reg:
            apply_run_options(self._options(auth_code=""))
        reg.assert_not_called()

    def test_register_failure_still_saves_schedule(self):
        """凭据写入失败为最佳努力：记日志，调度参数照常落盘。"""
        with mock.patch(
            "src.service.schedule.register_credentials",
            side_effect=RuntimeError("no keyring"),
        ):
            apply_run_options(self._options(auth_code="authcode16"))
        self.assertEqual(self._read()["shutdown"]["delay_seconds"], 120)


if __name__ == "__main__":
    unittest.main()
