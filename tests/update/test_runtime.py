"""更新锁和运行锁的跨进程语义。"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.update import __main__ as updater
from src.update.package import APP_EXE, UpdateError
from src.update.runtime import (
    FileLease,
    UpdateBusyError,
    application_lease,
    helper_processes,
)


class TestUpdateRuntime(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_shared_application_leases_coexist_but_exclude_installation(self):
        with (
            application_lease(self.root),
            application_lease(self.root),
            self.assertRaises(UpdateBusyError),
            FileLease(self.root / ".update/runtime.lock"),
        ):
            self.fail("exclusive lock acquired")
        with FileLease(self.root / ".update/runtime.lock"):
            self.assertTrue((self.root / ".update/runtime.lock").is_file())

    def test_update_intent_blocks_new_application_without_configuration_io(self):
        with (
            FileLease(self.root / ".update/intent.lock"),
            self.assertRaises(UpdateBusyError),
            application_lease(self.root),
        ):
            self.fail("application started")
        self.assertFalse((self.root / "config").exists())

    def test_process_exit_releases_update_intent(self):
        code = (
            "from pathlib import Path; from src.update.runtime import FileLease; "
            "import os,sys; lock=FileLease(Path(sys.argv[1])); lock.__enter__(); os._exit(0)"
        )
        path = self.root / ".update/intent.lock"
        subprocess.run([sys.executable, "-c", code, str(path)], check=True, timeout=20)
        with FileLease(path):
            self.assertTrue(path.exists())

    def test_unfinished_transaction_blocks_launch(self):
        (self.root / ".update").mkdir()
        (self.root / ".update/transaction.json").write_text(
            json.dumps({"phase": "installing"})
        )
        with self.assertRaisesRegex(UpdateError, "恢复"), application_lease(self.root):
            self.fail("application started")

    def test_process_detection_uses_install_path_and_excludes_caller(self):
        own = Mock(pid=os.getpid())
        own.exe.return_value = str(self.root / APP_EXE)
        running = Mock(pid=12345)
        running.exe.return_value = str(self.root / APP_EXE)
        another = Mock(pid=12346)
        another.exe.return_value = str(self.root / "other" / APP_EXE)
        with patch(
            "src.update.runtime.psutil.process_iter",
            return_value=[own, running, another],
        ):
            self.assertEqual(helper_processes(self.root, {os.getpid()}), [12345])

    def test_busy_runner_is_rejected_before_ready_or_install(self):
        ready = self.root / "ready.json"
        with (
            patch.object(updater, "helper_processes", return_value=[12345]),
            patch.object(updater, "install_package") as install,
            self.assertRaises(UpdateBusyError),
        ):
            updater.run_update(self.root, self.root / "new", ready=ready)
        install.assert_not_called()
        self.assertFalse(ready.exists())

    def test_parent_identity_must_match(self):
        parent = Mock()
        parent.create_time.return_value = 22.0
        with (
            patch.object(updater.psutil, "Process", return_value=parent),
            self.assertRaises(UpdateBusyError),
        ):
            updater.run_update(
                self.root, self.root / "new", parent_pid=12345, parent_created=11.0
            )

    def test_handoff_cancellation_blocks_orphaned_worker(self):
        cancel = self.root / "cancel"
        cancel.touch()
        with (
            patch.object(updater, "helper_processes", return_value=[]),
            patch.object(updater, "install_package") as install,
            self.assertRaisesRegex(UpdateBusyError, "取消"),
        ):
            updater.run_update(self.root, self.root / "new", cancel=cancel)
        install.assert_not_called()
