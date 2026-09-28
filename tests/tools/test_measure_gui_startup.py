"""启动测量必须等正确阶段，不能把早退或截图失败报告为成功。"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from tools.measure_gui_startup import run_sample


class StartupMeasurementTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.dict(os.environ, {"SYSTEMROOT": str(self.root)}))

    def test_process_exit_without_ready_marker_is_not_a_startup_result(self):
        process = Mock(returncode=0)
        process.poll.return_value = 0
        with (
            patch("tools.measure_gui_startup.subprocess.Popen", return_value=process),
            self.assertRaisesRegex(RuntimeError, "未到标记即退出"),
        ):
            run_sample("qt", self.root, self.root, 0)
        process.terminate.assert_not_called()

    def test_rust_ready_log_requires_successful_capture_exit(self):
        (self.root / "rust-0.log").write_text(
            "first task ready\ntask frame captured", encoding="utf-8"
        )
        process = Mock(returncode=1)
        process.poll.return_value = 1
        with (
            patch("tools.measure_gui_startup.subprocess.Popen", return_value=process),
            self.assertRaisesRegex(RuntimeError, "截图退出码 1"),
        ):
            run_sample("rust", self.root, self.root, 0)
        process.wait.assert_called_once_with(timeout=30)

    def test_frame_without_task_data_marker_is_rejected(self):
        (self.root / "rust-0.log").write_text("task frame captured", encoding="utf-8")
        process = Mock(returncode=0)
        process.poll.return_value = 0
        with (
            patch("tools.measure_gui_startup.subprocess.Popen", return_value=process),
            self.assertRaisesRegex(RuntimeError, "缺少任务就绪标记"),
        ):
            run_sample("rust", self.root, self.root, 0)
        process.terminate.assert_not_called()
