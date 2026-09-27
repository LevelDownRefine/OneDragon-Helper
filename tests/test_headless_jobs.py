"""真实无 Qt 会话中的后台 ZIP 往返与协议/租约隔离。"""

import json
import os
import queue
import subprocess
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path

from src.update.runtime import FileLease, UpdateBusyError
from tests.support.headless import PROJECT_ROOT, HeadlessFixture


class HeadlessJobTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.fixture = HeadlessFixture(self.root)
        self.errors = self.enterContext(
            tempfile.TemporaryFile(mode="w+", encoding="utf-8")
        )
        self.counter = 0
        self.lines = queue.Queue()
        self.process = None

    def start(self, command):
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.errors,
            text=True,
            encoding="utf-8",
            cwd=PROJECT_ROOT,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )

        def read():
            for line in self.process.stdout:
                self.lines.put(line)

        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()
        self.addCleanup(self.close)

    def close(self):
        if self.process.stdin and not self.process.stdin.closed:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
            self.fail("后台操作在 EOF 后未结束")
        finally:
            self.process.stdout.close()
            self.reader.join(5)

    def exchange(self, method, params):
        self.counter += 1
        self.process.stdin.write(
            json.dumps(
                {
                    "protocol_version": 1,
                    "id": self.counter,
                    "method": method,
                    "params": params,
                }
            )
            + "\n"
        )
        self.process.stdin.flush()
        response = json.loads(self.lines.get(timeout=15))
        self.assertEqual(response["id"], self.counter)
        return response

    def finished(self, task):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            response = self.exchange("job.poll", {"job_id": task["id"]})
            self.assertIn("result", response)
            state = response["result"]
            if state["state"] != "running":
                return state
            time.sleep(0.02)
        self.fail("后台操作超时")

    def test_backup_restore_round_trip_without_gui(self):
        self.start(self.fixture.command("serve", "--stdio"))
        created = self.finished(self.exchange("backup.start", {})["result"])
        self.assertEqual(created["state"], "succeeded", created)
        archive = Path(created["result"]["path"])
        with zipfile.ZipFile(archive) as backup:
            self.assertTrue(
                any(name.endswith("DailyTask.json") for name in backup.namelist())
            )
        self.fixture.native.write_text('{"changed":true}', encoding="utf-8")
        denied = self.exchange(
            "restore.start", {"zip_path": str(archive), "confirmed": False}
        )
        self.assertEqual(denied["error"]["code"], "invalid_params")
        self.assertEqual(
            json.loads(self.fixture.native.read_text(encoding="utf-8")),
            {"changed": True},
        )
        restored = self.finished(
            self.exchange(
                "restore.start", {"zip_path": str(archive), "confirmed": True}
            )["result"]
        )
        self.assertEqual(restored["state"], "succeeded", restored)
        self.assertEqual(
            json.loads(self.fixture.native.read_text(encoding="utf-8")),
            self.fixture.initial,
        )
        self.assertTrue(Path(restored["result"]["pre_backup"]).is_file())
        self.assertIn("result", self.exchange("app.snapshot", {}))

    def test_update_progress_and_cancel_without_qt(self):
        command = self.fixture.command("serve", "--stdio")
        command[2] = command[2].replace(
            "with patch('src.utils.get_root_dir', return_value=root):",
            """
def download(release, *, progress, cancelled):
    from src.update.package import UpdateCancelled
    progress(7, 10)
    if not cancelled.wait(10):
        raise TimeoutError('cancel did not arrive')
    raise UpdateCancelled('cancelled')
with patch('src.utils.get_root_dir', return_value=root):
    from src.update.service import UpdateInfo, ReleaseUpdate, UpdateService
    patch.object(UpdateService,'get_update_info',return_value=UpdateInfo('1.0.0')).start()
    patch.object(UpdateService,'check_update',return_value=ReleaseUpdate('2.0.0','notes','url','checksum',100)).start()
    patch.object(UpdateService,'prepare_update',side_effect=download).start()
""",
        )
        self.start(command)
        self.assertEqual(self.exchange("update.view", {})["result"]["version"], "1.0.0")
        self.finished(self.exchange("update.check", {})["result"])
        task = self.exchange("update.download", {})["result"]
        deadline = time.monotonic() + 5
        while True:
            state = self.exchange("job.poll", {"job_id": task["id"]})["result"]
            if "progress" in state:
                self.assertEqual(state["progress"], {"received": 7, "total": 10})
                break
            self.assertLess(time.monotonic(), deadline)
        self.assertEqual(
            self.exchange("update.view", {})["error"]["code"], "operation_busy"
        )
        self.assertTrue(self.exchange("job.cancel", {"job_id": task["id"]})["result"])
        self.assertEqual(self.finished(task)["state"], "cancelled")
        self.assertIsNone(
            self.exchange("update.view", {})["result"]["prepared_version"]
        )

    def test_background_stdout_busy_state_and_eof_hold_runtime_lease(self):
        command = self.fixture.command("serve", "--stdio")
        command[2] = command[2].replace(
            "with patch('src.utils.get_root_dir', return_value=root):",
            """
def operation():
    import time
    from pathlib import Path
    sys.stdout.write('background-noise\\n')
    sys.stdout.flush()
    deadline=time.monotonic()+10
    while not Path(root,'release').exists():
        if time.monotonic()>deadline:
            raise TimeoutError('test release missing')
        time.sleep(.01)
    return {'path':'fake.zip','file_count':1}
with patch('src.utils.get_root_dir', return_value=root), patch('src.service.backup_service.create_backup', side_effect=operation):
""",
        )
        self.start(command)
        task = self.exchange("backup.start", {})["result"]
        self.assertEqual(
            self.exchange("app.snapshot", {})["error"]["code"], "operation_busy"
        )
        self.assertEqual(
            self.exchange("job.poll", {"job_id": task["id"]})["result"]["state"],
            "running",
        )
        self.process.stdin.close()
        with (
            self.assertRaises(UpdateBusyError),
            FileLease(self.root / ".update/runtime.lock"),
        ):
            self.fail("后台写入期间提前释放租约")
        self.root.joinpath("release").touch()
        self.assertEqual(self.process.wait(timeout=10), 0)
        with FileLease(self.root / ".update/runtime.lock"):
            self.errors.seek(0)
            self.assertIn("background-noise", self.errors.read())
