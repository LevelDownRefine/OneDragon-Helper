"""Rust 演示目录不带真实配置，且保留整型与布尔选项的独立原生落点。"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.run_rust_gui import prepare_demo


class RustDemoTests(unittest.TestCase):
    def test_demo_uses_generated_config_and_static_declarations_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch("tools.run_rust_gui.shutil.copytree") as source_copy:
                prepare_demo(root)
            source_copy.assert_called_once()
            self.assertFalse((root / "config/config.yml").exists())
            self.assertFalse((root / "config/schedule.yml").exists())
            self.assertTrue((root / "config/daily_task_list.yml").is_file())
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
