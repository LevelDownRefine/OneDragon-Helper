"""Exercise the skill against real backend modules in fresh CLI processes."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
SKILL_DIR = Path(
    os.environ.get("ODH_SKILL_DIR", str(PROJECT / ".agents/skills/onedragon-helper"))
)


class SkillInspectTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.install = self.root / "安装目录"
        self.install.mkdir()
        self.write(
            "config/config.yml",
            "script_list:\n"
            "- display_name: 鸣潮\n  script_path: game/ok-ww.exe\n"
            "  script_arguments: private\n"
            "- display_name: 崩铁\n  script_path: 'other/March7th Launcher.EXE'\n"
            "- display_name: 自定义\n  script_path: tools/job.py\n",
        )
        self.write(
            "config/script_resources.yml",
            "version: 1\nscripts:\n  ok-ww:\n    backup_paths: [config]\n"
            "    links:\n      github: https://github.com/example/game\n"
            "      homepage: https://example.com/game\n"
            "      bilibili: https://example.com/video\n",
        )
        self.write(
            "config/log_analysis.yml",
            "parsers:\n  ok-ww:\n    log_path: logs/run.log\n"
            "    daily_success_marker: [INSTALLATION_COMPLETE]\n"
            "    error_markers: [ERROR]\n"
            "  March7th-Launcher:\n    log_path: logs/run.log\n"
            "    log_analysis_path: ''\n",
        )
        self.write("version.json", '{"version":"old-exe"}')

    def write(self, name, content):
        path = self.install / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def call(self, *arguments, source=None, expected=0):
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(SKILL_DIR / "scripts/odh.py"),
                "--source",
                str(source if source is not None else PROJECT),
                "--install",
                str(self.install),
                *arguments,
            ],
            cwd=self.root,
            capture_output=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, expected, result.stderr + result.stdout)
        return json.loads(result.stdout)

    def snapshot(self, root):
        return {
            str(p.relative_to(root)): p.read_bytes()
            for p in root.rglob("*")
            if p.is_file()
        }

    def test_identity_and_paths_use_backend_and_installation(self):
        entries = self.call("list")["scripts"]
        self.assertEqual(
            [s["script_name"] for s in entries],
            ["ok-ww", "March7th-Launcher", "自定义"],
        )
        data = self.call("inspect", "--script", "ok-ww", "--script", "自定义")
        script = data["scripts"][0]
        self.assertEqual(script["repository"]["url"], "https://github.com/example/game")
        self.assertEqual(Path(script["script_directory"]), self.install / "game")
        self.assertEqual(
            Path(script["log_patterns"]["analysis"]), self.install / "game/logs/run.log"
        )
        self.assertNotIn("script_arguments", script)
        self.assertIsNone(data["scripts"][1]["repository"]["url"])
        self.assertEqual(data["helper_version"]["version"], "old-exe")
        self.assertEqual(Path(data["source"]["path"]), PROJECT)

    def test_analysis_uses_installation_rules_and_never_initializes_or_cleans(self):
        # A copied source tree carries conflicting declarations and no Git metadata.
        source = self.root / "downloaded"
        shutil.copytree(
            PROJECT / "python-backend/src",
            source / "python-backend/src",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        (source / "config").mkdir()
        (source / "config/log_analysis.yml").write_text(
            "parsers:\n  ok-ww:\n    daily_success_marker: [SOURCE_ONLY]\n",
            encoding="utf-8",
        )
        self.write("game/logs/run.log", "INSTALLATION_COMPLETE\nERROR intermittent\n")
        old = self.write("logs/onedragon_helper.plan-2000-01-01.log", "keep")
        os.utime(old, (1, 1))
        before = self.snapshot(self.install)
        source_before = self.snapshot(source)
        data = self.call("analyze", "--script", "ok-ww", source=source)
        entry = data["scripts"][0]
        self.assertTrue(entry["daily_completion_checkable"])
        self.assertTrue(entry["result"]["daily_done"])
        self.assertEqual(entry["result"]["errors"], ["ERROR intermittent"])
        self.assertEqual(before, self.snapshot(self.install))
        self.assertEqual(source_before, self.snapshot(source))

    def test_unknown_disabled_and_missing_log_are_distinct(self):
        data = self.call(
            "analyze",
            "--script",
            "自定义",
            "--script",
            "March7th-Launcher",
            "--script",
            "ok-ww",
        )["scripts"]
        self.assertEqual(data[0]["reason"], "unsupported_parser")
        self.assertIsNone(data[0]["result"])
        self.assertEqual(data[1]["reason"], "analysis_log_not_configured")
        self.assertEqual(data[2]["result"]["status"], "NoLog")

    def test_no_completion_rule_does_not_claim_checkable(self):
        self.write(
            "config/log_analysis.yml",
            "parsers:\n  ok-ww:\n    log_path: logs/run.log\n",
        )
        self.write("game/logs/run.log", "ordinary line")
        data = self.call("analyze", "--script", "ok-ww")["scripts"][0]
        self.assertFalse(data["daily_completion_checkable"])
        self.assertTrue(data["result"]["daily_done"])

    def test_corrupt_and_incompatible_declarations_surface_without_repair(self):
        path = self.write("config/config.yml", "script_list: [")
        before = self.snapshot(self.install)
        self.assertIn("error", self.call("list", expected=1))
        self.assertEqual(path.read_text(encoding="utf-8"), "script_list: [")
        self.assertEqual(before, self.snapshot(self.install))
        self.write("config/config.yml", "script_list: []")
        self.write("config/script_resources.yml", "scripts: {}")
        self.assertEqual(
            self.call("inspect", "--script", "ok-ww", expected=1)["type"],
            "AssertionError",
        )

    def test_game_logs_without_repository_and_helper_logs_without_source(self):
        (self.install / "config/script_resources.yml").unlink()
        path = self.write("game/logs/run.log", "evidence")
        self.assertEqual(
            self.call("logs", "--script", "ok-ww", "--kind", "analysis")["files"][0][
                "path"
            ],
            str(path),
        )
        helper = self.write("logs/onedragon_helper.plan-2026-10-28.log", "diagnostic")
        (self.install / "config/config.yml").unlink()
        data = self.call("logs", "--kind", "helper", source=self.root / "absent-source")
        self.assertEqual(data["files"][0]["path"], str(helper))

    def test_duplicate_identity_and_unknown_selection_rejected(self):
        self.assertIn(
            "use list first",
            self.call("inspect", "--script", "鸣潮", expected=1)["error"],
        )
        self.write(
            "config/config.yml",
            "script_list:\n- display_name: a\n  script_path: a/game.exe\n"
            "- display_name: b\n  script_path: b/game.exe\n",
        )
        self.assertIn("duplicate", self.call("list", expected=1)["error"])

    def test_preloaded_backend_rejected(self):
        code = (
            "import sys; from pathlib import Path; "
            "sys.path.insert(0, sys.argv[1]); import odh; "
            "sys.path.insert(0, sys.argv[2] + '/python-backend'); import src.utils; "
            "odh.Backend(Path(sys.argv[2]), Path(sys.argv[3]))"
        )
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                "-X",
                "utf8",
                "-c",
                code,
                str(SKILL_DIR / "scripts"),
                str(PROJECT),
                str(self.install),
            ],
            capture_output=True,
            encoding="utf-8",
            check=False,
            timeout=30,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("fresh odh.py process", result.stderr)

    def test_conflicting_src_package_rejected(self):
        # A regular src package takes precedence over upstream's namespace package.
        conflicting = self.root / "conflict/src/utils"
        conflicting.mkdir(parents=True)
        (conflicting.parent / "__init__.py").write_text("", encoding="utf-8")
        (conflicting / "__init__.py").write_text("", encoding="utf-8")
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(conflicting.parent.parent)
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(SKILL_DIR / "scripts/odh.py"),
                "--source",
                str(PROJECT),
                "--install",
                str(self.install),
                "list",
            ],
            env=environment,
            cwd=self.root,
            capture_output=True,
            encoding="utf-8",
            check=False,
            timeout=30,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("outside source", json.loads(result.stdout)["error"])


if __name__ == "__main__":
    unittest.main()
