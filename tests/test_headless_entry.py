"""原 CLI 参数经独立入口执行，禁止导入 Qt 或启动真实脚本。"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.headless_entry import main
from src.update.runtime import FileLease
from src.utils.utils_shutdown import RUST_CONFIRM_ENV
from tests.support.headless import PROJECT_ROOT, HeadlessFixture


class HeadlessEntryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.fixture = HeadlessFixture(self.root)
        self.env = {**os.environ, "TMPDIR": str(self.root), "TEMP": str(self.root)}

    def run_entry(self, *args):
        command = self.fixture.command(*args)
        command[2] = command[2].replace("'src.headless'", "'src.headless_entry'")
        return subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            env=self.env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )

    def test_legacy_outputs_and_utf8_arguments_without_gui(self):
        for arguments, code, expected in (
            (("--selftest",), 0, {"status": "ok"}),
            (("--list-scripts",), 0, {"scripts": ["ok-ww", "自定义脚本"]}),
            (("--get-script", "自定义脚本"), 0, {"status": "ok"}),
            (("--get-script", "不存在"), 1, {"status": "not_found"}),
        ):
            with self.subTest(arguments=arguments):
                output = self.root / "中文 结果.json"
                result = self.run_entry(*arguments, "--out", str(output))
                self.assertEqual(result.returncode, code, result.stderr)
                data = json.loads(output.read_text(encoding="utf-8"))
                for key, value in expected.items():
                    self.assertEqual(data[key], value)
        (self.root / "version.json").write_text(
            '{"version":"1.2.3","frontend":"rust"}', encoding="utf-8"
        )
        result = self.run_entry("--version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("1.2.3", (self.root / "odh_gui_version.txt").read_text())

    def test_invalid_or_missing_action_cannot_fall_back_to_gui(self):
        for args in ((), ("--unknown-option",), ("--out", "unused.json")):
            with self.subTest(args=args):
                result = self.run_entry(*args)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertNotIn("CLI 加载了 GUI", result.stderr)

    def test_legacy_update_gate_precedes_configuration(self):
        with FileLease(self.root / ".update/intent.lock"):
            result = self.run_entry("--selftest", "--out", str(self.root / "out.json"))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse((self.root / "config/config.yml").exists())
        self.assertFalse((self.root / "out.json").exists())

    def test_frozen_entry_uses_sibling_shutdown_ui_and_preserves_rpc(self):
        with (
            patch("src.headless_entry.headless_main", return_value=7) as entry,
            patch("sys.frozen", True, create=True),
            patch("sys.executable", str(self.root / "OneDragon-Helper-CLI.exe")),
            patch.dict(os.environ),
        ):
            os.environ.pop(RUST_CONFIRM_ENV, None)
            self.assertEqual(main(["serve", "--stdio"]), 7)
            entry.assert_called_once_with(["serve", "--stdio"])
            self.assertEqual(
                os.environ[RUST_CONFIRM_ENV], str(self.root / "OneDragon-Helper.exe")
            )
            os.environ[RUST_CONFIRM_ENV] = "explicit-parent.exe"
            self.assertEqual(main(["--selftest"]), 7)
            entry.assert_called_with(["legacy", "--", "--selftest"])
            self.assertEqual(os.environ[RUST_CONFIRM_ENV], "explicit-parent.exe")

    def test_headless_entry_selects_rust_update_service(self):
        from argparse import Namespace
        from contextlib import nullcontext

        from src.headless import _run_command

        with (
            patch("src.update.runtime.application_lease", return_value=nullcontext()),
            patch("src.config.generate_config.config_workflow"),
            patch("src.utils.utils_logger.setup_logging"),
            patch("src.utils.utils_logger.install_crash_hooks"),
            patch("src.service.app_service.AppService") as factory,
            patch("src.headless._call", return_value=0) as dispatch,
        ):
            self.assertEqual(
                _run_command(Namespace(command="call", method="update.view")), 0
            )
        factory.assert_called_once_with(frontend="rust")
        dispatch.assert_called_once_with(factory.return_value, "update.view")
