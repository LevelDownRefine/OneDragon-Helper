"""下载包的路径、内容与版本边界。"""

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from src.update.package import (
    MANIFEST,
    UpdateError,
    load_manifest,
    managed_path,
    parse_manifest,
    safe_target,
    unpack_package,
    version_number,
)
from tests.support.update_package import archive_package, make_package


class TestUpdatePackage(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.package = make_package(self.directory / "source", "1.2.0")

    def test_semantic_version_order(self):
        self.assertGreater(version_number("1.10.0"), version_number("1.9.0"))
        self.assertGreater(version_number("1.0.0"), version_number("1.0.0-rc.1"))

    def test_zip_round_trip_verifies_program_bytes(self):
        archive = archive_package(self.package, self.directory / "package.zip")
        target = self.directory / "unpacked"
        self.assertEqual(unpack_package(archive, target, "1.2.0")["version"], "1.2.0")
        self.assertEqual((target / "_internal/python.dll").read_bytes(), b"runtime")

    def test_invalid_paths_are_rejected(self):
        for name in (
            "../app.exe",
            "/app.exe",
            "assets/../../config/config.yml",
            "assets\\file",
            "assets/NUL.txt",
            "assets/a:stream",
            "assets/a.",
            "assets/a ",
            "config/config.yml",
            "config/SCHEDULE.YML",
            "config/weekly.yml",
            "config/wallpaper.json",
            "config/backups/a.zip",
            "assets/a.bak2",
            "assets/BANNER.JPG",
            "logs/a.log",
            ".update/intent.lock",
        ):
            with self.subTest(name=name):
                self.assertFalse(managed_path(name))

    def test_existing_symlink_cannot_redirect_program_writes(self):
        outside = self.directory / "personal"
        outside.mkdir()
        (self.package / "assets").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(UpdateError, "链接"):
            safe_target(self.package, "assets/example.txt")
        self.assertFalse((outside / "example.txt").exists())

    def test_manifest_rejects_case_duplicates_and_file_directory_conflicts(self):
        for names in (("assets/a", "assets/A"), ("assets/a", "assets/a/b")):
            with self.subTest(names=names):
                data = load_manifest(self.package)
                data["files"].update(dict.fromkeys(names, "0" * 64))
                with self.assertRaises(UpdateError):
                    parse_manifest(data)

    def test_corrupt_file_is_rejected(self):
        (self.package / "_internal/python.dll").write_bytes(b"corrupt")
        archive = archive_package(self.package, self.directory / "corrupt.zip")
        with self.assertRaisesRegex(UpdateError, "校验失败"):
            unpack_package(archive, self.directory / "unpacked", "1.2.0")

    def test_wrong_version_and_extra_user_file_are_rejected_before_unpack(self):
        for extra in (False, True):
            with self.subTest(extra=extra):
                archive = archive_package(self.package, self.directory / "bad.zip")
                if extra:
                    with zipfile.ZipFile(archive, "a") as output:
                        output.writestr("OneDragon-Helper/config/config.yml", "secret")
                destination = self.directory / "unpacked"
                with self.assertRaises(UpdateError):
                    unpack_package(archive, destination, "1.2.0" if extra else "1.3.0")
                self.assertFalse(destination.exists())

    def test_zip_duplicate_symlink_and_path_traversal_are_rejected(self):
        for name, link in (
            ("OneDragon-Helper/assets/../secret", False),
            ("OneDragon-Helper/assets/link", True),
            ("outside.txt", False),
            ("OneDragon-Helper/VERSION.JSON", False),
        ):
            with self.subTest(name=name):
                archive = archive_package(self.package, self.directory / "bad.zip")
                with zipfile.ZipFile(archive, "a") as output:
                    info = zipfile.ZipInfo(name)
                    if link:
                        info.external_attr = 0o120777 << 16
                    output.writestr(info, "bad")
                with self.assertRaises(UpdateError):
                    unpack_package(archive, self.directory / "unpacked", "1.2.0")

    def test_manifest_cannot_own_user_files(self):
        path = self.package / MANIFEST
        data = json.loads(path.read_text())
        data["files"]["config/config.yml"] = "0" * 64
        path.write_text(json.dumps(data))
        with self.assertRaises(UpdateError):
            load_manifest(self.package)
