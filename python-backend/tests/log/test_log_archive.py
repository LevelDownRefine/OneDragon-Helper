import io
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from src.log.log_archive import MAX_LOG_BYTES, build_log_archive


class LogArchiveTests(unittest.TestCase):
    def test_same_filenames_are_kept_in_separate_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [root / "one" / "app.log", root / "two" / "app.log"]
            for path, content in zip(paths, (b"first", b"second"), strict=True):
                path.parent.mkdir()
                path.write_bytes(content)
            scripts = [{"display_name": "A", "script_path": "a.py"}]
            with patch("src.log.log_archive.resolve_log_path", side_effect=paths):
                data = build_log_archive(scripts, {"A"})
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                self.assertEqual(archive.read("01-A/实时/app.log"), b"first")
                self.assertEqual(archive.read("01-A/分析/app.log"), b"second")
                self.assertEqual(len(archive.namelist()), 2)

    def test_glob_picks_most_recent_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            older = root / "z.log"
            newer = root / "a.log"
            older.write_bytes(b"old")
            newer.write_bytes(b"new")
            os.utime(older, (1, 1))
            os.utime(newer, (2, 2))
            script = {"display_name": "A", "script_path": "a.py"}
            with patch(
                "src.log.log_archive.resolve_log_path", return_value=root / "*.log"
            ):
                data = build_log_archive([script], {"A"})
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                self.assertEqual(archive.read("01-A/实时/a.log"), b"new")

    def test_mail_receives_selected_scripts_even_without_parser_entries(self):
        from src.service.schedule import build_post_run_pipeline

        with (
            patch("src.service.schedule.analyze_logs", return_value={"entries": []}),
            patch("src.service.schedule.send_summary_mail") as send,
        ):
            steps = build_post_run_pipeline(
                shutdown_delay=None,
                smtp_config={"enabled": True},
                enabled_keys={"B", "A"},
            )
            for step in steps:
                step()
        self.assertEqual(send.call_args.args[0]["log_script_names"], ["A", "B"])

    def test_selected_logs_are_capped_and_zip_contains_exact_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            large = root / "large.log"
            large.write_bytes(b"prefix" + b"x" * MAX_LOG_BYTES)
            other = root / "other.log"
            other.write_bytes(b"not selected")
            scripts = [
                {"display_name": "A", "script_path": "a.py"},
                {"display_name": "B", "script_path": "b.py"},
            ]
            with patch(
                "src.log.log_archive.resolve_log_path",
                side_effect=lambda script, analysis=False: (
                    large if script["display_name"] == "A" else other
                ),
            ):
                data = build_log_archive(scripts, {"A"})
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                self.assertEqual(
                    archive.read("01-A/实时/large.log"), b"x" * MAX_LOG_BYTES
                )
                self.assertEqual(archive.namelist(), ["01-A/实时/large.log"])

    def test_missing_file_does_not_prevent_other_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "game.log"
            path.write_bytes(b"ok")
            script = {"display_name": "A", "script_path": "a.py"}
            with patch(
                "src.log.log_archive.resolve_log_path",
                side_effect=[path, Path(directory) / "missing"],
            ):
                data = build_log_archive([script], {"A"})
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                self.assertEqual(archive.read("01-A/实时/game.log"), b"ok")
                self.assertEqual(len(archive.namelist()), 1)
