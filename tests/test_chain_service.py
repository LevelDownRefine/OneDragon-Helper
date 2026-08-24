"""测试 src/service/chain_service.py：无头测试，全部 mock 被包装函数。"""

import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from src.service.chain_service import ChainService
from src.service.scheduled_run import ScheduledRun, build_post_run_pipeline
from src.utils_yaml import dump_yaml_file, load_yaml


class TestLoadSaveConfig(unittest.TestCase):
    """config.yml 读写：转发 + 结构断言（用临时文件，不碰真实 config）"""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.config_path = os.path.join(self.tmp_dir.name, "config.yml")

    def test_load_config_reads_yaml(self):
        fake_data = {
            "script_list": [
                {"display_name": "测试", "script_path": "C:/x.exe"},
            ]
        }
        dump_yaml_file(self.config_path, fake_data)
        with patch(
            "src.service.chain_service.require_config_yml_path",
            return_value=self.config_path,
        ):
            data = ChainService().load_config()
        self.assertEqual(data, fake_data)

    def test_load_config_asserts_script_list(self):
        dump_yaml_file(self.config_path, {"a": 1})
        with (
            patch(
                "src.service.chain_service.require_config_yml_path",
                return_value=self.config_path,
            ),
            self.assertRaises(AssertionError),
        ):
            ChainService().load_config()

    def test_save_config_writes_yaml(self):
        with patch(
            "src.service.chain_service.get_config_yml_path_under_root",
            return_value=self.config_path,
        ):
            ChainService().save_config({"script_list": [{"display_name": "测试"}]})
        saved = load_yaml(self.config_path)
        self.assertEqual(saved["script_list"][0]["display_name"], "测试")

    def test_save_config_asserts_script_list(self):
        with self.assertRaises(AssertionError):
            ChainService().save_config({"a": 1})


class TestDungeonMap(unittest.TestCase):
    """dungeon_map：转发 load_dungeon_map 读取副本配置。"""

    @patch("src.service.chain_service.load_dungeon_map", return_value={"ok-ww": {}})
    def test_returns_dungeon_map(self, mock_load):
        self.assertEqual(ChainService().dungeon_map(), {"ok-ww": {}})
        mock_load.assert_called_once()


class TestChainGeneration(unittest.TestCase):
    """链生成与校验：转发"""

    def test_generate_chain_delegates(self):
        data = {"script_list": []}
        mock_script = MagicMock()
        mock_script.load_all_weekly.return_value = {}
        mock_script.get_weekly_start_map.return_value = {}
        with patch(
            "src.service.chain_service._generate_chain_config", return_value="out.yml"
        ) as m:
            out = ChainService(script_service=mock_script).generate_chain(
                data, {"A"}, "88", {"A": {}}, "out.yml"
            )
        self.assertEqual(out, "out.yml")
        m.assert_called_once_with(
            data,
            {"A"},
            "88",
            {"A": {}},
            "out.yml",
            weekly_timeouts={},
            weekly_start_map={},
        )

    def test_collect_invalid_scripts_delegates(self):
        invalid = [("A", "游戏进程名称为空")]
        scripts = [{"display_name": "A"}]
        with patch(
            "src.service.chain_service.collect_invalid_script_messages",
            return_value=invalid,
        ) as m:
            self.assertEqual(ChainService().collect_invalid_scripts(scripts), invalid)
        m.assert_called_once_with(scripts)


class TestGenerateChainWeeklyStart(unittest.TestCase):
    """generate_chain_config：weekly_start_map 的 weekly_start 原样传给 set_config（CLI 兜底，不判断今天）"""

    def _run_chain(self, weekly_start_map):
        from src.service import chain_gen

        data = {
            "script_list": [
                {
                    "display_name": "测试",
                    "script_path": "scripts/test.py",
                }
            ]
        }
        with (
            patch.object(chain_gen, "load_dungeon_map", return_value={"测试": {}}),
            patch.object(chain_gen, "set_config") as mock_set_config,
            patch(
                "src.service.chain_gen.safe_path_join",
                return_value="out.yml",
            ),
            patch(
                "src.service.chain_gen.get_path_under_root",
                return_value="root",
            ),
            patch("builtins.open"),
        ):
            chain_gen.generate_chain_config(
                data,
                {"测试"},
                weekly_start_map=weekly_start_map,
                out_path="out.yml",
            )
        return mock_set_config

    def test_weekly_start_passed_through(self):
        """weekly_start=4 → set_config 收到（CLI 无 GUI 时按周几兜底）"""
        mock = self._run_chain({"测试": 4})
        mock.assert_called_once_with(
            "测试",
            dungeon_name=None,
            sequence=None,
            weekly_start=4,
        )

    def test_no_weekly_start_skips(self):
        """未设置周常 → set_config(weekly_start=None)，不处理周常"""
        mock = self._run_chain({})
        mock.assert_called_once_with(
            "测试",
            dungeon_name=None,
            sequence=None,
            weekly_start=None,
        )


