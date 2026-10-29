"""Skill 发布归档的内容、完整性和路径边界。"""

import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from tools import package_skill


class TestPackageSkill(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.skill = self.root / "source" / "onedragon-helper"
        self.output = self.root / "dist" / "onedragon-helper-skill.zip"
        self.contents = {
            name: f"测试内容：{name}\n".encode()
            for name in (
                "SKILL.md",
                "references/cli.md",
                "scripts/odh.py",
                "scripts/source_cache.py",
                "scripts/log_tools.py",
            )
        }
        for name, content in self.contents.items():
            path = self.skill / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

    def test_archive_contains_only_required_files_and_matching_checksum(self):
        for name in ("private.json", "logs/run.log", "scripts/__pycache__/odh.pyc"):
            path = self.skill / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"local data must stay private")

        package_skill.archive_skill(self.skill, self.output)

        with zipfile.ZipFile(self.output) as archive:
            self.assertEqual(
                sorted(archive.namelist()),
                sorted(f"onedragon-helper/{name}" for name in self.contents),
            )
            for name, content in self.contents.items():
                self.assertEqual(archive.read(f"onedragon-helper/{name}"), content)
        digest = hashlib.sha256(self.output.read_bytes()).hexdigest()
        checksum = self.output.with_suffix(".zip.sha256")
        self.assertEqual(
            checksum.read_text(encoding="ascii"),
            f"{digest}  {self.output.name}\n",
        )

    def test_missing_file_preserves_existing_archive_and_checksum(self):
        self.output.parent.mkdir()
        self.output.write_bytes(b"previous archive")
        checksum = self.output.with_suffix(".zip.sha256")
        checksum.write_bytes(b"previous checksum")
        for name, content in self.contents.items():
            with self.subTest(missing=name):
                path = self.skill / name
                path.unlink()
                try:
                    with self.assertRaises(FileNotFoundError):
                        package_skill.archive_skill(self.skill, self.output)
                    self.assertEqual(self.output.read_bytes(), b"previous archive")
                    self.assertEqual(checksum.read_bytes(), b"previous checksum")
                finally:
                    path.write_bytes(content)

    def test_output_inside_skill_is_rejected(self):
        for name in ("skill.zip", "dist/skill.zip"):
            with self.subTest(output=name):
                output = self.skill / name
                with self.assertRaises(ValueError):
                    package_skill.archive_skill(self.skill, output)
                self.assertFalse(output.exists())

    def test_symlink_in_source_path_is_rejected(self):
        for target in (
            self.root,
            self.skill.parent,
            self.skill,
            self.skill / "scripts",
            self.skill / "scripts" / "odh.py",
        ):
            with (
                self.subTest(symlink=target),
                patch.object(
                    Path, "is_symlink", lambda path, target=target: path == target
                ),
                self.assertRaises(ValueError),
            ):
                package_skill.archive_skill(self.skill, self.output)
            self.assertFalse(self.output.exists())
