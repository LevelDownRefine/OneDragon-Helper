"""Rust/CLI 双进程更新交接；进程和安装动作均为模拟对象。"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import psutil

from src.update import __main__ as updater
from src.update import service
from src.update.package import APP_EXE, CLI_EXE, UpdateError
from src.update.runtime import FileLease, UpdateBusyError
from tests.support.update_package import make_package, program_snapshot


class RustHandoffTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.root = make_package(self.directory / "installed", frontend="rust")
        self.package = make_package(
            self.root / ".update/download-test/package", "2.0.0", frontend="rust"
        )
        self.prepared = service.PreparedUpdate(self.package.parent, "2.0.0")
        self.client = service.UpdateService(self.root, frontend="rust")
        self.enterContext(patch.object(sys, "frozen", True, create=True))
        self.cli = Mock(pid=os.getpid())
        self.gui = Mock(pid=999991)
        self.cli.exe.return_value = str(self.root / CLI_EXE)
        self.gui.exe.return_value = str(self.root / APP_EXE)
        self.cli.create_time.return_value = 11.0
        self.gui.create_time.return_value = 22.0
        self.cli.parent.return_value = self.gui
        self.cli.ppid.return_value = self.gui.pid

    def test_service_only_hands_off_its_verified_parent_pair(self):
        before = program_snapshot(self.root)

        def start(command, **_kwargs):
            self.assertEqual(
                command[command.index("--parent-pid") + 1], str(self.cli.pid)
            )
            self.assertEqual(command[command.index("--parent-created") + 1], "11.0")
            self.assertEqual(
                command[command.index("--frontend-pid") + 1], str(self.gui.pid)
            )
            self.assertEqual(command[command.index("--frontend-created") + 1], "22.0")
            Path(command[command.index("--ready") + 1]).write_text('{"status":"ready"}')
            return Mock()

        with (
            patch.object(service.psutil, "Process", return_value=self.cli),
            patch.object(service, "helper_processes", return_value=[]) as running,
            patch.object(service.subprocess, "Popen", side_effect=start),
        ):
            self.assertEqual(
                self.client.start_update(self.prepared).name, "result.json"
            )
        running.assert_called_once_with(self.root, {self.cli.pid, self.gui.pid})
        self.assertEqual(program_snapshot(self.root), before)

    def test_service_rejects_foreign_parent_or_other_running_cli(self):
        for kind in ("foreign", "missing", "wrong_cli", "busy"):
            with self.subTest(kind=kind):
                self.cli.parent.return_value = None if kind == "missing" else self.gui
                self.cli.exe.return_value = str(
                    self.root / (APP_EXE if kind == "wrong_cli" else CLI_EXE)
                )
                self.gui.exe.return_value = str(
                    (self.directory if kind == "foreign" else self.root) / APP_EXE
                )
                with (
                    patch.object(service.psutil, "Process", return_value=self.cli),
                    patch.object(
                        service,
                        "helper_processes",
                        return_value=[1234] if kind == "busy" else [],
                    ),
                    patch.object(service.subprocess, "Popen") as spawn,
                    self.assertRaises(UpdateError),
                ):
                    self.client.start_update(self.prepared)
                spawn.assert_not_called()

    def run_installer(self, ready):
        updater.run_update(
            self.root,
            self.package,
            parent_pid=self.cli.pid,
            parent_created=11.0,
            frontend_pid=self.gui.pid,
            frontend_created=22.0,
            ready=ready,
        )

    def processes(self, pid):
        self.assertIn(pid, (self.cli.pid, self.gui.pid))
        return self.cli if pid == self.cli.pid else self.gui

    def test_installer_signals_ready_then_waits_for_both_processes(self):
        ready = self.directory / "ready.json"
        exited = []

        def wait(name, timeout):
            self.assertTrue(ready.is_file())
            self.assertGreater(timeout, 0)
            self.assertLessEqual(timeout, 30)
            exited.append(name)

        self.cli.wait.side_effect = lambda timeout: wait("cli", timeout)
        self.gui.wait.side_effect = lambda timeout: wait("gui", timeout)

        def install(root, package):
            self.assertEqual((root, package), (self.root, self.package))
            self.assertEqual(exited, ["cli", "gui"])
            with (
                self.assertRaises(UpdateBusyError),
                FileLease(self.root / ".update/runtime.lock", shared=True),
            ):
                self.fail("installer did not hold exclusive lease")

        with (
            patch.object(updater.psutil, "Process", side_effect=self.processes),
            patch.object(updater, "helper_processes", return_value=[]) as running,
            patch.object(updater, "install_package", side_effect=install) as installed,
        ):
            self.run_installer(ready)
        installed.assert_called_once()
        self.assertEqual(running.call_args_list[-1].args, (self.root, {os.getpid()}))

    def test_changed_identity_relationship_or_timeout_never_installs(self):
        for kind in ("pid_reuse", "foreign", "relationship", "timeout"):
            with self.subTest(kind=kind):
                ready = self.directory / f"ready-{kind}.json"
                self.gui.create_time.return_value = (
                    99.0 if kind == "pid_reuse" else 22.0
                )
                self.gui.exe.return_value = str(
                    (self.directory if kind == "foreign" else self.root) / APP_EXE
                )
                self.cli.ppid.return_value = (
                    0 if kind == "relationship" else self.gui.pid
                )
                self.gui.wait.side_effect = (
                    psutil.TimeoutExpired(30) if kind == "timeout" else None
                )
                with (
                    patch.object(updater.psutil, "Process", side_effect=self.processes),
                    patch.object(updater, "helper_processes", return_value=[]),
                    patch.object(updater, "install_package") as install,
                    self.assertRaises(UpdateBusyError),
                ):
                    self.run_installer(ready)
                install.assert_not_called()
                self.assertEqual(ready.exists(), kind == "timeout")


class QtCliHandoffTests(RustHandoffTests):
    def setUp(self):
        super().setUp()
        self.root = make_package(self.directory / "qt-installed")
        self.package = make_package(
            self.root / ".update/download-test/package", "2.0.0"
        )
        self.prepared = service.PreparedUpdate(self.package.parent, "2.0.0")
        self.client = service.UpdateService(self.root, frontend="qt")
        self.cli.exe.return_value = str(self.root / CLI_EXE)
        self.gui.exe.return_value = str(self.root / APP_EXE)

    def test_service_rejects_foreign_parent_or_other_running_cli(self):
        # Qt 旧入口仍支持 GUI 直接交接；CLI 入口严格验证父 GUI。
        for kind in ("foreign", "missing", "busy"):
            with self.subTest(kind=kind):
                self.cli.parent.return_value = None if kind == "missing" else self.gui
                self.gui.exe.return_value = str(
                    (self.directory if kind == "foreign" else self.root) / APP_EXE
                )
                with (
                    patch.object(service.psutil, "Process", return_value=self.cli),
                    patch.object(
                        service,
                        "helper_processes",
                        return_value=[1234] if kind == "busy" else [],
                    ),
                    patch.object(service.subprocess, "Popen") as spawn,
                    self.assertRaises(UpdateError),
                ):
                    self.client.start_update(self.prepared)
                spawn.assert_not_called()
