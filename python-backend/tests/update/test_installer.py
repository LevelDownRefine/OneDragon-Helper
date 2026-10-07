"""安装事务只影响程序清单中的文件，替换可容忍瞬时占用且中断可补完。"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.update import installer
from src.update.package import UpdateError, load_manifest
from tests.support.update_package import (
    make_package,
    program_snapshot,
    stage_interrupted_install,
)


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

    def test_files_whose_content_already_matches_are_not_replaced(self):
        unchanged = "OneDragon-Helper.exe"
        (self.root / unchanged).write_bytes((self.new / unchanged).read_bytes())
        replaced = []
        real_replace = installer._replace

        def record(source, target, temporary):
            replaced.append(target.relative_to(self.root).as_posix())
            return real_replace(source, target, temporary)

        with patch.object(installer, "_replace", side_effect=record):
            installer.install_package(self.root, self.new)
        self.assertEqual(load_manifest(self.root, verify=True)["version"], "2.0.0")
        self.assertIn("assets/new.txt", replaced)
        self.assertNotIn(unchanged, replaced)
        # 运行库两版本本就同内容，同样不该重写
        self.assertNotIn("_internal/python.dll", replaced)

    def test_transient_occupation_is_retried(self):
        victim = self.root / "assets/new.txt"
        real_replace = os.replace
        attempts = []

        def occupied(source, target):
            if target == victim:
                attempts.append(target)
                if len(attempts) <= 2:
                    raise PermissionError(13, "拒绝访问", str(target), 5)
            return real_replace(source, target)

        with (
            patch.object(installer.os, "replace", side_effect=occupied),
            patch.object(installer.time, "sleep") as sleep,
            self.assertLogs(installer.__name__, level="WARNING"),
        ):
            installer.install_package(self.root, self.new)
        self.assertEqual(len(attempts), 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual(load_manifest(self.root, verify=True)["version"], "2.0.0")

    def test_permanent_failure_is_not_retried(self):
        victim = self.root / "assets/new.txt"
        real_replace = os.replace
        attempts = []

        def missing(source, target):
            if target == victim:
                attempts.append(target)
                raise FileNotFoundError(2, "文件不存在", str(target))
            return real_replace(source, target)

        with (
            patch.object(installer.os, "replace", side_effect=missing),
            patch.object(installer.time, "sleep") as sleep,
            self.assertLogs(installer.__name__, level="ERROR"),
            self.assertRaises(FileNotFoundError),
        ):
            installer.install_package(self.root, self.new)
        self.assertEqual(len(attempts), 1)
        sleep.assert_not_called()


class TestUpdateSettlement(unittest.TestCase):
    """启动闸门只在能证明目录自洽时补完中断的事务。"""

    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.root = make_package(self.directory / "app")
        self.package = make_package(self.directory / "prepared", "2.0.0")
        self.journal = self.root / ".update/transaction.json"
        self.journal.parent.mkdir(parents=True, exist_ok=True)

    def prepare(self):
        """摆出中断现场：安装目录已是 2.0.0 的程序文件，包还留在 .update 里。"""
        shutil.copytree(self.package, self.root / ".update/download-v2.0.0/package")
        stage_interrupted_install(self.root, self.package)

    def write_phase(self, phase):
        self.journal.write_text(json.dumps({"phase": phase}), encoding="utf-8")

    def phase(self):
        return json.loads(self.journal.read_text(encoding="utf-8"))["phase"]

    def test_settlement_adopts_matching_prepared_package(self):
        self.prepare()
        self.assertTrue(installer.settle_transaction(self.root))
        self.assertEqual(load_manifest(self.root, verify=True)["version"], "2.0.0")
        self.assertEqual(self.phase(), "committed")
        self.assertFalse(installer.recover_installation(self.root))

    def test_settlement_refuses_when_program_files_differ(self):
        self.prepare()
        (self.root / "OneDragon-Helper.exe").write_bytes(b"damaged")
        self.assertFalse(installer.settle_transaction(self.root))
        self.assertEqual(self.phase(), "installing")

    def test_settlement_ignores_prepared_package_that_is_not_newer(self):
        # 目录仍是 1.0.0，包也只是同版本：没有升级可采信，不能当作已提交
        stale = self.root / ".update/download-v1.0.0/package"
        stale.mkdir(parents=True)
        for name in ("update-manifest.json", "version.json"):
            shutil.copy2(self.root / name, stale / name)
        self.write_phase("installing")
        self.assertFalse(installer.settle_transaction(self.root))
        self.assertEqual(self.phase(), "installing")

    def test_settlement_refuses_unknown_phase(self):
        for phase in ("installing-unknown", "verifying"):
            with self.subTest(phase=phase):
                self.write_phase(phase)
                self.assertFalse(installer.settle_transaction(self.root))

    def test_settlement_leaves_settled_or_absent_journal_alone(self):
        for phase in ("committed", "rolled_back"):
            with self.subTest(phase=phase):
                self.write_phase(phase)
                self.assertTrue(installer.settle_transaction(self.root))
                self.assertEqual(load_manifest(self.root)["version"], "1.0.0")
        self.journal.unlink()
        self.assertTrue(installer.settle_transaction(self.root))
        self.assertEqual(load_manifest(self.root)["version"], "1.0.0")
