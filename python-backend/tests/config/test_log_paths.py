"""日志路径解析及实时日志与分析报告的消费边界。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import link
from src.log import monitor
from src.service.chain_gen import generate_chain_config
from src.utils import utils_sub_config
from src.utils.utils_io import load_data, save_data
from src.utils.utils_sub_config import resolve_log_path


class TestLogPaths(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.declaration = self.root / "config/log_analysis.yml"
        self.declaration.parent.mkdir()
        self.enterContext(
            patch.object(utils_sub_config, "get_root_dir", return_value=str(self.root))
        )

    def declare(self, settings, name="工具"):
        save_data(self.declaration, {"parsers": {name: settings}}, file_format="yaml")

    def test_log_path_forms_and_analysis_fallback(self):
        with patch.object(
            utils_sub_config.tempfile, "gettempdir", return_value=str(self.root)
        ):
            for script_path, log_path, expected in (
                ("tools/工具.exe", "logs/*.log", self.root / "tools/logs/*.log"),
                ("工具.exe", str(self.root / "custom.log"), self.root / "custom.log"),
                ("工具.exe", "%TEMP%/task/*.txt", self.root / "task/*.txt"),
                (r"D:\游戏\工具.exe", r"logs\run.log", Path("D:/游戏/logs/run.log")),
                ("工具.exe", "", None),
            ):
                with self.subTest(script_path=script_path, log_path=log_path):
                    self.declare({"log_path": log_path})
                    script = {"script_path": script_path}
                    self.assertEqual(resolve_log_path(script), expected)
                    self.assertEqual(resolve_log_path(script, analysis=True), expected)

    def test_invalid_type_and_directory_globs_are_rejected(self):
        for value in (None, "logs/*/run.log"):
            with self.subTest(value=value):
                self.declare({"log_path": value})
                with self.assertRaises(ValueError):
                    resolve_log_path({"script_path": "工具.exe"})

    def test_analysis_uses_report_while_chain_and_log_link_use_live_file(self):
        live = self.root / "logs"
        reports = self.root / "reports"
        live.mkdir()
        reports.mkdir()
        (live / "runtime.log").write_text("still running", encoding="utf-8")
        report = reports / "result.txt"
        report.write_text("成功任务:\n  ⭐日常奖励", encoding="utf-8")
        script = {"display_name": "终末地", "script_path": str(self.root / "ok-ef.exe")}
        self.declare(
            {"log_path": "logs/runtime.log", "log_analysis_path": "reports/*.txt"},
            "ok-ef",
        )
        config = {"script_list": [script]}
        save_data(self.root / "config/config.yml", config, file_format="yaml")
        with (
            patch.object(monitor, "get_root_dir", return_value=str(self.root)),
            patch.object(monitor, "setup_logging"),
            patch.object(link, "get_script", return_value=script),
        ):
            result = monitor.parse_logs(do_log=False, candidate_script_names={"ok-ef"})
            self.assertEqual(result["entries"][0]["result"]["log_path"], str(report))
            self.assertTrue(result["entries"][0]["result"]["daily_done"])
            self.assertEqual(
                link.resolve_script_target("ok-ef", "log"),
                {"kind": "path", "value": str(live)},
            )
        chain = self.root / "chain.yml"
        generate_chain_config(config, {"ok-ef"}, out_path=str(chain))
        saved = load_data(chain, file_format="yaml")["script_list"][0]
        self.assertEqual(saved["log_path"], str(live / "runtime.log"))
        self.assertNotIn("log_analysis_path", saved)


if __name__ == "__main__":
    unittest.main()