class TestRunChain(unittest.TestCase):
    """runner 命令：转发"""

    def test_build_chain_command_delegates(self):
        with patch(
            "src.service.chain_service._build_chain_command",
            return_value=(["py"], "cwd", None),
        ) as m:
            cmd, cwd, env = ChainService().build_chain_command(
                "88.yml", ["--shutdown", "60"]
            )
        self.assertEqual(cmd, ["py"])
        m.assert_called_once_with("88.yml", ["--shutdown", "60"])

    def test_run_chain_command_delegates(self):
        with patch("src.service.chain_service._run_chain_command", return_value=0) as m:
            code = ChainService().run_chain_command(
                "88.yml", block=False, extra_args=[]
            )
        self.assertEqual(code, 0)
        m.assert_called_once_with("88.yml", False, [])


class TestRunChainOnce(unittest.TestCase):
    """run_chain_once：生成+运行+关机/静音命令构造的 service 侧原子。"""

    def _make_service(self, script_list):
        svc = ChainService()
        svc.load_config = MagicMock(return_value={"script_list": script_list})
        svc.load_ui_state = MagicMock(return_value={})
        return svc

    def test_defaults_all_scripts_and_runs(self):
        svc = self._make_service([{"display_name": "A", "script_path": "A.exe"}])
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
            svc.run_chain_once()
        # 默认启用全部脚本、chain_name=today、不关机不静音
        gen.assert_called_once_with(
            {"script_list": [{"display_name": "A", "script_path": "A.exe"}]},
            {"A"},
            "today",
            {},
        )
        build.assert_called_once_with("out.yml", mute=False)
        run.assert_called_once()

    def test_subset_with_mute_launches_blocking(self):
        """阻塞启动：按子集生成+运行，mute 透传，返回 None。"""
        svc = self._make_service(
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
            result = svc.run_chain_once({"A"}, mute=True)
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
            {},
        )
        build.assert_called_once_with("out.yml", mute=True)
        run.assert_called_once()

    def test_empty_script_list_asserts(self):
        svc = self._make_service([])
        with self.assertRaises(AssertionError):
            svc.run_chain_once()

    def test_run_steps_isolates_step_failures(self):
        """ScheduledRun._run_steps：单步失败不影响后续步骤，均记日志。"""
        order = []

        def boom() -> None:
            raise RuntimeError("step failed")

        with patch("src.service.scheduled_run.logger") as mock_logger:
            ScheduledRun._run_steps(
                [lambda: order.append("a"), boom, lambda: order.append("b")]
            )
        self.assertEqual(order, ["a", "b"])
        mock_logger.exception.assert_called_once()


