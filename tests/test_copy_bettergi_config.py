from pathlib import Path
import tempfile
import unittest

import yaml

from copy_bettergi_config import copy_bettergi_config, find_bettergi_path


def write_config(path: Path, script_path: str):
    path.write_text(
        yaml.safe_dump({"script_list": [{"script_path": script_path}]}, allow_unicode=True),
        encoding="utf-8",
    )


class CopyBetterGIConfigTest(unittest.TestCase):
    def test_find_bettergi_path_reads_01_yml(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config_file = temp_path / "01.yml"
            bettergi_exe = temp_path / "BetterGI" / "BetterGI.exe"
            write_config(config_file, str(bettergi_exe))

            self.assertEqual(find_bettergi_path(config_file), bettergi_exe)

    def test_find_bettergi_path_raises_when_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "01.yml"
            config_file.write_text(yaml.safe_dump({"script_list": []}), encoding="utf-8")

            with self.assertRaises(FileNotFoundError):
                find_bettergi_path(config_file)

    def test_copy_bettergi_config_copies_files_and_dirs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_dir = temp_path / "source"
            target_dir = temp_path / "target"
            config_file = temp_path / "01.yml"
            source_dir.mkdir()
            target_dir.mkdir()
            (source_dir / "root.json").write_text("root", encoding="utf-8")
            (source_dir / "User").mkdir()
            (source_dir / "User" / "settings.json").write_text("settings", encoding="utf-8")
            write_config(config_file, str(target_dir / "BetterGI.exe"))

            copied_to = copy_bettergi_config(source_dir, config_file)

            self.assertEqual(copied_to, target_dir)
            self.assertEqual((target_dir / "root.json").read_text(encoding="utf-8"), "root")
            self.assertEqual((target_dir / "User" / "settings.json").read_text(encoding="utf-8"), "settings")


if __name__ == "__main__":
    unittest.main()
