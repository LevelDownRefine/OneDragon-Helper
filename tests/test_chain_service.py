"""测试 src/service/chain_service.py：无头测试，全部 mock 被包装函数。"""

import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from src.service.chain_service import ChainService
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
        svc.generate_chain = MagicMock(return_value="out.yml")
        return svc

    def test_defaults_all_scripts_and_popens(self):
        svc = self._make_service([{"display_name": "A"}])
        with (
            patch(
                "src.service.chain_service._build_run_chain_command",
                return_value=(["cmd"], "cwd", None),
            ) as build,
            patch("src.service.chain_service.subprocess.Popen") as popen,
        ):
            svc.run_chain_once()
        # 默认启用全部脚本、chain_name=today、不关机不静音
        svc.generate_chain.assert_called_once_with(
            {"script_list": [{"display_name": "A"}]}, {"A"}, "today", {}
        )
        build.assert_called_once_with("out.yml", mute=False)
        popen.assert_called_once()

    def test_subset_with_mute_launches_nonblocking(self):
        """非阻塞启动：按子集生成+运行，mute 透传，返回 None，后台线程启动。"""
        svc = self._make_service([{"display_name": "A"}, {"display_name": "B"}])
        with (
            patch(
                "src.service.chain_service._build_run_chain_command",
                return_value=(["cmd"], "cwd", None),
            ) as build,
            patch("src.service.chain_service.subprocess.Popen") as popen,
            patch("src.service.chain_service.threading.Thread") as thread,
        ):
            result = svc.run_chain_once({"A"}, mute=True)
        self.assertIsNone(result)
        svc.generate_chain.assert_called_once_with(
            {"script_list": [{"display_name": "A"}, {"display_name": "B"}]},
            {"A"},
            "today",
            {},
        )
        build.assert_called_once_with("out.yml", mute=True)
        popen.assert_called_once()
        thread.assert_called_once()

    def test_run_executes_post_run_after_chain(self):
        """post_run 在链运行结束后（无论成败）按序触发（非阻塞 watcher 线程）。"""
        svc = self._make_service([{"display_name": "A"}])
        order = []

        def step() -> None:
            order.append("done")

        class _SyncThread:
            """测试替身：start() 同步执行目标，避免后台线程泄漏。"""

            def __init__(self, target=None, args=(), kwargs=None, daemon=None):
                self._target = target
                self._args = args
                self._kwargs = kwargs or {}

            def start(self):
                self._target(*self._args, **self._kwargs)

            def join(self, *a, **k):
                pass

        with (
            patch(
                "src.service.chain_service._build_run_chain_command",
                return_value=(["cmd"], "cwd", None),
            ),
            patch(
                "src.service.chain_service.subprocess.Popen",
                return_value=MagicMock(),
            ),
            patch("src.service.chain_service.threading.Thread", _SyncThread),
        ):
            svc.run_chain_once({"A"}, post_run=[step])
        self.assertEqual(order, ["done"])

    def test_empty_script_list_asserts(self):
        svc = self._make_service([])
        with self.assertRaises(AssertionError):
            svc.run_chain_once()


class TestScheduleRun(unittest.TestCase):
    """schedule_run：server 侧真实实现（等待→生成→运行→关机 post_run）。"""

    def _make_service(self, script_list):
        svc = ChainService()
        svc.load_config = MagicMock(return_value={"script_list": script_list})
        svc.load_ui_state = MagicMock(return_value={})
        svc.generate_chain = MagicMock(return_value="out.yml")
        svc.run_chain_command = MagicMock(return_value=0)
        return svc

    def _run(self, svc, target_time="08:00", **kwargs):
        with (
            patch("src.service.chain_service.time.sleep") as mock_sleep,
            patch(
                "src.service.chain_service.next_target_datetime",
                return_value=datetime(2030, 1, 1, 8, 0),
            ),
            patch("src.service.chain_service.shutdown_sys") as mock_shutdown,
        ):
            svc.schedule_run({"demo"}, target_time, **kwargs)
        return mock_sleep, mock_shutdown

    def test_waits_generates_runs(self):
        svc = self._make_service([{"display_name": "demo"}])
        mock_sleep, mock_shutdown = self._run(svc)
        mock_sleep.assert_called_once()  # pre_run 等待
        svc.generate_chain.assert_called_once()
        args = svc.generate_chain.call_args
        self.assertEqual(args.args[1], {"demo"})  # 启用脚本集合
        self.assertEqual(args.args[2], "today")  # chain_name
        svc.run_chain_command.assert_called_once_with(
            "out.yml", block=True, extra_args=None
        )
        mock_shutdown.assert_not_called()

    def test_shutdown_triggers_post_run(self):
        svc = self._make_service([{"display_name": "demo"}])
        _, mock_shutdown = self._run(svc, shutdown_delay=60)
        mock_shutdown.assert_called_once_with(60)

    def test_mute_passed(self):
        svc = self._make_service([{"display_name": "demo"}])
        self._run(svc, mute=True)
        svc.run_chain_command.assert_called_once_with(
            "out.yml", block=True, extra_args=["--mute"]
        )

    def test_no_shutdown_when_none(self):
        svc = self._make_service([{"display_name": "demo"}])
        _, mock_shutdown = self._run(svc, shutdown_delay=None)
        mock_shutdown.assert_not_called()


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