class TestScheduleRun(unittest.TestCase):
    """schedule_run：server 侧真实实现（等待→生成→运行→关机 post_run）。"""

    def _make_service(self, script_list):
        svc = ChainService()
        svc.load_config = MagicMock(
            return_value={"script_list": script_list, "rerun": {"enabled": True}}
        )
        svc.load_ui_state = MagicMock(return_value={})
        svc.run_chain_once = MagicMock(return_value=None)
        return svc

    def _run(self, svc, target_time="08:00", **kwargs):
        with (
            patch("src.service.scheduled_run.time.sleep") as mock_sleep,
            patch(
                "src.service.scheduled_run.next_target_datetime",
                return_value=datetime(2030, 1, 1, 8, 0),
            ),
            patch(
                "src.service.chain_service.parse_logs",
                return_value={"rerun": [], "notify": [], "report": "", "entries": []},
            ),
            patch("src.service.chain_service._run_chain_once_impl"),
            patch("src.service.scheduled_run.build_post_run_pipeline", return_value=[]),
            patch("src.service.scheduled_run.shutdown_sys") as mock_shutdown,
        ):
            svc.schedule_run({"demo"}, target_time, **kwargs)
        return mock_sleep, mock_shutdown

    def test_waits_generates_runs(self):
        svc = self._make_service([{"display_name": "demo"}])
        mock_sleep, mock_shutdown = self._run(svc)
        mock_sleep.assert_called_once()  # pre_run 等待
        # 第一次跑复用 run_chain_once，与重跑路径一致（仅脚本集合/链名不同）。
        svc.run_chain_once.assert_called_once_with(
            {"demo"}, chain_name="today", mute=False
        )
        mock_shutdown.assert_not_called()

    def test_shutdown_triggers_post_run(self):
        """shutdown_delay 非 None 时透传给 build_post_run_pipeline（末位挂关机 step）。"""
        svc = self._make_service([{"display_name": "demo"}])
        with (
            patch("src.service.scheduled_run.time.sleep"),
            patch(
                "src.service.scheduled_run.next_target_datetime",
                return_value=datetime(2030, 1, 1, 8, 0),
            ),
            patch("src.service.chain_service.parse_logs", return_value={"rerun": []}),
            patch("src.service.chain_service._run_chain_once_impl"),
            patch("src.service.scheduled_run.build_post_run_pipeline") as mock_pipeline,
        ):
            svc.schedule_run({"demo"}, "08:00", shutdown_delay=60)
        mock_pipeline.assert_called_once_with(shutdown_delay=60, smtp_config=None)

    def test_mute_passed(self):
        svc = self._make_service([{"display_name": "demo"}])
        self._run(svc, mute=True)
        svc.run_chain_once.assert_called_once_with(
            {"demo"}, chain_name="today", mute=True
        )

    def test_now_skips_wait(self):
        """target_time='now'（即时运行）跳过等待，直接点火运行。"""
        svc = self._make_service([{"display_name": "demo"}])
        with (
            patch("src.service.scheduled_run.time.sleep") as mock_sleep,
            patch(
                "src.service.scheduled_run.next_target_datetime",
                return_value=datetime(2030, 1, 1, 8, 0),
            ),
            patch(
                "src.service.chain_service.parse_logs",
                return_value={"rerun": [], "notify": [], "report": "", "entries": []},
            ),
            patch("src.service.chain_service._run_chain_once_impl"),
            patch("src.service.scheduled_run.shutdown_sys"),
        ):
            svc.schedule_run({"demo"}, "now")
        mock_sleep.assert_not_called()  # 即时：不等待
        svc.run_chain_once.assert_called_once()  # 仍点火运行

    def test_no_shutdown_when_none(self):
        svc = self._make_service([{"display_name": "demo"}])
        _, mock_shutdown = self._run(svc, shutdown_delay=None)
        mock_shutdown.assert_not_called()

    def test_rerun_round_before_post_run(self):
        """schedule_run：链跑完后先重跑失败脚本，再执行 post_run（邮件/关机）。"""
        svc = self._make_service([{"display_name": "demo"}])
        order = []
        with (
            patch("src.service.scheduled_run.time.sleep"),
            patch(
                "src.service.scheduled_run.next_target_datetime",
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
                "src.service.scheduled_run.build_post_run_pipeline",
                return_value=[lambda: order.append("mail")],
            ),
        ):
            svc.schedule_run({"demo"}, "08:00", shutdown_delay=60)
        self.assertEqual(order, ["rerun", "mail"])

    def test_rerun_skipped_when_disabled(self):
        """config.rerun.enabled=false：链跑完后不进入重跑轮。"""
        svc = self._make_service([{"display_name": "demo"}])
        svc.load_config = MagicMock(
            return_value={
                "script_list": [{"display_name": "demo"}],
                "rerun": {"enabled": False},
            }
        )
        with (
            patch("src.service.scheduled_run.time.sleep"),
            patch(
                "src.service.scheduled_run.next_target_datetime",
                return_value=datetime(2030, 1, 1, 8, 0),
            ),
            patch("src.service.chain_service._run_chain_once_impl") as rerun,
            patch("src.service.scheduled_run.build_post_run_pipeline", return_value=[]),
        ):
            svc.schedule_run({"demo"}, "08:00")
        rerun.assert_not_called()

    def test_mail_skipped_when_disabled(self):
        """notify.enabled=false：传给 build_post_run_pipeline 的 smtp_config 为 None（不发信）。"""
        svc = self._make_service([{"display_name": "demo"}])
        svc.load_config = MagicMock(
            return_value={
                "script_list": [{"display_name": "demo"}],
                "rerun": {"enabled": True},
                "notify": {"enabled": False, "email": "a@qq.com", "password": "pw"},
            }
        )
        captured = {}

        def _fake_pipeline(*, shutdown_delay, smtp_config):
            captured["smtp_config"] = smtp_config
            return []

        with (
            patch("src.service.scheduled_run.time.sleep"),
            patch(
                "src.service.scheduled_run.next_target_datetime",
                return_value=datetime(2030, 1, 1, 8, 0),
            ),
            patch(
                "src.service.chain_service.parse_logs",
                return_value={"rerun": [], "notify": [], "report": "", "entries": []},
            ),
            patch(
                "src.service.scheduled_run.build_post_run_pipeline",
                side_effect=_fake_pipeline,
            ) as pipeline,
        ):
            svc.schedule_run({"demo"}, "08:00")
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
                "src.service.scheduled_run.parse_logs",
                return_value=self._result(rerun=rerun, notify=notify),
            ) as parse,
            patch("src.service.scheduled_run.send_mail") as mail,
            patch("src.service.scheduled_run.shutdown_sys") as shutdown,
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
        parse.assert_any_call(do_log=False)
        self.assertEqual(parse.call_count, 1)  # 仅最终态分析
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


