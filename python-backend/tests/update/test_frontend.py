"""助手的本地版本、Qt/Rust 附件选择及下载适配。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import MagicMock, Mock, patch

from updater import PreparedUpdate, UpdateError

from src import update
from src.update import ARCHIVES, UpdateService, read_version
from tests.support.update_package import make_package, program_snapshot, release


class FrontendUpdateTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(
            self.enterContext(tempfile.TemporaryDirectory())
        ).resolve()
        self.enterContext(patch.object(sys, "frozen", True, create=True))

    def test_version_defaults_to_qt_and_rejects_invalid_metadata(self):
        root = make_package(self.directory / "qt")
        path = root / "version.json"
        path.write_text('{"version":"1.0.0"}', encoding="utf-8")
        self.assertEqual(read_version(root)["frontend"], "qt")
        for data in (
            {},
            {"version": []},
            {"version": "invalid"},
            {"version": "1.0.0", "frontend": []},
            {"version": "1.0.0", "frontend": "other"},
        ):
            with self.subTest(data=data), self.assertRaises(UpdateError):
                path.write_text(json.dumps(data), encoding="utf-8")
                read_version(root)

    def test_info_is_local_and_only_formal_matching_installs_support_updates(self):
        root = make_package(self.directory / "installed")
        with patch("requests.get") as network:
            self.assertFalse(UpdateService(root).get_update_info().unavailable_reason)
            self.assertFalse((root / ".update").exists())
            self.assertIn(
                "rust",
                UpdateService(root, frontend="rust")
                .get_update_info()
                .unavailable_reason,
            )
            make_package(root, "1.0.0+dev.abc")
            self.assertIn(
                "开发构建", UpdateService(root).get_update_info().unavailable_reason
            )
            make_package(root)
            (root / update.UPDATER_EXE).unlink()
            self.assertIn(
                "独立更新器", UpdateService(root).get_update_info().unavailable_reason
            )
            network.assert_not_called()

    def test_check_selects_each_frontends_asset_using_library(self):
        for frontend, asset in ARCHIVES.items():
            with self.subTest(frontend=frontend):
                root = make_package(self.directory / frontend, frontend=frontend)
                result = release(frontend=frontend)
                response = MagicMock()
                response.__enter__.return_value = response
                response.status_code = 200
                response.json.return_value = {
                    "tag_name": result.tag,
                    "body": result.notes,
                    "draft": False,
                    "prerelease": False,
                    "assets": [
                        {
                            "id": 1,
                            "name": asset,
                            "browser_download_url": result.archive_url,
                            "size": 100,
                        }
                    ],
                }
                with patch("requests.get", return_value=response):
                    self.assertEqual(
                        UpdateService(root, frontend=frontend).check_update(), result
                    )

    def test_download_delegates_progress_and_cancel_and_checks_identity(self):
        root = make_package(self.directory / "installed", frontend="rust")
        work = root / ".update/github-test"
        make_package(work / "package", "2.0.0", frontend="rust")
        prepared = PreparedUpdate(work, "2.0.0")
        progress, cancelled = Mock(), Event()
        updater = Mock()
        updater.download.return_value = prepared
        service = UpdateService(root, frontend="rust")
        target = release(frontend="rust")
        with patch.object(service, "_client", return_value=updater):
            self.assertEqual(
                service.prepare_update(target, progress=progress, cancelled=cancelled),
                prepared,
            )
            updater.download.assert_called_once_with(
                target, progress=progress, cancelled=cancelled
            )
            for version, frontend in (("2.0.0", "qt"), ("3.0.0", "rust")):
                with self.subTest(version=version, frontend=frontend):
                    make_package(work / "package", version, frontend=frontend)
                    with self.assertRaisesRegex(UpdateError, "版本或前端"):
                        service.prepare_update(target)
            self.assertEqual(updater.discard.call_count, 2)

    def test_worker_rejects_cross_frontend_without_touching_installation(self):
        root = make_package(self.directory / "installed", frontend="rust")
        work = root / ".update/github-test"
        make_package(work / "package", "2.0.0")
        before = program_snapshot(root)
        with (
            patch.object(update, "application_processes", return_value=[]),
            patch("updater.GitHubUpdater.install") as install,
            self.assertRaisesRegex(UpdateError, "版本或前端"),
        ):
            update.run_update(root, PreparedUpdate(work, "2.0.0"), frontend="rust")
        install.assert_not_called()
        self.assertEqual(program_snapshot(root), before)

    def test_invalid_download_metadata_discards_cache_for_explicit_retry(self):
        root = make_package(self.directory / "installed")
        work = root / ".update/github-test"
        package = make_package(work / "package", "2.0.0")
        updater = Mock()
        updater.download.return_value = PreparedUpdate(work, "2.0.0")
        service = UpdateService(root)
        target = release()
        for content in (None, "incomplete", '{"version": []}'):
            with self.subTest(content=content):
                updater.discard.reset_mock()
                path = package / "version.json"
                if content is None:
                    path.unlink()
                else:
                    path.write_text(content, encoding="utf-8")
                with (
                    patch.object(service, "_client", return_value=updater),
                    self.assertRaises(ValueError),
                ):
                    service.prepare_update(target)
                updater.discard.assert_called_once_with(target)
