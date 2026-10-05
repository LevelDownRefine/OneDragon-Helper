"""日志声明：路径解析、运行链注入及分析/跳转共用；读写均使用临时目录。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import link
from src.log import monitor
from src.service.chain_gen import generate_chain_config
from src.utils import utils_sub_config
from src.utils.utils_io import load_data, save_data
from src.utils.utils_sub_config import (
    default_script_entry,
    get_log_paths,
    resolve_log_path,
)


class TestLogPaths(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.exe = self.root / "工具.exe"
        self.declaration = self.root / "config/log_analysis.yml"
        self.declaration.parent.mkdir()
        self.enterContext(
            patch.object(utils_sub_config, "get_root_dir", return_value=str(self.root))
        )

    def declare(self, settings, name="工具"):
        save_data(self.declaration, {"parsers": {name: settings}}, file_format="yaml")

    def test_relative_absolute_temp_and_project_relative_paths(self):
        with patch.object(
            utils_sub_config.tempfile, "gettempdir", return_value=str(self.root)
        ):
            for script_path, log_path, expected in (
                (str(self.exe), "logs/*.log", self.root / "logs/*.log"),
                (
                    str(self.exe),
                    str(self.root / "custom.log"),
                    self.root / "custom.log",
                ),
                (
                    str(self.exe),
                    "%TEMP%/报告/日常_*.txt",
                    self.root / "报告/日常_*.txt",
                ),
                ("tools/工具.exe", "logs/run.log", self.root / "tools/logs/run.log"),
                (r"D:\游戏\工具.exe", r"logs\run.log", Path("D:/游戏/logs/run.log")),
                (str(self.exe), r"E:\其它目录\run.log", Path("E:/其它目录/run.log")),
                (
                    str(self.exe),
                    "logs [中文]/run.log",
                    self.root / "logs [中文]/run.log",
                ),
            ):
                with self.subTest(script_path=script_path, log_path=log_path):
                    self.declare({"log_path": log_path})
                    script = {"script_path": script_path}
                    self.assertEqual(resolve_log_path(script), expected)
                    self.assertEqual(resolve_log_path(script, analysis=True), expected)

    def test_analysis_override_empty_and_unknown_paths(self):
        script = {"script_path": str(self.exe)}
        self.declare({"log_path": "live.log", "log_analysis_path": "report_*.txt"})
        self.assertEqual(resolve_log_path(script), self.root / "live.log")
        self.assertEqual(
            resolve_log_path(script, analysis=True), self.root / "report_*.txt"
        )
        self.declare({"log_path": "live.log", "log_analysis_path": ""})
        self.assertIsNone(resolve_log_path(script, analysis=True))
        self.assertEqual(resolve_log_path(script), self.root / "live.log")
        for value in ({}, {"log_path": ""}, {"log_path": "  "}):
            with self.subTest(value=value):
                self.declare(value)
                self.assertIsNone(resolve_log_path(script))
        self.assertEqual(get_log_paths("unknown"), {})
        self.assertIsNone(
            resolve_log_path({"script_path": "unknown.exe", "log_path": "stale.log"})
        )

    def test_invalid_type_and_directory_globs_are_rejected(self):
        for value in (None, [], 10, "**/run.log", "logs/*/run.log", "logs/**"):
            with self.subTest(value=value):
                self.declare({"log_path": value})
                with self.assertRaises(ValueError):
                    resolve_log_path({"script_path": str(self.exe)})

    def test_declaration_changes_take_effect_and_old_entry_fields_are_ignored(self):
        script = {
            "script_path": str(self.exe),
            "log_path": "old.log",
            "log_analysis_path": "old.txt",
        }
        self.declare({"log_path": "first.log", "error_markers": ["ERROR"]})
        settings = get_log_paths("工具")
        self.assertEqual(settings, {"log_path": "first.log"})
        settings["log_path"] = "mutated.log"
        self.assertEqual(resolve_log_path(script), self.root / "first.log")
        self.declare({"log_path": "second.log"})
        self.assertEqual(resolve_log_path(script), self.root / "second.log")
        self.assertEqual(
            resolve_log_path(script, analysis=True), self.root / "second.log"
        )
        self.assertEqual(script["log_path"], "old.log")

    def test_new_entries_do_not_copy_fixed_log_paths_into_user_config(self):
        for name in ("ok-ww", "ok-ef", "MaaEnd", "unknown"):
            with self.subTest(name=name):
                entry = default_script_entry(
                    "用户名字", "external", str(self.root / f"{name}.exe")
                )
                self.assertNotIn("log_path", entry)
                self.assertNotIn("log_analysis_path", entry)
                self.assertEqual(entry["no_log_timeout_seconds"], 0)
                self.assertEqual(entry["display_name"], "用户名字")

    def test_analysis_uses_report_while_chain_and_log_link_use_live_file(self):
        live = self.root / "实时日志"
        reports = self.root / "reports"
        live.mkdir()
        reports.mkdir()
        (live / "runtime.log").write_text("still running", encoding="utf-8")
        report = reports / "result.txt"
        report.write_text("成功任务:\n  ⭐日常奖励", encoding="utf-8")
        script = {"display_name": "终末地", "script_path": str(self.root / "ok-ef.exe")}
        self.declare(
            {"log_path": "实时日志/runtime.log", "log_analysis_path": "reports/*.txt"},
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
            self.assertEqual(result["rerun"], [])
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
        self.assertNotIn("log_path", script)


class TestBundledLogPaths(unittest.TestCase):
    def test_maa_declarations_reach_runner_and_gui_without_parser(self):
        for name, log_file in (("MAA", "asst.log"), ("MaaEnd", "maafw.log")):
            with self.subTest(script=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                script = {
                    "script_path": str(root / f"{name}.exe"),
                    "display_name": "自定义名字",
                    "no_log_timeout_seconds": 300,
                    "no_log_max_retries": 1,
                }
                (root / "debug").mkdir()
                (root / f"{name}.exe").touch()
                # GUI 日志已有旧内容，运行链仍须选择核心日志，即使它尚未创建。
                (root / "debug/gui.log").write_text("old GUI message", encoding="utf-8")
                expected = root / "debug" / log_file
                self.assertEqual(resolve_log_path(script), expected)
                with patch.object(link, "get_script", return_value=script):
                    self.assertEqual(
                        link.resolve_script_target(name, "log"),
                        {"kind": "path", "value": str(expected.parent)},
                    )
                chain = root / "chain.yml"
                generate_chain_config(
                    {"script_list": [script]},
                    {name},
                    out_path=str(chain),
                    weekly_timeouts={name: [1800] * 7},
                )
                saved = load_data(chain, file_format="yaml")["script_list"][0]
                self.assertEqual(saved["log_path"], str(expected))
                self.assertEqual(saved["no_log_timeout_seconds"], 300)
                self.assertEqual(saved["no_log_max_retries"], 1)
                self.assertEqual(saved["run_timeout_seconds"], 1800)


if __name__ == "__main__":
    unittest.main()
