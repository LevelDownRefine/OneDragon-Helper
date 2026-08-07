"""测试 src/service/chain_service.py：无头测试，全部 mock 被包装函数。"""

import os
import tempfile
import unittest
from unittest.mock import patch

import yaml

from src.service.chain_service import ChainService


class TestLoadSaveConfig(unittest.TestCase):
    """config.yml 读写：转发 + 结构断言（用临时文件，不碰真实 config）"""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.config_path = os.path.join(self.tmp_dir.name, "config.yml")

    def test_load_config_reads_yaml(self):
        fake_data = {"script_list": [{"display_name": "测试"}]}
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(fake_data, f, allow_unicode=True)
        with patch(
            "src.service.chain_service.require_config_yml_path",
            return_value=self.config_path,
        ):
            data = ChainService().load_config()
        self.assertEqual(data, fake_data)

    def test_load_config_asserts_script_list(self):
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump({"a": 1}, f, allow_unicode=True)
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
        with open(self.config_path, encoding="utf-8") as f:
            saved = yaml.safe_load(f)
        self.assertEqual(saved["script_list"][0]["display_name"], "测试")

    def test_save_config_asserts_script_list(self):
        with self.assertRaises(AssertionError):
            ChainService().save_config({"a": 1})


class TestDungeonMap(unittest.TestCase):
    """dungeon_map：转发 load_dungeon_map 读取副本配置。"""

    @patch("src.service.chain_service.load_dungeon_map", return_value={"鸣潮": {}})
    def test_returns_dungeon_map(self, mock_load):
        self.assertEqual(ChainService().dungeon_map(), {"鸣潮": {}})
        mock_load.assert_called_once()


class TestChainGeneration(unittest.TestCase):
    """链生成与校验：转发"""

    def test_generate_chain_delegates(self):
        data = {"script_list": []}
        with patch(
            "src.service.chain_service._generate_chain_config", return_value="out.yml"
        ) as m:
            out = ChainService().generate_chain(data, {"A"}, "88", {"A": {}}, "out.yml")
        self.assertEqual(out, "out.yml")
        m.assert_called_once_with(data, {"A"}, "88", {"A": {}}, "out.yml")

    def test_collect_invalid_scripts_delegates(self):
        invalid = [("A", "游戏进程名称为空")]
        scripts = [{"display_name": "A"}]
        with patch(
            "src.service.chain_service.collect_invalid_script_messages",
            return_value=invalid,
        ) as m:
            self.assertEqual(ChainService().collect_invalid_scripts(scripts), invalid)
        m.assert_called_once_with(scripts)


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


if __name__ == "__main__":
    unittest.main()
