"""测试统一日志配置：按角色分文件、跨日切文件、过期清理。"""

import logging as _logging
import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import src.utils.utils_logger as utils_logger
from src.utils.utils_logger import _BACKUP_DAYS, _DailyFileHandler, purge_expired_logs


class _TempRootMixin:
    """把框架日志根指向临时目录并复位幂等标志（沿用 test_log_monitor 的做法）。"""

    def setUp(self):
        self._before = None

    def _temp_root(self) -> str:
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        configured = utils_logger._configured
        root_dir = utils_logger.get_root_dir
        self.addCleanup(setattr, utils_logger, "_configured", configured)
        self.addCleanup(setattr, utils_logger, "get_root_dir", root_dir)
        self.addCleanup(self._drop_added_handlers)
        if self._before is None:
            self._before = {id(h) for h in _logging.getLogger().handlers}
        utils_logger._configured = False
        utils_logger.get_root_dir = lambda: tmp
        return tmp

    def _drop_added_handlers(self) -> None:
        for handler in list(_logging.getLogger().handlers):
            if id(handler) not in self._before:
                _logging.getLogger().removeHandler(handler)
                handler.close()

    @staticmethod
    def _flush_handlers() -> None:
        for handler in _logging.getLogger().handlers:
            handler.flush()


class TestSetupLoggingRole(_TempRootMixin, unittest.TestCase):
    def test_role_selects_today_file(self):
        """两个角色各自只落盘到带当天日期的对应文件。"""
        for role, name in (
            ("gui", "onedragon_helper"),
            ("plan", "onedragon_helper.plan"),
        ):
            with self.subTest(role=role):
                tmp = self._temp_root()
                utils_logger.setup_logging(role=role)
                _logging.getLogger("__test_utils_logger__").info("HELLO_%s", role)
                self._flush_handlers()

                logs = os.listdir(os.path.join(tmp, "logs"))
                self.assertEqual(logs, [f"{name}-{utils_logger.today()}.log"])
                content = Path(tmp, "logs", logs[0]).read_text(encoding="utf-8")
                self.assertIn(f"HELLO_{role}", content)
                self._drop_added_handlers()


class TestDailyFileHandler(unittest.TestCase):
    def test_crossing_midnight_switches_file_without_rename(self):
        """跨日只关掉旧文件、改开当天文件；旧文件原地封存，不产生无日期的 rename 残留。"""
        directory = self.enterContext(tempfile.TemporaryDirectory())
        logger = _logging.getLogger("__test_daily_file_handler__")
        logger.setLevel(_logging.INFO)
        handler = None
        try:
            with mock.patch.object(utils_logger, "today", return_value="2026-10-09"):
                handler = _DailyFileHandler(directory, "onedragon_helper")
                logger.addHandler(handler)
                logger.info("DAY1")
            with mock.patch.object(utils_logger, "today", return_value="2026-10-10"):
                logger.info("DAY2")
            first = Path(directory, "onedragon_helper-2026-10-09.log").read_text(
                encoding="utf-8"
            )
            second = Path(directory, "onedragon_helper-2026-10-10.log").read_text(
                encoding="utf-8"
            )
        finally:
            if handler is not None:
                logger.removeHandler(handler)
                handler.close()

        self.assertIn("DAY1", first)
        self.assertNotIn("DAY2", first)
        self.assertIn("DAY2", second)
        self.assertEqual(
            sorted(os.listdir(directory)),
            ["onedragon_helper-2026-10-09.log", "onedragon_helper-2026-10-10.log"],
        )


class TestPurgeExpiredLogs(unittest.TestCase):
    def test_purge_only_removes_expired_files_of_same_prefix(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())

        def make(prefix: str, days_ago: int) -> Path:
            day = date.today() - timedelta(days=days_ago)
            path = Path(directory, f"{prefix}-{day.isoformat()}.log")
            path.write_text("x", encoding="utf-8")
            return path

        expired = make("onedragon_helper", _BACKUP_DAYS + 1)
        today_file = make("onedragon_helper", 0)
        other_prefix = make("onedragon_helper.plan", _BACKUP_DAYS + 1)

        purge_expired_logs(directory, "onedragon_helper")

        self.assertFalse(expired.exists())
        self.assertTrue(today_file.exists())
        self.assertTrue(other_prefix.exists())
