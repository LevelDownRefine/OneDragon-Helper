"""图标导出使用根目录资源位置，并产生可解码的 PNG。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.gui.helpers import get_app
from tools.export_rust_icons import main


class ExportRustIconsTests(unittest.TestCase):
    def test_export_writes_root_assets_with_complete_decodable_icons(self):
        app = get_app()
        from PySide6.QtGui import QImage

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch(
                "tools.export_rust_icons.__file__",
                str(root / "tools/export_rust_icons.py"),
            ):
                main()
            files = list((root / "assets/icons").glob("*.png"))
            expected = Path(__file__).resolve().parents[2] / "assets/icons"
            self.assertEqual(
                {path.name for path in files},
                {path.name for path in expected.glob("*.png")},
            )
            self.assertEqual(len(files), 16)
            self.assertFalse((root / "src").exists())
            for path in files:
                with self.subTest(icon=path.name):
                    image = QImage(str(path))
                    self.assertFalse(image.isNull())
                    self.assertGreater(image.width(), 0)
                    self.assertGreater(image.height(), 0)
        self.assertIsNotNone(app)
