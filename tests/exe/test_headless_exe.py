"""真实无 Qt CLI EXE；仅使用临时配置，不运行任务或修改系统设置。"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import psutil

from src.update.package import CLI_EXE
from src.update.runtime import FileLease, UpdateBusyError, child_environment
from tests.exe import project_root
from tools.release_package import resource_files

ROOT = Path(project_root())
EXECUTABLE = Path(
    os.environ.get(
        "ODH_CLI_EXE", str(ROOT / "deploy/dist/rust-cli/OneDragon-Helper" / CLI_EXE)
    )
)


@unittest.skipUnless(
    sys.platform == "win32" and EXECUTABLE.is_file(), "需要 Windows 与独立 CLI 打包产物"
)
class HeadlessExeTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.root = self.directory / "独立 CLI 安装"
        self.root.mkdir()
        shutil.copy2(EXECUTABLE, self.root / CLI_EXE)
        shutil.copytree(EXECUTABLE.parent / "_internal", self.root / "_internal")
        for name in resource_files(ROOT):
            if name.startswith(("config/", "assets/")):
                target = self.root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / name, target)
        (self.root / "config/config.example.yml").write_text(
            "script_list: []\n", encoding="utf-8"
        )

    def call(self, method="app.snapshot", params=None):
        return subprocess.run(
            [str(self.root / CLI_EXE), "call", method],
            input=json.dumps({} if params is None else params),
            text=True,
            encoding="utf-8",
            capture_output=True,
            cwd=self.directory,
            env=child_environment(),
            timeout=60,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

    def test_first_launch_from_foreign_cwd_generates_and_preserves_configuration(self):
        result = self.call()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["result"]["scripts"], [])
        config = self.root / "config/config.yml"
        self.assertTrue(config.is_file())
        config.write_text(
            "script_list:\n- display_name: 测试脚本\n  script_path: scripts/custom.exe\n",
            encoding="utf-8",
        )
        before = config.read_bytes()
        result = self.call()
        self.assertEqual(result.returncode, 0, result.stderr)
        scripts = json.loads(result.stdout)["result"]["scripts"]
        self.assertEqual(scripts[0]["display_name"], "测试脚本")
        self.assertEqual(config.read_bytes(), before)
        self.assertFalse((self.directory / "config").exists())

    def test_update_gate_precedes_configuration_initialization(self):
        with FileLease(self.root / ".update/intent.lock"):
            result = self.call()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(json.loads(result.stdout)["error"]["code"], "session_failed")
        self.assertFalse((self.root / "config/config.yml").exists())

    def test_persistent_cli_is_one_process_and_eof_releases_runtime_lease(self):
        with tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(
                [str(self.root / CLI_EXE), "serve", "--stdio"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=errors,
                cwd=self.directory,
                env=child_environment(),
                text=True,
                encoding="utf-8",
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            try:
                process.stdin.write(
                    json.dumps(
                        {
                            "protocol_version": 1,
                            "id": "中文",
                            "method": "app.snapshot",
                            "params": {},
                        }
                    )
                    + "\n"
                )
                process.stdin.flush()
                # A bounded background reader avoids hanging CI if the packaged child cannot start.
                import queue
                from threading import Thread

                lines = queue.Queue()
                reader = Thread(
                    target=lambda: lines.put(process.stdout.readline()), daemon=True
                )
                reader.start()
                response = json.loads(lines.get(timeout=60))
                reader.join(timeout=5)
                self.assertEqual(response["id"], "中文")
                self.assertIn("result", response)
                cli = psutil.Process(process.pid)
                self.assertEqual(Path(cli.exe()).resolve(), self.root / CLI_EXE)
                self.assertEqual(cli.ppid(), os.getpid())
                # Windows may create a hidden conhost; only another CLI would change the handoff identity.
                self.assertFalse(
                    any(
                        Path(child.exe()).resolve() == self.root / CLI_EXE
                        for child in cli.children()
                    )
                )
                with (
                    self.assertRaises(UpdateBusyError),
                    FileLease(self.root / ".update/runtime.lock"),
                ):
                    self.fail("CLI did not retain runtime lease")
                process.stdin.close()
                self.assertEqual(process.wait(timeout=30), 0)
                with FileLease(self.root / ".update/runtime.lock"):
                    self.assertTrue((self.root / "config/config.yml").is_file())
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=10)
                process.stdout.close()
                if not process.stdin.closed:
                    process.stdin.close()

    def test_binary_archive_has_business_dependencies_without_gui_modules(self):
        from PyInstaller.archive.readers import CArchiveReader

        archive = CArchiveReader(str(EXECUTABLE))
        modules = archive.open_embedded_archive("PYZ.pyz").toc
        for name in (
            "src.service.app_service",
            "src.update.service",
            "keyring.backends.Windows",
            "requests",
            "ssl",
        ):
            self.assertIn(name, modules)
        self.assertFalse(
            any(
                name.startswith(("PySide6", "shiboken6", "src.gui", "src.launcher"))
                for name in modules
            )
        )
        self.assertFalse(
            any(
                "pyside" in path.name.lower() or "shiboken" in path.name.lower()
                for path in (self.root / "_internal").rglob("*")
            )
        )
