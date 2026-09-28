"""构建输出边界：不覆盖安装数据或删除其他输出目录。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.build_rust import build, output_path


class RustBuildOutputTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.dist = self.root / "deploy/dist"
        self.dist.mkdir(parents=True)

    def test_path_escape_and_wrong_package_name_are_rejected_before_build(self):
        for path in (
            self.root / "OneDragon-Helper",
            self.dist / ".." / "OneDragon-Helper",
            self.dist / "other-name",
        ):
            with (
                self.subTest(path=path),
                patch("tools.build_rust.subprocess.run") as run,
            ):
                with self.assertRaisesRegex(ValueError, "输出须"):
                    build(self.root, path)
                run.assert_not_called()
        outside = self.root / "outside"
        outside.mkdir()
        (self.dist / "linked").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "输出须"):
            output_path(self.root, self.dist / "linked/OneDragon-Helper")

    def test_existing_unmanaged_install_is_preserved_before_compilation(self):
        path = self.dist / "rust/OneDragon-Helper"
        (path / "config").mkdir(parents=True)
        config = path / "config/config.yml"
        config.write_text("user: untouched\n", encoding="utf-8")
        with patch("tools.build_rust.subprocess.run") as run:
            with self.assertRaises(ValueError):
                build(self.root, path)
            run.assert_not_called()
        self.assertEqual(config.read_text(), "user: untouched\n")

    def test_compiler_failure_does_not_create_package_or_touch_other_builds(self):
        other = self.dist / "qt.txt"
        other.write_text("preserved")
        target = self.dist / "rust/OneDragon-Helper"
        with (
            patch(
                "tools.build_rust.subprocess.run", side_effect=OSError("compiler")
            ) as run,
            self.assertRaisesRegex(OSError, "compiler"),
        ):
            build(self.root, target)
        command = run.call_args.args[0]
        self.assertEqual(
            command[command.index("--manifest-path") + 1],
            str(self.root / "src/rust-gui/Cargo.toml"),
        )
        self.assertEqual(
            command[command.index("--target-dir") + 1],
            str(self.root / "src/rust-gui/target"),
        )
        self.assertFalse(target.exists())
        self.assertEqual(other.read_text(), "preserved")
        self.assertEqual(list(self.dist.iterdir()), [other])
