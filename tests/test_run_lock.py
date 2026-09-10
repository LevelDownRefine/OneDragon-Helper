"""手动/每日运行共用系统锁，覆盖不同进程及异常释放。"""

import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from src.service.chain_service import schedule_run
from src.service.run_lock import run_lock


class TestRunLock(unittest.TestCase):
    def test_other_process_cannot_run_until_lock_released(self):
        code = (
            "import sys; from src.service.run_lock import run_lock\n"
            "with run_lock(sys.argv[1]) as acquired:\n"
            "    raise SystemExit(0 if acquired else 7)\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            with run_lock(directory) as acquired:
                self.assertTrue(acquired)
                blocked = subprocess.run(
                    [sys.executable, "-c", code, directory], timeout=20
                )
                self.assertEqual(blocked.returncode, 7)
            resumed = subprocess.run(
                [sys.executable, "-c", code, directory], timeout=20
            )
            self.assertEqual(resumed.returncode, 0)

    def test_exception_releases_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "failed"), run_lock(directory):
                raise RuntimeError("failed")
            with run_lock(directory) as acquired:
                self.assertTrue(acquired)

    def test_busy_factory_performs_no_pre_or_post_actions(self):
        @contextmanager
        def busy():
            yield False

        with (
            patch("src.service.chain_service.run_lock", busy),
            patch("src.service.chain_service.ScheduledRun") as run,
        ):
            schedule_run({"A"}, "now", shutdown_delay=60)
        run.assert_not_called()

    def test_empty_selection_does_not_construct_run(self):
        with patch("src.service.chain_service.ScheduledRun") as run:
            schedule_run(set(), "now", shutdown_delay=60)
        run.assert_not_called()
