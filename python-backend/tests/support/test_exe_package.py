"""前端专用产物测试按清单选择，不以共用 CLI 文件判断。"""

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from updater import UpdateError
from updater.utils import file_digest

from src.update import CLI_EXE, VERSION_FILE, client
from tests.exe import is_frontend_package
from tests.support.update_package import (
    archive_package,
    make_package,
    prepare_archive,
    prepare_package,
    program_snapshot,
)


class ExePackageTests(unittest.TestCase):
    def test_shared_zip_produces_separate_verified_install_workspaces(self):
        package = make_package(self.directory / "package", "2.0.0")
        archive = archive_package(package, self.directory / "shared.zip")
        before = file_digest(archive)
        roots = [make_package(self.directory / name) for name in ("one", "two")]
        prepared = [prepare_archive(root, archive, "2.0.0", "qt") for root in roots]
        self.assertNotEqual(prepared[0].directory, prepared[1].directory)
        (prepared[0].directory / "package/config/config.example.yml").write_bytes(
            b"modified"
        )
        self.assertNotEqual(
            (prepared[0].directory / "package/config/config.example.yml").read_bytes(),
            (prepared[1].directory / "package/config/config.example.yml").read_bytes(),
        )
        client(roots[1], "1.0.0", "qt").install(prepared[1])
        self.assertEqual(file_digest(archive), before)

    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_changed_exe_fixture_rebuilds_optional_manifest(self):
        root = make_package(self.directory / "package", "2.0.0", frontend="rust")
        (root / "update-manifest.json").write_text("old manifest", encoding="utf-8")
        (root / "config/config.yml").write_bytes(b"personal")
        example = root / "config/config.example.yml"
        example.write_bytes(b"changed template")
        archive = archive_package(root, self.directory / "package.zip")
        with zipfile.ZipFile(archive) as bundle:
            manifest = json.loads(bundle.read("OneDragon-Helper/update-manifest.json"))
        self.assertEqual(manifest["version"], "2.0.0")
        self.assertEqual(manifest["frontend"], "rust")
        self.assertEqual(
            manifest["files"]["config/config.example.yml"], file_digest(example)
        )
        self.assertNotIn("config/config.yml", manifest["files"])
        self.assertNotIn("update-manifest.json", manifest["files"])

    def test_program_snapshot_excludes_local_data_and_detects_program_changes(self):
        root = make_package(self.directory / "installed")
        user = root / "config/config.yml"
        user.write_text("before", encoding="utf-8")
        logs = root / ".log"
        logs.mkdir()
        (logs / "runner.log").write_text("before", encoding="utf-8")
        prepared = prepare_package(root, root, "1.0.0", "qt")
        client(root, "0", "qt").install(prepared)
        before = program_snapshot(root)
        user.write_text("personal", encoding="utf-8")
        (logs / "runner.log").write_text("new log", encoding="utf-8")
        self.assertEqual(program_snapshot(root), before)
        (root / "version.json").write_text('{"version":"2.0.0"}', encoding="utf-8")
        self.assertNotEqual(program_snapshot(root), before)

    def test_qt_package_with_cli_does_not_select_rust_tests(self):
        package = make_package(self.directory / "qt")
        (package / CLI_EXE).write_bytes(b"cli")
        self.assertTrue(is_frontend_package(package, "qt"))
        self.assertFalse(is_frontend_package(package, "rust"))

    def test_rust_package_selects_rust_tests(self):
        package = make_package(self.directory / "rust", frontend="rust")
        self.assertTrue(is_frontend_package(package, "rust"))
        self.assertFalse(is_frontend_package(package, "qt"))

    def test_missing_version_skips_but_invalid_version_is_not_hidden(self):
        self.assertFalse(is_frontend_package(self.directory, "rust"))
        package = make_package(self.directory / "invalid")
        path = package / VERSION_FILE
        data = json.loads(path.read_text(encoding="utf-8"))
        data["frontend"] = "invalid"
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(UpdateError):
            is_frontend_package(package, "rust")