class TestRerunRound(unittest.TestCase):
    """ChainService._rerun_round：链结束后解析日志，对失败脚本二次运行（主流程）。

    逻辑已内联（不再经 src.log.rerun），此处直接验证其与 _run_chain_once_impl 的交互。
    """

    def _svc_with_config(self, script_list):
        svc = ChainService()
        svc.load_config = MagicMock(return_value={"script_list": script_list})
        return svc

    def test_reruns_when_rerun_list_nonempty(self):
        """parse_logs 产出 rerun 非空 → 以 chain_name='rerun' 阻塞重跑失败子集。"""
        svc = self._svc_with_config([{"display_name": "demo", "script_path": "demo"}])
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
            svc._rerun_round(mute=True, all_config=svc.load_config())
        run_impl.assert_called_once()
        args, kwargs = run_impl.call_args
        self.assertEqual(args[1], {"demo"})  # 启用脚本集合
        self.assertEqual(kwargs["chain_name"], "rerun")
        self.assertTrue(kwargs["mute"])

    def test_no_rerun_when_list_empty(self):
        """rerun 为空列表 → _run_chain_once_impl 不调用。"""
        svc = self._svc_with_config([{"display_name": "demo", "script_path": "demo"}])
        with (
            patch(
                "src.service.chain_service.parse_logs",
                return_value={"rerun": [], "notify": [], "report": "", "entries": []},
            ),
            patch("src.service.chain_service._run_chain_once_impl") as run_impl,
        ):
            svc._rerun_round(all_config=svc.load_config())
        run_impl.assert_not_called()

    def test_filters_unknown_script_names(self):
        """rerun_list 含不在 config 的脚本名时，仅对已知脚本重跑。"""
        svc = self._svc_with_config([{"display_name": "demo", "script_path": "demo"}])
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
            svc._rerun_round(all_config=svc.load_config())
        run_impl.assert_called_once()
        args, _ = run_impl.call_args
        self.assertEqual(args[1], {"demo"})  # 过滤掉的 ghost 不在 config


class TestAddRemoveScript(unittest.TestCase):
    """add_script / remove_script / update_script：操作 config.yml 并同步 weekly。"""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.config_path = os.path.join(self.tmp_dir.name, "config.yml")
        dump_yaml_file(
            self.config_path,
            {"script_list": [{"display_name": "原神", "script_path": "C:/a.exe"}]},
        )
        self.mock_script = MagicMock()

    def _read(self):
        return load_yaml(self.config_path)

    def test_add_script_appends(self):
        """add_script 在 script_list 末尾追加条目、落盘，并内部调 ensure_weekly_entry。"""
        with (
            patch(
                "src.service.chain_service.require_config_yml_path",
                return_value=self.config_path,
            ),
            patch(
                "src.service.chain_service.get_config_yml_path_under_root",
                return_value=self.config_path,
            ),
        ):
            ChainService(script_service=self.mock_script).add_script(
                {"display_name": "鸣潮", "script_path": "C:/b.exe"}
            )
        names = [s["display_name"] for s in self._read()["script_list"]]
        self.assertEqual(names, ["原神", "鸣潮"])
        self.mock_script.ensure_weekly_entry.assert_called_once_with("b")

    def test_remove_script_removes(self):
        """remove_script 从 script_list 移除指定进程条目、落盘，并内部清 weekly 孤儿。"""
        with (
            patch(
                "src.service.chain_service.require_config_yml_path",
                return_value=self.config_path,
            ),
            patch(
                "src.service.chain_service.get_config_yml_path_under_root",
                return_value=self.config_path,
            ),
        ):
            ChainService(script_service=self.mock_script).remove_script("a")
        self.assertEqual(self._read()["script_list"], [])
        self.mock_script.delete_weekly.assert_called_once_with("a")

    def test_remove_script_missing_raises(self):
        """remove_script 移除不存在的脚本属非法调用：assert 表达不该发生"""
        with (
            patch(
                "src.service.chain_service.require_config_yml_path",
                return_value=self.config_path,
            ),
            patch(
                "src.service.chain_service.get_config_yml_path_under_root",
                return_value=self.config_path,
            ),
            self.assertRaises(AssertionError),
        ):
            ChainService(script_service=self.mock_script).remove_script("不存在")


if __name__ == "__main__":
    unittest.main()
