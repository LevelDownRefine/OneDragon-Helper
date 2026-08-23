"""测试 src/service/chain_service.py：无头测试，全部 mock 被包装函数。"""

import os
import tempfile
import unittest
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
