"""前端专用产物测试按清单选择，不以共用 CLI 文件判断。"""

import json
import tempfile
import unittest
from pathlib import Path

from src.update.package import CLI_EXE, MANIFEST, UpdateError
from tests.exe import is_frontend_package
from tests.support.update_package import make_package


class ExePackageTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_qt_package_with_cli_does_not_select_rust_tests(self):
        package = make_package(self.directory / "qt")
        (package / CLI_EXE).write_bytes(b"cli")
        self.assertTrue(is_frontend_package(package, "qt"))
        self.assertFalse(is_frontend_package(package, "rust"))

    def test_rust_package_selects_rust_tests(self):
        package = make_package(self.directory / "rust", frontend="rust")
        self.assertTrue(is_frontend_package(package, "rust"))
        self.assertFalse(is_frontend_package(package, "qt"))

    def test_missing_manifest_skips_but_invalid_manifest_is_not_hidden(self):
        self.assertFalse(is_frontend_package(self.directory, "rust"))
        package = make_package(self.directory / "invalid")
        path = package / MANIFEST
        data = json.loads(path.read_text(encoding="utf-8"))
        data["frontend"] = "invalid"
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(UpdateError):
            is_frontend_package(package, "rust")
