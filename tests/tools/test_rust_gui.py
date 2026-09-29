"""Rust 演示目录不带真实配置，且保留整型与布尔选项的独立原生落点。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.run_rust_gui import main, prepare_demo


class RustDemoTests(unittest.TestCase):
    def test_demo_uses_generated_config_and_static_declarations_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch("tools.run_rust_gui.shutil.copytree") as source_copy:
                prepare_demo(root)
            source_copy.assert_called_once()
            ignored = source_copy.call_args.kwargs["ignore"](
                "src", ["headless.py", "service", "rust-gui", "__pycache__"]
            )
            self.assertEqual(ignored, {"rust-gui", "__pycache__"})
            self.assertFalse((root / "config/config.yml").exists())
            self.assertFalse((root / "config/schedule.yml").exists())
            self.assertTrue((root / "config/daily_task_list.yml").is_file())
            self.assertEqual(
                (root / "config/script_resources.yml").read_bytes(),
                (
                    Path(__file__).resolve().parents[2] / "config/script_resources.yml"
                ).read_bytes(),
            )
            self.assertIn(
                "scripts/ok-ww.exe",
                (root / "config/config.example.yml").read_text(encoding="utf-8"),
            )
            native = root / "scripts/data/apps/ok-ww/working/configs/DailyTask.json"
            data = json.loads(native.read_text(encoding="utf-8"))
            self.assertEqual(data["Which Forgery Challenge to Farm"], 20)
            self.assertEqual(data["untouched"], {"中文": [1, 2, 3]})
            self.assertIn(
                "build_target_enable: false",
                (root / "scripts/config.yaml").read_text(encoding="utf-8"),
            )

    def test_launcher_builds_and_runs_from_src_crate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            crate = root / "src/rust-gui"
            name = (
                "onedragon-rust-gui.exe"
                if sys.platform == "win32"
                else "onedragon-rust-gui"
            )
            binary = crate / "target/release" / name
            binary.parent.mkdir(parents=True)
            binary.touch()
            with (
                patch("tools.run_rust_gui.PROJECT_ROOT", root),
                patch("tools.run_rust_gui.subprocess.run") as run,
            ):
                run.return_value.returncode = 7
                self.assertEqual(main([]), 7)
            build, launch = run.call_args_list
            self.assertEqual(
                build.args[0][-2:], ["--manifest-path", str(crate / "Cargo.toml")]
            )
            self.assertEqual(
                launch.args[0],
                [str(binary), "--project-root", str(root), "--python", sys.executable],
            )
            self.assertEqual(launch.kwargs["cwd"], root)
