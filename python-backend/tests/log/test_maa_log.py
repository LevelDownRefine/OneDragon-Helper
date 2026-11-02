"""MAA 累积日志、运行日及重跑口径；夹具仅保留真实日志的脱敏事件。"""

import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from src.log import MaaLogParser, ScriptLogStatus, parse_log
from src.log.monitor import _prepare_action_lists, display_status


class TestMaaLog(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "gui.log"
        self.fixture = (
            Path(__file__).parents[1] / "fixtures/maa_gui.scrubbed.txt"
        ).read_text(encoding="utf-8")

    def parse(self, content, now=datetime(2026, 11, 2, 14)):
        self.path.write_text(content, encoding="utf-8")
        # 特意给文件过期 mtime，验证复制日志只看正文时间。
        os.utime(self.path, (1, 1))
        with patch("src.log.monitor.datetime", wraps=datetime) as clock:
            clock.now.return_value = now
            return parse_log("MAA", str(self.path))

    def test_latest_success_with_warnings_does_not_rerun(self):
        result = self.parse(self.fixture)
        self.assertEqual(result["status"], ScriptLogStatus.SUCCESS)
        self.assertTrue(result["daily_done"])
        self.assertEqual(result["stamina"], "2")
        self.assertEqual(len(result["errors"]), 3)
        self.assertNotIn("连接失败", "\n".join(result["errors"]))
        self.assertEqual(display_status(result), ScriptLogStatus.WARN)
        self.assertEqual(
            _prepare_action_lists([{"script_name": "MAA", "result": result}]),
            ([], ["MAA"]),
        )

    def test_failed_rounds_do_not_inherit_old_success(self):
        for cutoff, expected in (
            ("[2026-11-02 10:51:04", "开始唤醒, 剿灭作战"),
            ("[2026-11-02 12:32:57", "连接失败"),
        ):
            with self.subTest(cutoff=cutoff):
                result = self.parse(self.fixture.split(cutoff)[0])
                self.assertEqual(result["status"], ScriptLogStatus.FAILED)
                self.assertFalse(result["daily_done"])
                self.assertIn(expected, "\n".join(result["errors"]))
                self.assertEqual(
                    _prepare_action_lists([{"script_name": "MAA", "result": result}]),
                    (["MAA"], ["MAA"]),
                )

    def test_new_incomplete_run_in_same_gui_resets_success_and_stamina(self):
        content = self.fixture + (
            "[2026-11-02 13:30:00.000][INF][TaskQueueViewModel] <2> LinkStart Enter\n"
            "[2026-11-02 13:30:01.000][INF][TaskQueueViewModel] <2> LinkStart Exit, 1 ms\n"
        )
        result = self.parse(content)
        self.assertEqual(result["status"], ScriptLogStatus.FAILED)
        self.assertIsNone(result["stamina"])
        self.assertEqual(result["errors"], [])

    def test_award_alone_is_not_queue_completion(self):
        result = self.parse(self.fixture.split("[2026-11-02 13:04:34")[0])
        self.assertFalse(result["daily_done"])

    def test_run_day_uses_four_am_and_not_file_mtime(self):
        for now, expected in (
            (datetime(2026, 11, 3, 3, 59), ScriptLogStatus.SUCCESS),
            (datetime(2026, 11, 3, 4), ScriptLogStatus.NO_LOG),
        ):
            with self.subTest(now=now):
                result = self.parse(self.fixture, now)
                self.assertEqual(result["status"], expected)

    def test_run_crossing_four_am_keeps_start_and_continuations(self):
        content = (
            "[2026-11-02 03:59:00.000][INF][TaskQueueViewModel] <2> LinkStart Enter\n"
            "[2026-11-02 04:01:00.000][INF][TaskQueueViewModel] <2> 任务已全部完成！\n"
            "理智: 3/210\n"
        )
        result = self.parse(content)
        self.assertTrue(result["daily_done"])
        self.assertEqual(result["stamina"], "3")

    def test_missing_empty_and_new_session_have_no_run(self):
        self.assertEqual(
            parse_log("MAA", str(self.path))["status"], ScriptLogStatus.NO_LOG
        )
        for content in (
            "",
            self.fixture
            + "[2026-11-02 13:30:00.000][INF][Bootstrapper] <2> MaaAssistantArknights GUI started\n",
            "[2026-11-02 13:30:00.000][INF][ConfigFactory] <2> LinkStart Enter\n",
        ):
            with self.subTest(content=content[-100:]):
                result = self.parse(content)
                self.assertEqual(result["status"], ScriptLogStatus.NO_LOG)
                self.assertFalse(result["daily_done"])

    def test_config_messages_cannot_impersonate_completion(self):
        content = (
            "[2026-11-02 13:30:00.000][INF][TaskQueueViewModel] <2> LinkStart Enter\n"
            "[2026-11-02 13:30:01.000][INF][ConfigFactory] <2> 任务已全部完成！\n"
        )
        self.assertFalse(self.parse(content)["daily_done"])

    def test_invalid_timestamp_is_reported(self):
        with self.assertLogs("src.log.monitor", level="WARNING"):
            result = self.parse(
                "[2026-99-02 13:30:00.000][INF][TaskQueueViewModel] <2> LinkStart Enter\n"
            )
        self.assertEqual(result["status"], ScriptLogStatus.NO_LOG)

    def test_future_records_cannot_complete_current_run(self):
        result = self.parse(self.fixture, datetime(2026, 11, 2, 12, 40))
        self.assertFalse(result["daily_done"])
        self.assertIsNone(result["stamina"])
        self.assertEqual(result["errors"], [])

    def test_idle_config_update_does_not_make_old_run_current(self):
        content = self.fixture + (
            "[2026-11-03 12:00:00.000][INF][ConfigFactory] <2> saved\n"
        )
        result = self.parse(content, datetime(2026, 11, 3, 14))
        self.assertEqual(result["status"], ScriptLogStatus.NO_LOG)

    def test_error_limit_retains_multiline_record(self):
        errors = MaaLogParser().collect_error_lines(
            self.fixture.split("[2026-11-02 10:51:04")[0], limit=2
        )
        self.assertEqual(len(errors), 2)
        self.assertIn("开始唤醒, 剿灭作战", errors[1])

    def test_failure_summary_survives_more_than_ten_errors(self):
        content = "".join(
            f"[2026-11-02 04:14:{index:02d}.000][ERR][TaskQueueViewModel] <2> 任务出错: task {index}\n"
            for index in range(12)
        ) + (
            "[2026-11-02 04:15:00.000][ERR][TaskQueueViewModel] <2> 任务已结束，以下任务出现错误:\n"
            "开始唤醒, 剿灭作战, 理智作战\n"
        )
        errors = MaaLogParser().collect_error_lines(content)
        self.assertEqual(len(errors), 10)
        self.assertIn("开始唤醒, 剿灭作战, 理智作战", errors[-1])
        self.assertNotIn("task 0\n", "\n".join(errors))
        self.assertEqual(MaaLogParser().collect_error_lines(content, limit=0), [])
