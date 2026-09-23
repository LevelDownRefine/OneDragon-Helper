"""升级与恢复只影响程序清单中的文件。"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.service import update_installer as installer
from src.service.update_package import UpdateError, load_manifest
from tests.support.update_package import make_package, program_snapshot


class InterruptedInstall(BaseException):
    """模拟进程被终止，跳过进程内异常恢复。"""


class TestUpdateInstaller(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.root = make_package(
            self.directory / "app", extra={"assets/obsolete.txt": b"old"}
        )
        self.new = make_package(
            self.directory / "new", "2.0.0", {"assets/new.txt": b"new"}
        )
        self.user_files = {}
        for name in (
            "config/config.yml",
            "config/schedule.yml",
            "config/weekly.yml",
            "config/wallpaper.json",
            "config/wallpaper_cache/a.jpg",
            "config/backups/a.zip",
            "config/config.yml.bak",
            "config/script_chain/today.yml",
            "assets/custom.jpg",
            "logs/a.log",
            ".log/a.log",
        ):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"user bytes")
            self.user_files[name] = path.read_bytes()
        self.before = program_snapshot(self.root)

    def assert_user_files(self):
        self.assertEqual(
            {name: (self.root / name).read_bytes() for name in self.user_files},
            self.user_files,
        )

    def test_upgrade_replaces_program_and_removes_only_obsolete_files(self):
        installer.install_package(self.root, self.new)
        self.assertEqual(load_manifest(self.root, verify=True)["version"], "2.0.0")
        self.assertFalse((self.root / "assets/obsolete.txt").exists())
        self.assertEqual((self.root / "assets/new.txt").read_bytes(), b"new")
        self.assert_user_files()
        self.assertFalse(installer.recover_installation(self.root))

    def test_existing_unowned_file_blocks_installation(self):
        (self.root / "assets/new.txt").write_bytes(b"personal")
        with self.assertRaisesRegex(UpdateError, "用户文件冲突"):
            installer.install_package(self.root, self.new)
        self.assertEqual(program_snapshot(self.root), self.before)
        self.assertEqual((self.root / "assets/new.txt").read_bytes(), b"personal")

    def test_install_error_rolls_back_and_removes_new_files(self):
        real_replace = installer._replace

        def fail_once(source, target, temporary):
            if source == self.new / "config/config.example.yml":
                raise PermissionError("file in use")
            return real_replace(source, target, temporary)

        with (
            patch.object(installer, "_replace", side_effect=fail_once),
            self.assertLogs(installer.__name__, level="ERROR"),
            self.assertRaises(PermissionError),
        ):
            installer.install_package(self.root, self.new)
        self.assertEqual(program_snapshot(self.root), self.before)
        self.assertFalse((self.root / "assets/new.txt").exists())
        self.assert_user_files()

    def interrupt(self):
        real_replace = installer._replace

        def stop(source, target, temporary):
            if source == self.new / "config/config.example.yml":
                raise InterruptedInstall()
            return real_replace(source, target, temporary)

        with (
            patch.object(installer, "_replace", side_effect=stop),
            self.assertRaises(InterruptedInstall),
        ):
            installer.install_package(self.root, self.new)

    def test_restart_recovers_interrupted_install_idempotently(self):
        self.interrupt()
        self.assertTrue(installer.recover_installation(self.root))
        self.assertFalse(installer.recover_installation(self.root))
        self.assertEqual(program_snapshot(self.root), self.before)
        self.assert_user_files()

    def test_corrupt_snapshot_blocks_recovery_without_further_changes(self):
        self.interrupt()
        journal = json.loads((self.root / ".update/transaction.json").read_text())
        backup = (
            self.root / ".update" / journal["transaction"] / "previous" / "version.json"
        )
        backup.write_bytes(b"damaged")
        observed = (self.root / "OneDragon-Helper.exe").read_bytes()
        with self.assertRaisesRegex(UpdateError, "快照损坏"):
            installer.recover_installation(self.root)
        self.assertEqual((self.root / "OneDragon-Helper.exe").read_bytes(), observed)

    def test_same_version_and_downgrade_are_rejected(self):
        for version in ("1.0.0", "0.9.0"):
            with self.subTest(version=version):
                candidate = make_package(self.directory / version, version)
                with self.assertRaisesRegex(UpdateError, "没有高于"):
                    installer.install_package(self.root, candidate)
                self.assertEqual(program_snapshot(self.root), self.before)
