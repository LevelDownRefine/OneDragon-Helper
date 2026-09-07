"""测试 src/config/generate_config.py：首启生成与损坏兜底。

三个生成物（config/schedule/weekly.yml）是用户可手改的外部文件：损坏属可恢复
外部输入——改名保留 .bak 留现场，从模板重建使用户无感恢复（GUI 不崩在坏文件上）。
"""

import os
import tempfile
import unittest
from unittest.mock import patch

from src.config import generate_config
from src.config.generate_config import config_workflow
from src.utils.utils_yaml import load_yaml


class ConfigWorkflowTestBase(unittest.TestCase):
    """用临时 config/ 目录隔离真实文件，内含三个模板。"""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.config_dir = os.path.join(self.tmp_dir.name, "config")
        os.makedirs(self.config_dir)
        self._write(
            "config.example.yml",
            "script_list:\n  - display_name: 示例\n    script_path: C:/demo.exe\n",
        )
        self._write(
            "schedule.example.yml",
            "rerun:\n  enabled: false\nnotify:\n  enabled: false\ntimed_run:\n  enabled: false\n  target_time: ''\n",
        )
        self._write("weekly.example.yml", "weekly_start: {}\nweekly_timeouts: {}\n")

        patchers = [
            patch.object(
                generate_config, "get_root_dir", return_value=self.tmp_dir.name
            ),
            patch.object(
                generate_config,
                "get_config_yml_path_under_root",
                return_value=os.path.join(self.config_dir, "config.yml"),
            ),
            patch.object(
                generate_config,
                "get_schedule_yml_path_under_root",
                return_value=os.path.join(self.config_dir, "schedule.yml"),
            ),
            patch.object(
                generate_config,
                "get_weekly_yml_path_under_root",
                return_value=os.path.join(self.config_dir, "weekly.yml"),
            ),
            patch("src.config.set_config.init_config_all"),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)

    def _write(self, name: str, text: str) -> None:
        with open(os.path.join(self.config_dir, name), "w", encoding="utf-8") as f:
            f.write(text)

    def _read_text(self, name: str) -> str:
        with open(os.path.join(self.config_dir, name), encoding="utf-8") as f:
            return f.read()

    def _path(self, name: str) -> str:
        return os.path.join(self.config_dir, name)


class TestConfigWorkflowGenerate(ConfigWorkflowTestBase):
    def test_missing_files_generated(self):
        config_workflow()
        self.assertTrue(os.path.exists(self._path("config.yml")))
        self.assertTrue(os.path.exists(self._path("schedule.yml")))
        self.assertTrue(os.path.exists(self._path("weekly.yml")))
        self.assertEqual(
            load_yaml(self._path("config.yml"))["script_list"][0]["display_name"],
            "示例",
        )

    def test_valid_files_not_touched(self):
        """已存在且合法的生成物不被覆盖（用户数据是权威）。"""
        self._write(
            "config.yml",
            "script_list:\n  - display_name: 我改过\n    script_path: C:/x.exe\n",
        )
        config_workflow()
        self.assertIn("我改过", self._read_text("config.yml"))
        self.assertFalse(os.path.exists(self._path("config.yml.bak")))


class TestConfigWorkflowCorruption(ConfigWorkflowTestBase):
    """损坏 → 记日志、改名 .bak 保留现场、从模板重建。"""

    def test_corrupt_config_recovered(self):
        self._write("config.yml", "{{{ broken yaml: [")
        config_workflow()
        # 重建后的 config.yml 可解析且含模板 script_list
        self.assertEqual(
            load_yaml(self._path("config.yml"))["script_list"][0]["display_name"],
            "示例",
        )
        # 损坏现场保留
        self.assertIn("broken yaml", self._read_text("config.yml.bak"))

    def test_corrupt_schedule_recovered(self):
        self._write("schedule.yml", "rerun: [unclosed")
        config_workflow()
        self.assertIn("rerun", load_yaml(self._path("schedule.yml")))
        self.assertTrue(os.path.exists(self._path("schedule.yml.bak")))

    def test_corrupt_weekly_recovered(self):
        self._write("weekly.yml", "weekly_start: {")
        config_workflow()
        self.assertIn("weekly_timeouts", load_yaml(self._path("weekly.yml")))
        self.assertTrue(os.path.exists(self._path("weekly.yml.bak")))

    def test_existing_bak_not_clobbered(self):
        """已有 .bak 时顺延 .bak2，不覆盖旧备份（约定：不动备份文件）。"""
        self._write("config.yml", "{{{ broken")
        self._write("config.yml.bak", "旧备份内容")
        config_workflow()
        self.assertEqual(self._read_text("config.yml.bak"), "旧备份内容")
        self.assertIn("broken", self._read_text("config.yml.bak2"))


if __name__ == "__main__":
    unittest.main()
