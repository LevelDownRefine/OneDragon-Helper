"""链生成、运行与调度编排；外部进程和通知使用替身。"""

import os
import subprocess
import unittest
from datetime import datetime
from unittest.mock import patch

import src.service.chain_service as chain_service
import src.utils.utils_config as utils_config
from src.service.schedule import ScheduledRun, build_post_run_pipeline


class TestRunChainOnce(unittest.TestCase):
    """生成所选脚本链并等待子进程结束。"""

    def test_run_selected_chain_passes_weekly_timeouts_and_waits(self):
        for subset, weekly in ((False, {}), (False, {"A": 100}), (True, {})):
            with self.subTest(subset=subset, weekly=weekly):
                scripts = [{"display_name": "A", "script_path": "A.exe"}]
                if subset:
                    scripts.append({"display_name": "B", "script_path": "B.exe"})
                with (
                    patch(
                        "src.utils.utils_config.load_config",
                        return_value={"script_list": scripts},
                    ),
                    patch(
                        "src.service.chain_service.load_all_weekly", return_value=weekly
                    ),
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
                    self.assertIsNone(chain_service.run_chain_once({"A"}))
                gen.assert_called_once_with(
                    {"script_list": scripts}, {"A"}, "today", weekly_timeouts=weekly
                )
                build.assert_called_once_with("out.yml")
                flags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
                run.assert_called_once_with(
                    ["cmd"], cwd="cwd", env=None, creationflags=flags
                )

    def test_empty_script_list_asserts(self):
        with (
            patch(
                "src.utils.utils_config.load_config", return_value={"script_list": []}
            ),
            patch("src.service.chain_service.load_all_weekly", return_value={}),
            self.assertRaises(AssertionError),
        ):
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
        self._cfg_patch = patch(
            "src.utils.utils_config.load_config",
            return_value={"script_list": script_list},
        )
        self._run_once_patch = patch(
            "src.service.chain_service.run_chain_once", return_value=None
        )
        self._run_once = self._run_once_patch.start()
        self._cfg = self._cfg_patch.start()
        self.addCleanup(self._run_once_patch.stop)
        self.addCleanup(self._cfg_patch.stop)
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

    def test_empty_selection_does_not_run(self):
        """enabled_keys 为空时直接跳过：不等待、不生成、不运行。"""
        with patch("src.service.chain_service.ScheduledRun") as run:
            chain_service.schedule_run(set(), "now", shutdown_delay=60)
        run.assert_not_called()

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
            shutdown_delay=60, smtp_config=None, unmute=False, enabled_keys={"demo"}
        )

    def test_mute_unmute_passed_to_pipelines(self):
        """mute/unmute 独立透传：mute→pre_run 工厂（挂静音 step），unmute→post_run 工厂（挂恢复）。"""
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
            chain_service.schedule_run({"demo"}, "08:00", mute=True, unmute=True)
        # mute 经 pre_run 工厂透传（由其挂静音 step）；unmute 经 post_run 工厂（挂恢复），
        # 两者互不依赖，均不再经 run_chain_once 透传。
        self.assertTrue(mock_pre.call_args.kwargs["mute"])
        self.assertNotIn("unmute", mock_pre.call_args.kwargs)
        mock_post.assert_called_once_with(
            shutdown_delay=None, smtp_config=None, unmute=True, enabled_keys={"demo"}
        )
        # 静音/恢复不再经 run_chain_once 透传
        _, kwargs = self._run_once.call_args
        self.assertNotIn("mute", kwargs)
        self.assertNotIn("unmute", kwargs)

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
            *, shutdown_delay, smtp_config, unmute=False, enabled_keys=None
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
            patch("src.log.notify_mail.send_mail") as mail,
            patch("src.service.schedule.shutdown_sys") as shutdown,
        ):
            steps = build_post_run_pipeline(**kwargs)
            for step in steps:
                step()
        return parse, mail, shutdown

    def test_post_run_respects_mail_and_shutdown_options(self):
        config = {"enabled": True, "email": "a@qq.com", "password": "pw"}
        for name, smtp, delay, rerun in (
            ("mail_and_shutdown", config, 60, ("demo",)),
            ("mail_only", config, None, ("demo",)),
            ("neither", None, None, ("demo",)),
            ("no_failures", None, None, ()),
        ):
            with self.subTest(name=name):
                parse, mail, shutdown = self._run(
                    rerun=rerun,
                    shutdown_delay=delay,
                    smtp_config=smtp,
                    enabled_keys={"demo"},
                )
                parse.assert_called_once_with(
                    do_log=False, candidate_script_names={"demo"}
                )
                if smtp is None:
                    mail.assert_not_called()
                else:
                    mail.assert_called_once_with(
                        self._result(rerun=rerun), smtp_config=smtp
                    )
                if delay is None:
                    shutdown.assert_not_called()
                else:
                    shutdown.assert_called_once_with(delay)


class TestRerunRound(unittest.TestCase):
    """chain_service.rerun_round：链结束后解析日志，对失败脚本二次运行（主流程）。

    逻辑已内联（不再经 src.log.rerun），此处直接验证其与 _run_chain_once_impl 的交互。
    """

    def _svc_with_config(self, script_list):
        self._cfg_patch = patch(
            "src.utils.utils_config.load_config",
            return_value={"script_list": script_list},
        )
        self._weekly_patch = patch(
            "src.service.chain_service.load_all_weekly", return_value={}
        )
        self._weekly_load = self._weekly_patch.start()
        self._cfg = self._cfg_patch.start()
        self.addCleanup(self._weekly_patch.stop)
        self.addCleanup(self._cfg_patch.stop)
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
