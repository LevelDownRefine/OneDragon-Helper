"""测试统一日志配置：按角色分文件、跨日切文件、过期清理。"""

import logging as _logging
import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import src.log.monitor as collect_log
import src.utils.utils_logger as utils_logger
from src.utils.utils_logger import _BACKUP_DAYS, _DailyFileHandler, today
from tests.support.framework_log import temp_framework_root


class TestSetupLoggingRole(unittest.TestCase):
    def test_role_selects_today_file(self):
        """两个角色各自只落盘到带当天日期的对应文件。"""
        for role, name in (
            ("gui", "onedragon_helper"),
            ("plan", "onedragon_helper.plan"),
        ):
            with self.subTest(role=role), temp_framework_root() as tmp:
                utils_logger.setup_logging(role=role)
                _logging.getLogger("__test_utils_logger__").info("HELLO_%s", role)
                for handler in _logging.getLogger().handlers:
                    handler.flush()

                logs = os.listdir(os.path.join(tmp, "logs"))
                self.assertEqual(logs, [f"{name}-{today()}.log"])
                content = Path(tmp, "logs", logs[0]).read_text(encoding="utf-8")
                self.assertIn(f"HELLO_{role}", content)

    def test_repeat_call_keeps_first_role(self):
        """重复调用沿用首次落点：运行期日志汇总的调用形态不报错，显式换角色即断言失败。"""
        with temp_framework_root():
            utils_logger.setup_logging(role="plan")
            collect_log.setup_logging()  # parse_logs 内部就是这样调的（不传角色）
            with self.assertRaises(AssertionError):
                utils_logger.setup_logging(role="gui")


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
    def test_purge_removes_only_expired_dated_files(self):
        """按日文件各角色一律按保留期清理；当天文件与旧命名文件都不动。"""
        directory = self.enterContext(tempfile.TemporaryDirectory())

        def make(name: str, days_ago: int) -> Path:
            day = date.today() - timedelta(days=days_ago)
            path = Path(directory, name.format(day=day.isoformat()))
            path.write_text("x", encoding="utf-8")
            return path

        expired_gui = make("onedragon_helper-{day}.log", _BACKUP_DAYS + 1)
        expired_plan = make("onedragon_helper.plan-{day}.log", _BACKUP_DAYS + 1)
        today_gui = make("onedragon_helper-{day}.log", 0)
        legacy = make("onedragon_helper.log.{day}", _BACKUP_DAYS + 1)

        utils_logger.purge_expired_logs(directory)

        self.assertFalse(expired_gui.exists())
        self.assertFalse(expired_plan.exists())
        self.assertTrue(today_gui.exists())
        self.assertTrue(legacy.exists())
