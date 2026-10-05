"""调度 EXE 测试按实际日志文件读取增量。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.exe import test_schedule_exe as schedule


class TestScheduleLogOffsets(unittest.TestCase):
    def test_offsets_use_log_paths_and_return_only_appended_text(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        paths = {name: root / f"{name}.log" for name in ("fw", "runner")}
        previous = "旧日志\n".encode()
        for path in paths.values():
            path.write_bytes(previous)
        fixture = schedule.TestScheduleExeE2E
        with patch.object(fixture, "_log_paths", return_value=paths):
            offsets = fixture._log_offsets()
            self.assertEqual(offsets, dict.fromkeys(paths, len(previous)))
            self.assertEqual(fixture._read_tails(offsets), ("", ""))
            for name, path in paths.items():
                with path.open("ab") as stream:
                    stream.write(f"{name} 新日志\n".encode())
            self.assertEqual(
                fixture._read_tails(offsets), ("fw 新日志\n", "runner 新日志\n")
            )
