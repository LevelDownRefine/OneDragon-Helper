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

    def test_only_current_failure_images_are_archived_with_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index in range(7):
                path = root / f"{index}.png"
                path.write_bytes(f"image-{index}".encode())
                os.utime(path, (index, index))
            script = {"display_name": "A", "script_path": "a.py"}
            with patch(
                "src.log.log_archive.resolve_log_path",
                side_effect=lambda script, analysis=False, failure_image=False: (
                    root / "*.png" if failure_image else None
                ),
            ):
                data = build_log_archive([script], {"A"}, not_before=2)
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                self.assertEqual(
                    archive.namelist(),
                    [f"01-A/失败截图/{index}.png" for index in (6, 5, 4, 3)],
                )
                self.assertEqual(archive.read("01-A/失败截图/6.png"), b"image-6")

    def test_maa_failure_image_path_is_declared_relative_to_script(self):
        from src.utils.utils_sub_config import resolve_log_path

        with tempfile.TemporaryDirectory() as directory:
            script = {
                "display_name": "MAA",
                "script_path": str(Path(directory) / "MAA.exe"),
            }
            self.assertEqual(
                resolve_log_path(script, failure_image=True),
                Path(directory) / "debug/interface/*.png",
            )

    def test_ok_and_maaend_existing_image_paths(self):
        from src.utils.utils_sub_config import resolve_log_path

        with tempfile.TemporaryDirectory() as directory:
            for name in ("ok-ap", "ok-ww", "ok-nte", "ok-ef", "MaaEnd"):
                with self.subTest(name=name):
                    script = {
                        "display_name": name,
                        "script_path": str(Path(directory) / f"{name}.exe"),
                    }
                    relative = (
                        "debug/on_error/*"
                        if name == "MaaEnd"
                        else f"data/apps/{name}/working/screenshots/*.png"
                    )
                    self.assertEqual(
                        resolve_log_path(script, failure_image=True),
                        Path(directory) / relative,
                    )

    def test_march7th_and_onedragon_image_paths(self):
        from src.utils.utils_sub_config import resolve_log_path

        with tempfile.TemporaryDirectory() as directory:
            for name, relative in (
                ("March7th-Launcher", "logs/screenshots/error_*.png"),
                ("OneDragon-Launcher", ".debug/images/*.png"),
            ):
                with self.subTest(name=name):
                    script = {
                        "display_name": name,
                        "script_path": str(Path(directory) / f"{name}.exe"),
                    }
                    self.assertEqual(
                        resolve_log_path(script, failure_image=True),
                        Path(directory) / relative,
                    )

    def test_nested_images_keep_paths_and_ignore_old_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for folder, stamp in (("failed", 20), ("log", 20), ("old", 1)):
                path = root / folder / "same.png"
                path.parent.mkdir()
                path.write_bytes(folder.encode())
                os.utime(path, (stamp, stamp))
            with patch(
                "src.log.log_archive.resolve_log_path",
                side_effect=lambda script, analysis=False, failure_image=False: (
                    root / "*.png" if failure_image else None
                ),
            ):
                data = build_log_archive(
                    [{"display_name": "A", "script_path": "a.py"}], {"A"}, 10
                )
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                self.assertEqual(
                    set(archive.namelist()),
                    {"01-A/失败截图/failed/same.png", "01-A/失败截图/log/same.png"},
                )
                self.assertEqual(
                    archive.read("01-A/失败截图/failed/same.png"), b"failed"
                )
