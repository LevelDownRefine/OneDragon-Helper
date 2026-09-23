"""发布资源边界、版本信息与归档校验。"""

import hashlib
import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from tools import release_package as release


class TestReleasePackage(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(directory) / "repo"
        self.root.mkdir()
        self.package = Path(directory) / "OneDragon-Helper"
        self.package.mkdir()
        self.resources = {
            "README.md": "readme",
            "config/config.example.yml": "script_list: []\n",
            "config/schedule.example.yml": "daily_run: {}\n",
            "config/weekly.example.yml": "weekly_start: {}\n",
            "config/daily_task_list.yml": "日常: []\n",
            "assets/ds.jpg": "image",
            "src/gui/qml/main.qml": "Window {}",
        }
        for name, content in self.resources.items():
            self.write(self.root, name, content)
        self.write(self.root, "pyproject.toml", '[project]\nversion = "0.0.1"\n')
        self.git("init", "--quiet")
        self.git("add", "--", *self.resources, "pyproject.toml")
        self.git(
            "-c",
            "user.name=Package Test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.hooksPath=/dev/null",
            "commit",
            "--quiet",
            "-m",
            "test: resources",
        )
        for name in (
            release.EXE_NAME,
            release.RUNNER_NAME,
            release.UPDATER_EXE,
            "_internal/python.dll",
        ):
            self.write(self.package, name, "binary")

    def git(self, *args):
        return subprocess.run(
            ["git", *args], cwd=self.root, check=True, capture_output=True, text=True
        ).stdout.strip()

    def write(self, root, name, content):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_prepare_copies_only_tracked_resources_and_release_version(self):
        personal = (
            "config/config.yml",
            "config/schedule.yml",
            "config/weekly.yml",
            "config/wallpaper.json",
            "config/wallpaper_cache/custom.jpg",
            "config/backups/private.zip",
            "config/script_chain/today.yml",
            "config/config.yml.bak2",
            "logs/helper.log",
            ".log/runner.log",
            "assets/banner.jpg",
            "assets/untracked.jpg",
        )
        for name in personal:
            self.write(self.root, name, "personal")
        release.prepare_package(self.root, self.package, "v1.2.3")
        actual = {
            p.relative_to(self.package).as_posix()
            for p in release.validate_package(self.root, self.package)
        }
        self.assertEqual(
            actual,
            set(self.resources)
            | {
                release.EXE_NAME,
                release.RUNNER_NAME,
                release.UPDATER_EXE,
                release.MANIFEST,
                release.VERSION_FILE,
                "_internal/python.dll",
            },
        )
        for name in personal:
            self.assertEqual((self.root / name).read_text(encoding="utf-8"), "personal")
        self.assertEqual(
            json.loads(
                (self.package / release.VERSION_FILE).read_text(encoding="utf-8")
            ),
            {
                "version": "1.2.3",
                "tag": "v1.2.3",
                "commit": self.git("rev-parse", "HEAD"),
            },
        )

    def test_development_build_is_identified_by_commit(self):
        release.prepare_package(self.root, self.package)
        info = json.loads(
            (self.package / release.VERSION_FILE).read_text(encoding="utf-8")
        )
        self.assertEqual(
            info["version"], "0.0.1+dev." + self.git("rev-parse", "HEAD")[:7]
        )
        self.assertEqual(info["tag"], "")

    def test_invalid_release_tag_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "发布 tag"):
            release.prepare_package(self.root, self.package, "main")
        self.assertFalse((self.package / release.VERSION_FILE).exists())

    def test_tracked_user_files_are_rejected_without_modifying_them(self):
        for name in (
            "config/config.yml",
            "config/schedule.yml",
            "config/weekly.yml",
            "config/wallpaper.json",
            "config/config.yml.bak2",
            "assets/banner.jpg",
        ):
            with self.subTest(name=name):
                path = self.write(self.root, name, "personal")
                self.git("add", "--", name)
                with self.assertRaisesRegex(ValueError, "用户文件"):
                    release.resource_files(self.root)
                self.assertEqual(path.read_text(encoding="utf-8"), "personal")
                self.git("reset", "--quiet", "HEAD", "--", name)

    def test_validation_rejects_runtime_files_and_unknown_assets(self):
        release.prepare_package(self.root, self.package)
        for name in (
            "config/config.yml",
            "config/schedule.yml",
            "config/weekly.yml",
            "config/notify_mail.yml",
            "config/wallpaper.json",
            "config/gui_state.json",
            "config/config.yml.bak2",
            "assets/banner.jpg",
            "assets/private.jpg",
        ):
            with self.subTest(name=name):
                path = self.write(self.package, name, "personal")
                with self.assertRaisesRegex(ValueError, "非程序文件"):
                    release.validate_package(self.root, self.package)
                self.assertEqual(path.read_text(encoding="utf-8"), "personal")
                path.unlink()
        for name in (
            "logs",
            ".log",
            "config/backups",
            "config/wallpaper_cache",
            "config/script_chain",
        ):
            with self.subTest(directory=name):
                directory = self.package / name
                directory.mkdir()
                with self.assertRaisesRegex(ValueError, "非程序目录"):
                    release.validate_package(self.root, self.package)
                directory.rmdir()

    def test_missing_template_blocks_publication(self):
        release.prepare_package(self.root, self.package)
        (self.package / "config/config.example.yml").unlink()
        with self.assertRaisesRegex(ValueError, "config/config.example.yml"):
            release.validate_package(self.root, self.package)

    def test_runtime_file_added_after_manifest_blocks_publication(self):
        release.prepare_package(self.root, self.package)
        self.write(self.package, "_internal/unlisted.dll", "unknown")
        with self.assertRaisesRegex(ValueError, "更新清单不一致"):
            release.validate_package(self.root, self.package)

    def test_archive_contains_checked_files_and_matching_checksum(self):
        release.prepare_package(self.root, self.package, "v1.2.3")
        output = self.package.parent / "OneDragon-Helper.zip"
        release.archive_package(self.root, self.package, output)
        with zipfile.ZipFile(output) as archive:
            expected = {
                f"OneDragon-Helper/{path.relative_to(self.package).as_posix()}"
                for path in release.validate_package(self.root, self.package)
            }
            self.assertEqual(set(archive.namelist()), expected)
            self.assertEqual(
                archive.read("OneDragon-Helper/config/config.example.yml"),
                b"script_list: []\n",
            )
        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        self.assertEqual(
            output.with_suffix(".zip.sha256").read_text(encoding="ascii"),
            f"{digest}  OneDragon-Helper.zip\n",
        )

    def test_archive_rejects_contamination_before_creating_zip(self):
        release.prepare_package(self.root, self.package)
        self.write(self.package, "config/schedule.yml", "private")
        output = self.package.parent / "release.zip"
        with self.assertRaisesRegex(ValueError, "非程序文件"):
            release.archive_package(self.root, self.package, output)
        self.assertFalse(output.exists())

    def test_exe_tests_run_in_copy_and_propagate_failure(self):
        release.prepare_package(self.root, self.package)
        real_run = subprocess.run
        copies = []

        def run(command, **kwargs):
            if command[0] == "git":
                return real_run(command, **kwargs)
            env = kwargs["env"]
            sandbox = Path(env["ODH_PACKAGE_DIR"])
            copies.append(sandbox)
            self.assertNotEqual(sandbox, self.package)
            self.assertEqual(Path(env["ODH_GUI_EXE"]), sandbox / release.EXE_NAME)
            self.assertEqual(Path(env["ODH_RUNNER_EXE"]), sandbox / release.RUNNER_NAME)
            self.write(sandbox, "config/config.yml", "test config")
            self.write(sandbox, "logs/test.log", "test log")
            return subprocess.CompletedProcess(command, 1)

        with patch.object(release.subprocess, "run", side_effect=run):
            self.assertEqual(release.test_package(self.root, self.package), 1)
        self.assertEqual(len(copies), 1)
        self.assertFalse(copies[0].exists())
        self.assertFalse((self.package / "config/config.yml").exists())
        self.assertFalse((self.package / "logs").exists())
        release.validate_package(self.root, self.package)
