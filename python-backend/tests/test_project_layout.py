"""从实际子项目目录启动入口，不依赖调用者的 PYTHONPATH。"""

import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from src.headless import _run_target
from src.service.schedule import RunOptions
from src.utils import get_root_dir
from src.utils.utils_runner import build_script_command


class ProjectLayoutTests(unittest.TestCase):
    def test_source_backend_run_target_imports_without_parent_environment(self):
        target = _run_target([], RunOptions())
        self.assertEqual(Path(target["cwd"]), Path(get_root_dir()) / "python-backend")
        environment = {
            key: value for key, value in os.environ.items() if key != "PYTHONPATH"
        }
        result = subprocess.run(
            [target["program"], *target["args"][:-1], "serve", "--help"],
            cwd=target["cwd"],
            env=environment,
            capture_output=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b"--stdio", result.stdout)

    def test_runner_remains_a_separate_cli(self):
        with patch.dict(os.environ, {"PYTHONPATH": ""}):
            command, cwd, environment = build_script_command(["--help"])
        self.assertEqual(command[:3], [sys.executable, "-m", "runner.launcher"])
        result = subprocess.run(
            command, cwd=cwd, env=environment, capture_output=True, timeout=20
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b"--chain", result.stdout)
        self.assertIn(b"--script", result.stdout)
