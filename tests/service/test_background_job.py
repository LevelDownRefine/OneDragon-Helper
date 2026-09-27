"""后台操作并发、失败和退出生命周期；不操作用户配置。"""

import unittest
from threading import Event, Thread

from src.service.background_job import BackgroundJob, InvalidBackgroundJob


class BackgroundJobTests(unittest.TestCase):
    def test_single_job_result_retention_and_close_waits(self):
        entered, release, closed = Event(), Event(), Event()
        jobs = BackgroundJob()

        def operation():
            entered.set()
            if not release.wait(10):
                raise TimeoutError("test release was not signalled")
            return {"path": "中文 backup.zip"}

        task = jobs.start("backup", operation)
        self.assertTrue(entered.wait(3))
        self.assertEqual(jobs.poll(task["id"])["state"], "running")
        with self.assertRaises(InvalidBackgroundJob):
            jobs.start("restore", lambda: {})

        def close():
            jobs.close()
            closed.set()

        waiter = Thread(target=close)
        waiter.start()
        try:
            self.assertFalse(closed.wait(0.05))
        finally:
            release.set()
            waiter.join(10)
        self.assertTrue(closed.is_set())
        expected = {
            "id": task["id"],
            "kind": "backup",
            "state": "succeeded",
            "result": {"path": "中文 backup.zip"},
        }
        self.assertEqual(jobs.poll(task["id"]), expected)
        self.assertEqual(jobs.poll(task["id"]), expected)

    def test_failure_is_logged_and_partial_details_survive(self):
        jobs = BackgroundJob()

        def operation():
            raise OSError("已恢复 1 个文件，未回滚；恢复前备份: test.zip")

        with self.assertLogs("src.service.background_job", level="ERROR"):
            task = jobs.start("restore", operation)
            jobs.close()
        result = jobs.poll(task["id"])
        self.assertEqual(result["state"], "failed")
        self.assertIn("已恢复 1 个文件", result["error"])
        self.assertIn("test.zip", result["error"])
        with self.assertRaises(InvalidBackgroundJob):
            jobs.poll("stale")
