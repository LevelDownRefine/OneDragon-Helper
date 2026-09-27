"""更新会话只使用模拟网络与临时包，不替换当前安装。"""

import tempfile
import time
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import Mock

from src.service.background_job import BackgroundJob, InvalidBackgroundJob
from src.service.update_session import UpdateSession
from src.update.package import UpdateCancelled, UpdateError
from src.update.service import PreparedUpdate, ReleaseUpdate, UpdateInfo, UpdateService


class UpdateSessionTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.service = Mock(spec=UpdateService)
        self.service.get_update_info.return_value = UpdateInfo("1.0.0")
        self.release = ReleaseUpdate(
            "2.0.0", "更新说明", "verified-url", "checksum", 100
        )
        self.service.check_update.return_value = self.release
        self.jobs = BackgroundJob()
        self.addCleanup(self.jobs.close)
        self.session = UpdateSession(self.service, self.jobs)

    def finished(self, task):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result = self.jobs.poll(task["id"])
            if result["state"] != "running":
                return result
            time.sleep(0.01)
        self.fail("更新任务未结束")

    def test_local_info_is_read_only_and_download_requires_checked_release(self):
        self.assertEqual(self.session.view()["version"], "1.0.0")
        self.service.check_update.assert_not_called()
        with self.assertRaisesRegex(UpdateError, "先检查"):
            self.session.download()
        self.service.get_update_info.return_value = UpdateInfo("源码运行", "不支持")
        with self.assertRaisesRegex(UpdateError, "不支持"):
            self.session.check()
        self.assertFalse(self.jobs.running)

    def test_check_download_progress_and_private_prepared_directory(self):
        checked = self.finished(self.session.check())
        self.assertEqual(
            checked["result"]["release"],
            {"version": "2.0.0", "notes": "更新说明", "size": 100},
        )

        def download(release, *, progress, cancelled):
            self.assertIs(release, self.release)
            self.assertFalse(cancelled.is_set())
            progress(75, 100)
            return PreparedUpdate(self.root / "private-package", "2.0.0")

        self.service.prepare_update.side_effect = download
        downloaded = self.finished(self.session.download())
        self.assertEqual(downloaded["result"], {"version": "2.0.0"})
        self.assertEqual(downloaded["progress"], {"received": 75, "total": 100})
        self.assertEqual(self.session.view()["prepared_version"], "2.0.0")
        self.assertNotIn("private-package", str(self.session.view()))
        self.service.start_update.assert_not_called()

    def test_cancel_or_eof_cancels_download_and_retains_no_prepared_package(self):
        for eof in (False, True):
            with self.subTest(eof=eof):
                jobs = BackgroundJob()
                session = UpdateSession(self.service, jobs)
                checked = session.check()
                deadline = time.monotonic() + 5
                while jobs.poll(checked["id"])["state"] == "running":
                    self.assertLess(time.monotonic(), deadline)
                    time.sleep(0.01)
                entered = Event()

                def download(_release, *, progress, cancelled, entered=entered):
                    progress(1, 10)
                    entered.set()
                    if not cancelled.wait(5):
                        raise TimeoutError("取消未送达")
                    raise UpdateCancelled("已取消")

                self.service.prepare_update.side_effect = download
                task = session.download()
                try:
                    self.assertTrue(entered.wait(3))
                    with self.assertRaises(InvalidBackgroundJob):
                        session.check()
                    if not eof:
                        self.assertTrue(jobs.cancel(task["id"]))
                finally:
                    jobs.close()
                self.assertEqual(jobs.poll(task["id"])["state"], "cancelled")
                self.assertIsNone(session.view()["prepared_version"])
                self.assertFalse(jobs.cancel(task["id"]))
                with self.assertRaises(InvalidBackgroundJob):
                    jobs.cancel("old")

    def test_failed_check_can_retry_and_restore_cannot_be_cancelled(self):
        self.service.check_update.side_effect = OSError("网络中断")
        with self.assertLogs("src.service.background_job", level="ERROR"):
            failed = self.finished(self.session.check())
        self.assertIn("网络中断", failed["error"])
        self.assertIsNone(self.session.view()["release"])
        self.service.check_update.side_effect = None
        self.service.check_update.return_value = None
        self.assertIsNone(self.finished(self.session.check())["result"]["release"])
        task = self.jobs.start("restore", lambda: {})
        with self.assertRaisesRegex(InvalidBackgroundJob, "不支持"):
            self.jobs.cancel(task["id"])
