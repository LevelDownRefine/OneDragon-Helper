"""独立更新模块入口：真实进程安装与错误结果，不触碰用户安装。"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from src.update.package import APP_EXE, load_manifest
from tests.support.update_package import make_package, program_snapshot


class TestUpdateEntrypoint(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.root = make_package(self.directory / "installed")
        self.package = make_package(self.directory / "next", "2.0.0")
        self.config = self.root / "config/config.yml"
        self.config.write_bytes(b"user: preserved\n")
        self.result = self.directory / "result.json"

    def run_updater(self):
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "src.update",
                "--root",
                str(self.root),
                "--package",
                str(self.package),
                "--result",
                str(self.result),
            ],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )

    def read_result(self):
        result = json.loads(self.result.read_text(encoding="utf-8"))
        self.assertEqual(
            json.loads((self.root / ".update/result.json").read_text(encoding="utf-8")),
            result,
        )
        self.assertEqual(self.config.read_bytes(), b"user: preserved\n")
        return result

    def test_module_entry_installs_and_records_success(self):
        completed = self.run_updater()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(load_manifest(self.root, verify=True)["version"], "2.0.0")
        self.assertEqual(program_snapshot(self.root), program_snapshot(self.package))
        self.assertEqual(self.read_result(), {"status": "installed"})

    def test_module_entry_reports_bad_package_without_changing_program(self):
        before = program_snapshot(self.root)
        (self.package / APP_EXE).write_bytes(b"corrupted")
        completed = self.run_updater()
        self.assertEqual(completed.returncode, 1, completed.stderr)
        self.assertEqual(program_snapshot(self.root), before)
        result = self.read_result()
        self.assertEqual(result["status"], "failed")
        self.assertIn("UpdateError", result["error"])
        self.assertIn(APP_EXE, result["error"])
