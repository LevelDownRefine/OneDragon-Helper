"""启动测量必须等正确阶段，不能把早退或截图失败报告为成功。"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from tools.measure_gui_startup import main, run_sample


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

    def test_report_creates_local_output_directory_and_excludes_warmup(self):
        packages = [self.root / family for family in ("qt", "rust")]
        for package in packages:
            package.mkdir()
            (package / "OneDragon-Helper.exe").write_bytes(b"test executable")
        qml = packages[0] / "src/gui/qml/main.qml"
        qml.parent.mkdir(parents=True)
        qml.write_text("Window {}", encoding="utf-8")
        output = self.root / ".cache/gui-startup.json"
        arguments = [
            "measure_gui_startup.py",
            "--qt-package",
            str(packages[0]),
            "--rust-package",
            str(packages[1]),
            "--output",
            str(output),
            "--runs",
            "1",
        ]
        with (
            patch("tools.measure_gui_startup.sys.argv", arguments),
            patch("tools.measure_gui_startup.sys.platform", "win32"),
            patch("tools.measure_gui_startup.validate_package"),
            patch("tools.measure_gui_startup.load_manifest"),
            patch(
                "tools.measure_gui_startup.manifest_frontend",
                side_effect=["qt", "rust"],
            ),
            patch(
                "tools.measure_gui_startup.run_sample",
                return_value={
                    "task_data_ms": 100,
                    "task_frame_ms": 200,
                },
            ) as sample,
        ):
            self.assertEqual(main(), 0)
        report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(sample.call_count, 4)
        for family in ("qt", "rust"):
            self.assertEqual(len(report["samples_ms"][family]), 1)
            self.assertEqual(
                report["summary_ms"][family]["task_frame_ms"]["median"], 200
            )
