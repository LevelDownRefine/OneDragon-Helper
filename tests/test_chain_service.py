"""测试 src/service/chain_service.py：无头测试，全部 mock 被包装函数。"""

import unittest
from datetime import datetime
from unittest.mock import patch

import src.service.chain_service as chain_service
import src.utils_config as utils_config
from src.service.schedule import ScheduledRun, build_post_run_pipeline


class TestChainGeneration(unittest.TestCase):
    """链生成与校验：转发"""

    def test_generate_chain_delegates(self):
        data = {"script_list": []}
        with (
            patch(
                "src.service.chain_service._generate_chain_config",
                return_value="out.yml",
            ) as m,
            patch("src.service.chain_service.load_all_weekly", return_value={}),
        ):
            out = chain_service.generate_chain(data, {"A"}, "88", out_path="out.yml")
        self.assertEqual(out, "out.yml")
        m.assert_called_once_with(
            data,
            {"A"},
            "88",
            "out.yml",
            weekly_timeouts={},
        )


class TestRunChainOnce(unittest.TestCase):
    """run_chain_once：生成+运行+关机/静音命令构造的模块级原子。"""

    def _make_service(self, script_list):
        self._cfg = patch(
            "src.utils_config.load_config",
            return_value={"script_list": script_list},
        ).start()
        self._weekly_load = patch(
            "src.service.chain_service.load_all_weekly", return_value={}
        ).start()
        self.addCleanup(patch.stopall)

    def test_defaults_all_scripts_and_runs(self):
        self._make_service([{"display_name": "A", "script_path": "A.exe"}])
        with (
            patch(
                "src.service.chain_service._generate_chain_config",
                return_value="out.yml",
            ) as gen,
            patch(
                "src.service.chain_service._build_run_chain_command",
                return_value=(["cmd"], "cwd", None),
            ) as build,
            patch("src.service.chain_service.subprocess.run") as run,
        ):
            chain_service.run_chain_once({"A"})
        # 默认启用全部脚本、chain_name=today、不关机不静音
        gen.assert_called_once_with(
            {"script_list": [{"display_name": "A", "script_path": "A.exe"}]},
            {"A"},
            "today",
            weekly_timeouts={},
        )
        build.assert_called_once_with("out.yml")
        run.assert_called_once()

    def test_run_chain_once_does_not_forward_weekly_start_map(self):
        """回归：weekly_start→子脚本 config 的写盘已移到 ScheduledRun.pre_run，
        run_chain_once 不再把 weekly_start_map 透传给链生成。"""
        self._make_service([{"display_name": "A", "script_path": "A.exe"}])
        self._weekly_load.return_value = {"A": 100}
        with (
            patch(
                "src.service.chain_service._generate_chain_config",
                return_value="out.yml",
            ) as gen,
            patch(
                "src.service.chain_service._build_run_chain_command",
                return_value=(["cmd"], "cwd", None),
            ),
            patch("src.service.chain_service.subprocess.run"),
        ):
            chain_service.run_chain_once({"A"})
        gen.assert_called_once_with(
            {"script_list": [{"display_name": "A", "script_path": "A.exe"}]},
            {"A"},
            "today",
            weekly_timeouts={"A": 100},
        )

    def test_subset_launches_blocking(self):
        """阻塞启动：按子集生成+运行，返回 None（静音已不再经此透传）。"""
        self._make_service(
            [
                {"display_name": "A", "script_path": "A.exe"},
                {"display_name": "B", "script_path": "B.exe"},
            ]
        )
        with (
            patch(
                "src.service.chain_service._generate_chain_config",
                return_value="out.yml",
            ) as gen,
            patch(
                "src.service.chain_service._build_run_chain_command",
                return_value=(["cmd"], "cwd", None),
            ) as build,
            patch("src.service.chain_service.subprocess.run") as run,
        ):
            result = chain_service.run_chain_once({"A"})
        self.assertIsNone(result)
        gen.assert_called_once_with(
            {
                "script_list": [
                    {"display_name": "A", "script_path": "A.exe"},
                    {"display_name": "B", "script_path": "B.exe"},
                ]
            },
            {"A"},
            "today",
            weekly_timeouts={},
        )
        build.assert_called_once_with("out.yml")
        run.assert_called_once()

    def test_empty_script_list_asserts(self):
        self._make_service([])
        with self.assertRaises(AssertionError):
            chain_service.run_chain_once({"A"})

    def test_run_steps_isolates_step_failures(self):
        """ScheduledRun._run_steps：单步失败不影响后续步骤，均记日志。"""
        order = []

        def boom() -> None:
            raise RuntimeError("step failed")

        with patch("src.service.schedule.logger") as mock_logger:
            ScheduledRun._run_steps(
                [lambda: order.append("a"), boom, lambda: order.append("b")]
            )
        self.assertEqual(order, ["a", "b"])
        mock_logger.exception.assert_called_once()


