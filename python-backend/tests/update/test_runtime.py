"""应用启动恢复和独立安装；实际更新库配合临时安装目录。"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from updater import UpdateError
from updater.utils import FileLease, UpdateBusyError, file_digest, write_json

from src.update import application_lease, read_version, run_update
from tests.support.update_package import make_package, prepare_package, program_snapshot


class UpdateRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(
            self.enterContext(tempfile.TemporaryDirectory())
        ).resolve()
        self.root = make_package(self.directory / "installed")

    def test_worker_installs_plain_zip_and_preserves_unpublished_local_files(self):
        for frontend in ("qt", "rust"):
            with self.subTest(frontend=frontend):
                root = make_package(self.directory / frontend, frontend=frontend)
                target = make_package(
                    self.directory / (frontend + "-next"), "2.0.0", frontend=frontend
                )
                user = root / "config/config.yml"
                user.write_bytes(b"local configuration")
                prepared = prepare_package(root, target, "2.0.0", frontend)
                run_update(root, prepared, frontend=frontend)
                self.assertEqual(read_version(root)["version"], "2.0.0")
                self.assertEqual(user.read_bytes(), b"local configuration")
                self.assertFalse((root / "update-manifest.json").exists())
                self.assertFalse(prepared.directory.exists())
                self.assertEqual(
                    json.loads((root / ".update/github-installed.json").read_text())[
                        "version"
                    ],
                    "2.0.0",
                )

    def test_startup_recovers_before_acquiring_shared_runtime_lease(self):
        previous = self.root / ".update" / ("a" * 32) / "previous/version.json"
        previous.parent.mkdir(parents=True)
        shutil.copy2(self.root / "version.json", previous)
        write_json(
            self.root / ".update/github-transaction.json",
            {
                "phase": "installing",
                "transaction": "a" * 32,
                "originals": {"version.json": file_digest(previous)},
                "inventory": None,
            },
        )
        (self.root / "version.json").write_text("incomplete", encoding="utf-8")
        with application_lease(self.root):
            self.assertEqual(read_version(self.root)["version"], "1.0.0")
            with (
                self.assertRaises(UpdateBusyError),
                FileLease(self.root / ".update/runtime.lock"),
            ):
                self.fail("running application must hold a shared lease")
        self.assertEqual(
            json.loads((self.root / ".update/result.json").read_text()),
            {"status": "recovered"},
        )
        with application_lease(self.root):
            self.assertEqual(read_version(self.root)["version"], "1.0.0")

    def test_update_gate_blocks_start_and_running_task_blocks_install(self):
        with (
            FileLease(self.root / ".update/intent.lock"),
            self.assertRaises(UpdateBusyError),
            application_lease(self.root),
        ):
            self.fail("startup gate must reject startup")
        target = make_package(self.directory / "next", "2.0.0")
        prepared = prepare_package(self.root, target, "2.0.0", "qt")
        before = program_snapshot(self.root)
        with (
            patch("src.update.application_processes", return_value=[1234]),
            self.assertRaises(UpdateBusyError),
        ):
            run_update(self.root, prepared)
        self.assertEqual(program_snapshot(self.root), before)
        self.assertTrue(prepared.directory.is_dir())

    def test_cancelled_handoff_and_tampered_package_never_modify_application(self):
        target = make_package(self.directory / "next", "2.0.0")
        prepared = prepare_package(self.root, target, "2.0.0", "qt")
        before = program_snapshot(self.root)
        cancel = self.directory / "cancel"
        cancel.touch()
        with self.assertRaises(UpdateBusyError):
            run_update(self.root, prepared, cancel=cancel)
        (prepared.directory / "package/config/config.example.yml").write_bytes(
            b"tampered"
        )
        with self.assertRaises(UpdateError):
            run_update(self.root, prepared)
        self.assertEqual(program_snapshot(self.root), before)

    def test_malformed_journal_rejects_startup_as_update_error(self):
        (self.root / ".update").mkdir()
        contents = [
            json.dumps({"phase": phase}) for phase in ([], {}, None, 1, "unknown")
        ]
        contents += ["", "incomplete"]
        for content in contents:
            with self.subTest(content=content):
                (self.root / ".update/github-transaction.json").write_text(
                    content, encoding="utf-8"
                )
                with self.assertRaises(UpdateError), application_lease(self.root):
                    self.fail("invalid journal must reject startup")

    def test_cache_cleanup_failure_keeps_successful_installation(self):
        target = make_package(self.directory / "next", "2.0.0")
        prepared = prepare_package(self.root, target, "2.0.0", "qt")
        with (
            patch("src.update.remove_directory", side_effect=PermissionError("busy")),
            self.assertLogs("src.update", level="WARNING"),
        ):
            run_update(self.root, prepared)
        self.assertEqual(read_version(self.root)["version"], "2.0.0")
        self.assertTrue(prepared.directory.is_dir())
