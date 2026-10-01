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

from src.update.package import CLI_EXE, QT_CLI_EXE
from src.update.runtime import FileLease, UpdateBusyError, child_environment
from tests.exe import project_root
from tests.exe.pipe_output import PipeOutput
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
        self.root = self.root.resolve()
        relative = (
            QT_CLI_EXE
            if EXECUTABLE.parent.name == "cli"
            and EXECUTABLE.parent.parent.name == "_internal"
            else CLI_EXE
        )
        self.binary = self.root / relative
        self.binary.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(EXECUTABLE, self.binary)
        self.runtime = self.binary.parent / "_internal"
        shutil.copytree(EXECUTABLE.parent / "_internal", self.runtime)
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
            [str(self.binary), "call", method],
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
        self.assertEqual(json.loads(result.stdout)["error"]["code"], -32004)
        self.assertFalse((self.root / "config/config.yml").exists())

    def test_jsonrpc_errors_use_library_validation_in_frozen_package(self):
        for method, code in (("unknown", -32601), ("script.view", -32602)):
            with self.subTest(method=method):
                result = self.call(method)
                self.assertEqual(result.returncode, 1, result.stderr)
                response = json.loads(result.stdout)
                self.assertEqual(response["jsonrpc"], "2.0")
                self.assertEqual(response["id"], 1)
                self.assertEqual(response["error"]["code"], code)
        result = self.call()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["result"]["scripts"], [])

    def test_legacy_flags_preserve_output_files_and_exit_status(self):
        output = self.directory / "中文 自检.json"
        for arguments, code in (
            (["--selftest", "--out", str(output)], 0),
            (["--get-script", "不存在", "--out", str(output)], 1),
            (["--invalid-option"], 2),
        ):
            with self.subTest(arguments=arguments):
                result = subprocess.run(
                    [str(self.binary), *arguments],
                    cwd=self.directory,
                    env=child_environment(),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=60,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                self.assertEqual(result.returncode, code, result.stderr)
                if code in (0, 1):
                    self.assertEqual(
                        json.loads(output.read_text(encoding="utf-8"))["status"],
                        "ok" if code == 0 else "not_found",
                    )

    def test_cli_keeps_runtime_lease_until_output_is_consumed(self):
        content = {"script_list": [], "handoff_probe": "x" * 1024**2}
        (self.root / "config/config.yml").write_text(
            json.dumps(content), encoding="utf-8"
        )
        with PipeOutput() as pipe:
            process = subprocess.Popen(
                [str(self.binary), "--dump-config", "--out", pipe.name],
                cwd=self.directory,
                env=child_environment(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            try:
                pipe.connect()
                self.assertIsNone(process.poll())
                with (
                    self.assertRaises(UpdateBusyError),
                    FileLease(self.root / ".update/runtime.lock"),
                ):
                    self.fail("CLI released runtime lease before output completed")
                self.assertEqual(json.loads(pipe.read()), content)
                self.assertEqual(process.wait(timeout=30), 0)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=10)

    def test_persistent_cli_is_one_process_and_eof_releases_runtime_lease(self):
        with tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(
                [str(self.binary), "serve", "--stdio"],
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
                            "jsonrpc": "2.0",
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
                self.assertEqual(Path(cli.exe()).resolve(), self.binary)
                self.assertEqual(cli.ppid(), os.getpid())
                # Windows may create a hidden conhost; only another CLI would change the handoff identity.
                self.assertFalse(
                    any(
                        Path(child.exe()).resolve() == self.binary
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
            "jsonrpcserver",
            "jsonschema",
            "ssl",
        ):
            self.assertIn(name, modules)
        self.assertFalse(
            any(
                name.startswith(("PySide6", "shiboken6", "gui", "gui.launcher"))
                for name in modules
            )
        )
        self.assertFalse(
            any(
                "pyside" in path.name.lower() or "shiboken" in path.name.lower()
                for path in self.runtime.rglob("*")
            )
        )