class TestScheduleRun(unittest.TestCase):
    """schedule_run：server 侧真实实现（等待→生成→运行→关机 post_run）。"""

    def setUp(self):
        # schedule.yml 现由 src.service.schedule.load_schedule 读取（模块函数），
        # 故 patch 模块函数；用例改 self.schedule_data 即可切换配置。
        self.schedule_data = {"rerun": {"enabled": True}, "notify": {"enabled": False}}
        patcher = patch(
            "src.service.schedule.load_schedule",
            side_effect=lambda: self.schedule_data,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _make_service(self, script_list):
        self._cfg = patch(
            "src.utils_config.load_config",
            return_value={"script_list": script_list},
        ).start()
        self._run_once = patch(
            "src.service.chain_service.run_chain_once", return_value=None
        ).start()
        self.addCleanup(patch.stopall)
        return self._run_once

    def _run(self, target_time="08:00", **kwargs):
        with (
            patch("src.service.run_actions.time.sleep") as mock_sleep,
            patch(
                "src.service.run_actions.next_target_datetime",
                return_value=datetime(2030, 1, 1, 8, 0),
            ),
            patch(
                "src.service.chain_service.parse_logs",
                return_value={"rerun": [], "notify": [], "report": "", "entries": []},
            ),
            patch("src.service.chain_service._run_chain_once_impl"),
            patch("src.service.schedule.build_post_run_pipeline", return_value=[]),
            patch("src.service.schedule.shutdown_sys") as mock_shutdown,
        ):
            chain_service.schedule_run({"demo"}, target_time, **kwargs)
        return mock_sleep, mock_shutdown

    def test_waits_generates_runs(self):
        self._make_service([{"display_name": "demo"}])
        mock_sleep, mock_shutdown = self._run()
        mock_sleep.assert_called_once()  # pre_run 等待
        # 第一次跑复用 run_chain_once，与重跑路径一致（仅脚本集合/链名不同）。
        self._run_once.assert_called_once_with({"demo"}, chain_name="today")
        mock_shutdown.assert_not_called()

    def test_shutdown_triggers_post_run(self):
        """shutdown_delay 非 None 时透传给 build_post_run_pipeline（末位挂关机 step）。"""
        self._make_service([{"display_name": "demo"}])
        with (
            patch("src.service.run_actions.time.sleep"),
            patch(
                "src.service.run_actions.next_target_datetime",
                return_value=datetime(2030, 1, 1, 8, 0),
            ),
            patch("src.service.chain_service.parse_logs", return_value={"rerun": []}),
            patch("src.service.chain_service._run_chain_once_impl"),
            patch("src.service.schedule.build_post_run_pipeline") as mock_pipeline,
        ):
            chain_service.schedule_run({"demo"}, "08:00", shutdown_delay=60)
        mock_pipeline.assert_called_once_with(
            shutdown_delay=60, smtp_config=None, mute=False, enabled_keys={"demo"}
        )

    def test_mute_passed_to_pipelines(self):
        """mute=True：透传给 pre_run/post_run 工厂（由其挂静音/恢复 step），不再透传 run_chain_once。"""
        self._make_service([{"display_name": "demo"}])
        with (
            patch("src.service.run_actions.time.sleep"),
            patch(
                "src.service.run_actions.next_target_datetime",
                return_value=datetime(2030, 1, 1, 8, 0),
            ),
            patch("src.service.chain_service.parse_logs", return_value={"rerun": []}),
            patch("src.service.chain_service._run_chain_once_impl"),
            patch("src.service.schedule.build_pre_run_pipeline") as mock_pre,
            patch("src.service.schedule.build_post_run_pipeline") as mock_post,
        ):
            chain_service.schedule_run({"demo"}, "08:00", mute=True)
        # mute 经 pre_run 工厂透传（由其挂静音 step），不再经 run_chain_once
        self.assertTrue(mock_pre.called)
        pre_kwargs = mock_pre.call_args.kwargs
        self.assertEqual(pre_kwargs["target_time"], "08:00")
        self.assertTrue(pre_kwargs["mute"])
        mock_post.assert_called_once_with(
            shutdown_delay=None, smtp_config=None, mute=True, enabled_keys={"demo"}
        )
        # 静音不再经 run_chain_once 透传
        _, kwargs = self._run_once.call_args
        self.assertNotIn("mute", kwargs)

    def test_now_skips_wait(self):
        """target_time='now'（即时运行）跳过等待，直接点火运行。"""
        self._make_service([{"display_name": "demo"}])
        with (
            patch("src.service.run_actions.time.sleep") as mock_sleep,
            patch(
                "src.service.run_actions.next_target_datetime",
                return_value=datetime(2030, 1, 1, 8, 0),
            ),
            patch(
                "src.service.chain_service.parse_logs",
                return_value={"rerun": [], "notify": [], "report": "", "entries": []},
            ),
            patch("src.service.chain_service._run_chain_once_impl"),
            patch("src.service.schedule.shutdown_sys"),
        ):
            chain_service.schedule_run({"demo"}, "now")
        mock_sleep.assert_not_called()  # 即时：不等待
        self._run_once.assert_called_once()  # 仍点火运行

    def test_no_shutdown_when_none(self):
        self._make_service([{"display_name": "demo"}])
        _, mock_shutdown = self._run(shutdown_delay=None)
        mock_shutdown.assert_not_called()

    def test_rerun_round_before_post_run(self):
        """schedule_run：链跑完后先重跑失败脚本，再执行 post_run（邮件/关机）。"""
        self._make_service([{"display_name": "demo"}])
        order = []
        with (
            patch("src.service.run_actions.time.sleep"),
            patch(
                "src.service.run_actions.next_target_datetime",
                return_value=datetime(2030, 1, 1, 8, 0),
            ),
            patch(
                "src.service.chain_service.parse_logs",
                return_value={
                    "rerun": ["demo"],
                    "notify": [],
                    "report": "",
                    "entries": [],
                },
            ),
            patch(
                "src.service.chain_service._run_chain_once_impl",
                side_effect=lambda *a, **k: order.append("rerun"),
            ),
            patch(
                "src.service.schedule.build_post_run_pipeline",
                return_value=[lambda: order.append("mail")],
            ),
        ):
            chain_service.schedule_run({"demo"}, "08:00", shutdown_delay=60)
        self.assertEqual(order, ["rerun", "mail"])

    def test_rerun_skipped_when_disabled(self):
        """schedule.rerun.enabled=false：链跑完后不进入重跑轮。"""
        self._make_service([{"display_name": "demo"}])
        self.schedule_data = {
            "rerun": {"enabled": False},
            "notify": {"enabled": False},
        }
        with (
            patch("src.service.run_actions.time.sleep"),
            patch(
                "src.service.run_actions.next_target_datetime",
                return_value=datetime(2030, 1, 1, 8, 0),
            ),
            patch("src.service.chain_service._run_chain_once_impl") as rerun,
            patch("src.service.schedule.build_post_run_pipeline", return_value=[]),
        ):
            chain_service.schedule_run({"demo"}, "08:00")
        rerun.assert_not_called()

    def test_mail_skipped_when_disabled(self):
        """notify.enabled=false（即便配了 email/password）：smtp_config 为 None（不发信）。"""
        self._make_service([{"display_name": "demo"}])
        self.schedule_data = {
            "rerun": {"enabled": True},
            "notify": {"enabled": False, "email": "a@qq.com", "password": "pw"},
        }
        captured = {}

        def _fake_pipeline(
            *, shutdown_delay, smtp_config, mute=False, enabled_keys=None
        ):
            captured["smtp_config"] = smtp_config
            return []

        with (
            patch("src.service.run_actions.time.sleep"),
            patch(
                "src.service.run_actions.next_target_datetime",
                return_value=datetime(2030, 1, 1, 8, 0),
            ),
            patch(
                "src.service.chain_service.parse_logs",
                return_value={"rerun": [], "notify": [], "report": "", "entries": []},
            ),
            patch(
                "src.service.schedule.build_post_run_pipeline",
                side_effect=_fake_pipeline,
            ) as pipeline,
        ):
            chain_service.schedule_run({"demo"}, "08:00")
        pipeline.assert_called_once()
        self.assertIsNone(captured["smtp_config"])


class TestBuildPostRunPipeline(unittest.TestCase):
    """build_post_run_pipeline：日志分析(最终态) → 邮件 → 关机(末位)（重跑已移出）。"""

    def _result(self, *, rerun=("demo",), notify=("demo",)):
        return {
            "rerun": list(rerun),
            "notify": list(notify),
            "report": "R",
            "entries": [],
        }

    def _run(self, *, rerun=("demo",), notify=("demo",), **kwargs):
        """构建并执行 pipeline，返回各 mock。rerun/notify 控制 parse_logs 产物。"""
        with (
            patch(
                "src.service.run_actions.parse_logs",
                return_value=self._result(rerun=rerun, notify=notify),
            ) as parse,
            patch("src.service.run_actions.send_mail") as mail,
            patch("src.service.schedule.shutdown_sys") as shutdown,
        ):
            steps = build_post_run_pipeline(**kwargs)
            for step in steps:
                step()
        return parse, mail, shutdown

    def test_full_pipeline_order_and_calls(self):
        """有 SMTP+关机：分析(最终态)→邮件→关机，均触发；重跑不在 pipeline 内。"""
        parse, mail, shutdown = self._run(
            shutdown_delay=60,
            smtp_config={"enabled": True, "email": "a@qq.com", "password": "pw"},
        )
        self.assertEqual(parse.call_count, 1)  # 仅最终态分析
        self.assertEqual(parse.call_args.kwargs.get("do_log"), False)
        mail.assert_called_once()
        shutdown.assert_called_once_with(60)

    def test_empty_rerun_skips_rerun_and_reparse(self):
        """rerun 名单为空不影响：邮件/关机按配置；pipeline 内部本就不含重跑。"""
        parse, mail, shutdown = self._run(
            rerun=(), shutdown_delay=None, smtp_config=None
        )
        self.assertEqual(parse.call_count, 1)
        mail.assert_not_called()
        shutdown.assert_not_called()

    def test_no_shutdown_trims_steps(self):
        """shutdown_delay=None：末位关机步骤不出现（仍可发邮件）。"""
        parse, mail, shutdown = self._run(
            shutdown_delay=None,
            smtp_config={"enabled": True, "email": "a@qq.com", "password": "pw"},
        )
        mail.assert_called_once()  # 邮件仍执行
        shutdown.assert_not_called()

    def test_mail_skipped_without_smtp_config(self):
        """未配置 SMTP：邮件步骤静默跳过（默认关闭）。"""
        parse, mail, shutdown = self._run(shutdown_delay=None, smtp_config=None)
        mail.assert_not_called()

    def test_enabled_keys_passed_as_candidate_to_parse_logs(self):
        """build_post_run_pipeline 把本次启用的脚本集合作为候选列表传给 parse_logs：
        邮件汇总只在候选（启用）脚本内挑选，未启用脚本不计入。"""
        parse, mail, shutdown = self._run(
            shutdown_delay=None,
            smtp_config={"enabled": True, "email": "a@qq.com", "password": "pw"},
            enabled_keys={"demo"},
        )
        parse.assert_called_once_with(do_log=False, candidate_script_names={"demo"})


class TestRerunRound(unittest.TestCase):
    """chain_service.rerun_round：链结束后解析日志，对失败脚本二次运行（主流程）。

    逻辑已内联（不再经 src.log.rerun），此处直接验证其与 _run_chain_once_impl 的交互。
    """

    def _svc_with_config(self, script_list):
        self._cfg = patch(
            "src.utils_config.load_config",
            return_value={"script_list": script_list},
        ).start()
        self._weekly_load = patch(
            "src.service.chain_service.load_all_weekly", return_value={}
        ).start()
        self.addCleanup(patch.stopall)
        return self._cfg

    def test_reruns_when_rerun_list_nonempty(self):
        """parse_logs 产出 rerun 非空 → 以 chain_name='rerun' 阻塞重跑失败子集。"""
        self._svc_with_config([{"display_name": "demo", "script_path": "demo"}])
        with (
            patch(
                "src.service.chain_service.parse_logs",
                return_value={
                    "rerun": ["demo"],
                    "notify": [],
                    "report": "",
                    "entries": [],
                },
            ),
            patch("src.service.chain_service._run_chain_once_impl") as run_impl,
        ):
            chain_service.rerun_round(
                all_config=utils_config.load_config(), enabled_keys={"demo"}
            )
        run_impl.assert_called_once()
        args, kwargs = run_impl.call_args
        self.assertEqual(args[1], {"demo"})  # 启用脚本集合
        self.assertEqual(kwargs["chain_name"], "rerun")
        self.assertNotIn("mute", kwargs)  # 静音已不在重跑路径透传

    def test_no_rerun_when_list_empty(self):
        """rerun 为空列表 → _run_chain_once_impl 不调用。"""
        self._svc_with_config([{"display_name": "demo", "script_path": "demo"}])
        with (
            patch(
                "src.service.chain_service.parse_logs",
                return_value={"rerun": [], "notify": [], "report": "", "entries": []},
            ),
            patch("src.service.chain_service._run_chain_once_impl") as run_impl,
        ):
            chain_service.rerun_round(
                all_config=utils_config.load_config(), enabled_keys={"demo"}
            )
        run_impl.assert_not_called()

    def test_filters_unknown_script_names(self):
        """rerun_list 含不在 config 的脚本名时，仅对已知脚本重跑。"""
        self._svc_with_config([{"display_name": "demo", "script_path": "demo"}])
        with (
            patch(
                "src.service.chain_service.parse_logs",
                return_value={
                    "rerun": ["demo", "ghost"],
                    "notify": [],
                    "report": "",
                    "entries": [],
                },
            ),
            patch("src.service.chain_service._run_chain_once_impl") as run_impl,
        ):
            chain_service.rerun_round(
                all_config=utils_config.load_config(), enabled_keys={"demo"}
            )
        run_impl.assert_called_once()
        args, _ = run_impl.call_args
        self.assertEqual(args[1], {"demo"})  # 过滤掉的 ghost 不在 config

    def test_passes_enabled_keys_to_parse_logs(self):
        """rerun_round 把本次启用的脚本集合透传给 parse_logs，使重跑仅针对启用脚本。"""
        self._svc_with_config([{"display_name": "demo", "script_path": "demo"}])
        with (
            patch(
                "src.service.chain_service.parse_logs",
                return_value={"rerun": [], "notify": [], "report": "", "entries": []},
            ) as parse,
            patch("src.service.chain_service._run_chain_once_impl"),
        ):
            chain_service.rerun_round(
                all_config=utils_config.load_config(),
                enabled_keys={"demo", "other"},
            )
        parse.assert_called_once_with(
            do_log=False, candidate_script_names={"demo", "other"}
        )


if __name__ == "__main__":
    unittest.main()
