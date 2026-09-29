"""Qt/Rust 更新包身份隔离；全部为临时合成文件。"""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.service.app_service import AppService
from src.update import service
from src.update.installer import install_package
from src.update.package import (
    CLI_EXE,
    MANIFEST,
    RUST_RUNTIME,
    VERSION_FILE,
    UpdateError,
    load_manifest,
    manifest_frontend,
    parse_manifest,
    unpack_package,
)
from tests.support.update_package import archive_package, make_package, program_snapshot


class FrontendPackageTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(sys, "frozen", True, create=True))

    def test_rust_round_trip_requires_cli_and_matching_version_metadata(self):
        root = make_package(self.directory / "rust", frontend="rust")
        self.assertTrue((root / CLI_EXE).is_file())
        self.assertFalse((root / "src/gui/qml/main.qml").exists())
        data = load_manifest(root, verify=True)
        archive = archive_package(root, self.directory / "rust.zip")
        unpacked = unpack_package(archive, self.directory / "unpacked", "1.0.0")
        self.assertEqual(manifest_frontend(unpacked), "rust")
        del data["files"][CLI_EXE]
        with self.assertRaisesRegex(UpdateError, "必要程序"):
            parse_manifest(data)
        (root / VERSION_FILE).write_text(
            json.dumps({"version": "1.0.0"}), encoding="utf-8"
        )
        # 保持哈希正确，单独验证身份元数据，而非因文件被改动提前失败。
        from src.update.package import file_digest

        manifest = load_manifest(root)
        manifest["files"][VERSION_FILE] = file_digest(root / VERSION_FILE)
        (root / MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(UpdateError, "前端类型不一致"):
            load_manifest(root, verify=True)

    def test_legacy_defaults_to_qt_and_unknown_frontends_are_rejected(self):
        root = make_package(self.directory / "legacy")
        data = load_manifest(root, verify=True)
        self.assertNotIn("frontend", data)
        self.assertEqual(manifest_frontend(data), "qt")
        for value in (None, "other", [], 1):
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(UpdateError, "前端类型"),
            ):
                parse_manifest({**data, "frontend": value})

    def test_rust_native_runtime_is_required_and_hash_verified(self):
        root = make_package(self.directory / "runtime", frontend="rust")
        manifest = load_manifest(root, verify=True)
        self.assertTrue((root / RUST_RUNTIME).is_file())
        del manifest["files"][RUST_RUNTIME]
        with self.assertRaisesRegex(UpdateError, "必要程序"):
            parse_manifest(manifest)
        (root / RUST_RUNTIME).write_bytes(b"changed")
        with self.assertRaises(UpdateError):
            load_manifest(root, verify=True)

    def test_installer_rejects_cross_frontend_without_changing_program_or_user_files(
        self,
    ):
        for old, new in (("qt", "rust"), ("rust", "qt")):
            with self.subTest(old=old):
                root = make_package(self.directory / old, frontend=old)
                target = make_package(
                    self.directory / f"next-{new}", "2.0.0", frontend=new
                )
                user = root / "config/config.yml"
                user.write_bytes(b"user configuration")
                before = program_snapshot(root)
                with self.assertRaisesRegex(UpdateError, "前端类型不一致"):
                    install_package(root, target)
                self.assertEqual(program_snapshot(root), before)
                self.assertEqual(user.read_bytes(), b"user configuration")
                self.assertFalse((root / ".update/transaction.json").exists())

    def test_rust_to_rust_upgrade_preserves_user_files(self):
        root = make_package(self.directory / "old", frontend="rust")
        target = make_package(self.directory / "next", "2.0.0", frontend="rust")
        user = root / "config/wallpaper.json"
        user.write_bytes(b"user wallpaper")
        install_package(root, target)
        self.assertEqual(load_manifest(root, verify=True)["version"], "2.0.0")
        self.assertEqual((root / CLI_EXE).read_bytes(), b"program 2.0.0")
        self.assertEqual(user.read_bytes(), b"user wallpaper")

    def test_release_selection_and_local_info_do_not_mix_frontends(self):
        prefix = f"https://github.com/{service.REPOSITORY}/releases/download/v2.0.0/"
        assets = [
            {"name": name, "browser_download_url": prefix + name, "size": 100}
            for archive in (service.ZIP_NAME, service.RUST_ZIP_NAME)
            for name in (archive, archive + ".sha256")
        ]
        data = {
            "tag_name": "v2.0.0",
            "draft": False,
            "prerelease": False,
            "body": "notes",
            "assets": assets,
        }
        response = MagicMock()
        response.__enter__.return_value = response
        response.json.return_value = data
        for frontend, name in (
            ("qt", service.ZIP_NAME),
            ("rust", service.RUST_ZIP_NAME),
        ):
            with self.subTest(frontend=frontend):
                root = make_package(self.directory / frontend, frontend=frontend)
                client = service.UpdateService(root, frontend=frontend)
                with patch("requests.get", return_value=response):
                    result = client.check_update()
                self.assertEqual(result.archive_url, prefix + name)
        with (
            patch.object(
                service, "get_root_dir", return_value=str(self.directory / "qt")
            ),
            patch("requests.get") as network,
        ):
            app = AppService()
            self.addCleanup(app.close)
            self.assertFalse(app.get_update_info().unavailable_reason)
            self.assertFalse(app.update_view()["unavailable_reason"])
            rust_app = AppService(frontend="rust")
            self.addCleanup(rust_app.close)
            self.assertIn("rust", rust_app.get_update_info().unavailable_reason)
            self.assertIn("rust", rust_app.update_view()["unavailable_reason"])
            network.assert_not_called()

    def test_mislabelled_download_is_cleaned_and_never_handed_to_installer(self):
        root = make_package(self.directory / "installed", frontend="rust")
        client = service.UpdateService(root, frontend="rust")
        prefix = f"https://github.com/{service.REPOSITORY}/releases/download/v2.0.0/"
        release = service.ReleaseUpdate(
            "2.0.0",
            "",
            prefix + service.RUST_ZIP_NAME,
            prefix + service.RUST_ZIP_NAME + ".sha256",
            100,
        )

        def prepare(_release, work, _progress, _cancelled):
            make_package(work / "package", "2.0.0", frontend="qt")
            return True

        before = program_snapshot(root)
        with (
            patch.object(client, "_prepare_incremental", side_effect=prepare),
            self.assertLogs("src.update.service", level="ERROR"),
            self.assertRaisesRegex(UpdateError, "前端类型不一致"),
        ):
            client.prepare_update(release)
        self.assertEqual(list((root / ".update").glob("download-*")), [])
        self.assertEqual(program_snapshot(root), before)
        package = make_package(
            root / ".update/download-test/package", "2.0.0", frontend="qt"
        )
        with (
            patch.object(service.subprocess, "Popen") as process,
            self.assertRaisesRegex(UpdateError, "前端类型不一致"),
        ):
            client.start_update(service.PreparedUpdate(package.parent, "2.0.0"))
        process.assert_not_called()

    def test_rust_full_download_uses_its_own_checksum_filename(self):
        root = make_package(self.directory / "installed", frontend="rust")
        target = make_package(self.directory / "next", "2.0.0", frontend="rust")
        archive = archive_package(target, self.directory / "rust.zip").read_bytes()
        client = service.UpdateService(root, frontend="rust")
        prefix = f"https://github.com/{service.REPOSITORY}/releases/download/v2.0.0/"
        release = service.ReleaseUpdate(
            "2.0.0",
            "",
            prefix + client.zip_name,
            prefix + client.zip_name + ".sha256",
            len(archive),
        )
        checksum = hashlib.sha256(archive).hexdigest()
        before = program_snapshot(root)
        for name in (service.ZIP_NAME, service.RUST_ZIP_NAME):
            with self.subTest(checksum_filename=name):
                responses = []
                for content in (f"{checksum}  {name}\n".encode(), archive):
                    response = MagicMock()
                    response.__enter__.return_value = response
                    response.iter_content.return_value = [content]
                    responses.append(response)
                with (
                    patch.object(client, "_prepare_incremental", return_value=False),
                    patch("requests.get", side_effect=responses) as network,
                ):
                    if name == service.ZIP_NAME:
                        with (
                            self.assertLogs(service.__name__, level="ERROR"),
                            self.assertRaisesRegex(UpdateError, "SHA-256 文件格式"),
                        ):
                            client.prepare_update(release)
                        self.assertFalse(list((root / ".update").glob("download-*")))
                    else:
                        prepared = client.prepare_update(release)
                        data = load_manifest(
                            prepared.directory / "package", verify=True
                        )
                        self.assertEqual(manifest_frontend(data), "rust")
                        self.assertEqual(data["version"], "2.0.0")
                        self.assertEqual(
                            [call.args[0] for call in network.call_args_list],
                            [release.checksum_url, release.archive_url],
                        )
                self.assertEqual(program_snapshot(root), before)
