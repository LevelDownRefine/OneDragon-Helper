"""真实 Rust 发布包的 Windows 资源与无 Qt 边界；只读，不触发 UAC。"""

import sys
import unittest
from xml.etree import ElementTree

from src.update.package import APP_EXE, CLI_EXE, RUNNER_EXE, UPDATER_EXE, load_manifest
from tests.exe import package_dir

PACKAGE = package_dir()


@unittest.skipUnless(
    sys.platform == "win32" and (PACKAGE / CLI_EXE).is_file(),
    "需要 Windows 与完整 Rust 发布目录",
)
class RustPackageExeTests(unittest.TestCase):
    def test_gui_has_icon_and_admin_manifest_cli_inherits_permissions(self):
        import pefile
        from PyInstaller.utils.win32.winmanifest import read_manifest_from_executable

        self.assertEqual(load_manifest(PACKAGE, verify=True)["frontend"], "rust")
        for name, level in ((APP_EXE, "requireAdministrator"), (CLI_EXE, "asInvoker")):
            with self.subTest(executable=name):
                document = ElementTree.fromstring(
                    read_manifest_from_executable(str(PACKAGE / name))
                )
                node = document.find(
                    ".//{urn:schemas-microsoft-com:asm.v3}requestedExecutionLevel"
                )
                self.assertIsNotNone(node)
                self.assertEqual(node.attrib["level"], level)
        with pefile.PE(str(PACKAGE / APP_EXE)) as binary:
            self.assertIn(
                14, [entry.id for entry in binary.DIRECTORY_ENTRY_RESOURCE.entries]
            )
            self.assertEqual(
                binary.OPTIONAL_HEADER.CheckSum, binary.generate_checksum()
            )

    def test_workers_and_runtime_exclude_qt(self):
        from PyInstaller.archive.readers import CArchiveReader

        for name in (CLI_EXE, RUNNER_EXE, UPDATER_EXE):
            with self.subTest(executable=name):
                archive = CArchiveReader(str(PACKAGE / name))
                modules = archive.open_embedded_archive("PYZ.pyz").toc
                self.assertFalse(
                    any(
                        key.startswith(("PySide6", "shiboken6", "gui"))
                        for key in modules
                    )
                )
        self.assertFalse((PACKAGE / "src/gui/qml").exists())
        self.assertFalse(
            any(
                "pyside" in path.name.lower() or "shiboken" in path.name.lower()
                for path in (PACKAGE / "_internal").rglob("*")
            )
        )

    def test_native_crt_imports_resolve_to_shipped_runtime_exports(self):
        import pefile

        with pefile.PE(str(PACKAGE / APP_EXE)) as executable:
            imports = [
                entry
                for entry in executable.DIRECTORY_ENTRY_IMPORT
                if entry.dll.lower().startswith((b"vcruntime", b"msvcp"))
            ]
            self.assertTrue(imports)
            for entry in imports:
                runtime = PACKAGE / entry.dll.decode("ascii").lower()
                self.assertTrue(runtime.is_file(), f"缺少原生运行库：{runtime.name}")
                self.assertEqual(
                    runtime.read_bytes(),
                    (PACKAGE / "_internal" / runtime.name).read_bytes(),
                )
                with pefile.PE(str(runtime)) as library:
                    symbols = {
                        symbol.name for symbol in library.DIRECTORY_ENTRY_EXPORT.symbols
                    }
                    self.assertTrue({item.name for item in entry.imports} <= symbols)
