"""手动更新的网络输入、下载校验与取消路径。"""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import Mock, patch

import requests

from src.service import update_service as service
from src.service.app_service import AppService
from src.service.update_package import UPDATER_EXE, UpdateError, load_manifest
from tests.support.update_package import archive_package, make_package, program_snapshot


class Response:
    def __init__(self, data=None, content=b"", error=None):
        self.data, self.content, self.error = data, content, error

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def raise_for_status(self):
        if self.error is not None:
            raise self.error

    def json(self):
        return self.data

    def iter_content(self, _size):
        yield self.content


class TestUpdateService(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.root = make_package(self.directory / "installed")
        self.next = make_package(self.directory / "next", "1.10.0")
        self.archive = archive_package(
            self.next, self.directory / service.ZIP_NAME
        ).read_bytes()
        self.client = service.UpdateService(self.root)
        self.enterContext(patch.object(sys, "frozen", True, create=True))
        prefix = f"https://github.com/{service.REPOSITORY}/releases/download/v1.10.0/"
        self.release = service.ReleaseUpdate(
            "1.10.0",
            "notes",
            prefix + service.ZIP_NAME,
            prefix + service.ZIP_NAME + ".sha256",
            len(self.archive),
        )
        self.data = {
            "tag_name": "v1.10.0",
            "draft": False,
            "prerelease": False,
            "body": "notes",
            "assets": [
                {
                    "name": service.ZIP_NAME,
                    "browser_download_url": self.release.archive_url,
                    "size": len(self.archive),
                },
                {
                    "name": service.ZIP_NAME + ".sha256",
                    "browser_download_url": self.release.checksum_url,
                    "size": 88,
                },
            ],
        }

    def test_construction_and_facade_do_not_query_network(self):
        with patch.object(service.requests, "get") as request:
            service.UpdateService(self.root)
            AppService()
        request.assert_not_called()

    def test_local_info_reads_version_without_network_or_work_directory(self):
        with patch.object(service.requests, "get") as request:
            info = self.client.get_update_info()
        self.assertEqual(info.version, "1.0.0")
        self.assertEqual(info.unavailable_reason, "")
        self.assertIsNone(info.previous_result)
        self.assertFalse((self.root / ".update").exists())
        request.assert_not_called()

    def test_local_info_explains_source_development_and_legacy_packages(self):
        with patch.object(sys, "frozen", False):
            self.assertIn("源码", self.client.get_update_info().unavailable_reason)
        make_package(self.root, "1.0.0+dev.1234567")
        self.assertIn("开发", self.client.get_update_info().unavailable_reason)
        (self.root / "update-manifest.json").unlink()
        self.assertIn("手动安装", self.client.get_update_info().unavailable_reason)

    def test_local_info_reads_previous_result_and_rejects_invalid_data(self):
        directory = self.root / ".update"
        directory.mkdir()
        path = directory / "result.json"
        result = {"status": "failed", "error": "file locked"}
        path.write_text(json.dumps(result), encoding="utf-8")
        self.assertEqual(self.client.get_update_info().previous_result, result)
        for invalid in ({"status": []}, {"status": "failed", "error": []}, {}):
            with self.subTest(invalid=invalid):
                path.write_text(json.dumps(invalid), encoding="utf-8")
                with self.assertRaises(UpdateError):
                    self.client.get_update_info()

    def test_explicit_check_returns_newer_stable_release(self):
        with patch.object(
            service.requests, "get", return_value=Response(self.data)
        ) as request:
            self.assertEqual(self.client.check_update(), self.release)
        request.assert_called_once()
        self.assertIn("timeout", request.call_args.kwargs)

    def test_no_new_version_returns_none(self):
        self.data["tag_name"] = "v1.0.0"
        with patch.object(service.requests, "get", return_value=Response(self.data)):
            self.assertIsNone(self.client.check_update())

    def test_incomplete_or_untrusted_release_is_rejected(self):
        for change in ("missing_checksum", "external_url", "draft", "prerelease"):
            with self.subTest(change=change):
                data = json.loads(json.dumps(self.data))
                if change == "missing_checksum":
                    data["assets"].pop()
                elif change == "external_url":
                    data["assets"][0]["browser_download_url"] = (
                        "https://example.com/app.zip"
                    )
                else:
                    data[change] = True
                with (
                    patch.object(service.requests, "get", return_value=Response(data)),
                    self.assertRaises(UpdateError),
                ):
                    self.client.check_update()

    def test_source_and_development_builds_do_not_query_releases(self):
        with (
            patch.object(sys, "frozen", False),
            patch.object(service.requests, "get") as request,
            self.assertRaisesRegex(UpdateError, "源码"),
        ):
            self.client.check_update()
        request.assert_not_called()
        make_package(self.root, "1.0.0+dev.1234567")
        with (
            patch.object(service.requests, "get") as request,
            self.assertRaisesRegex(UpdateError, "开发"),
        ):
            self.client.check_update()
        request.assert_not_called()

    def responses(self, archive=None, checksum=None):
        content = self.archive if archive is None else archive
        digest = (
            hashlib.sha256(self.archive).hexdigest() if checksum is None else checksum
        )
        return [
            Response(content=f"{digest}  {service.ZIP_NAME}\n".encode()),
            Response(content=content),
        ]

    def test_download_stages_verified_package_without_changing_installation(self):
        before = program_snapshot(self.root)
        progress = Mock()
        with patch.object(service.requests, "get", side_effect=self.responses()):
            prepared = self.client.prepare_update(self.release, progress=progress)
        self.assertEqual(
            load_manifest(prepared.directory / "package", verify=True)["version"],
            self.release.version,
        )
        self.assertEqual(program_snapshot(self.root), before)
        progress.assert_called_once_with(len(self.archive), len(self.archive))

    def test_bad_checksum_or_interrupted_download_preserves_installation(self):
        for kind in ("checksum", "truncated", "network"):
            with self.subTest(kind=kind):
                responses = (
                    self.responses(checksum="0" * 64)
                    if kind == "checksum"
                    else self.responses(archive=self.archive[:-5])
                )
                if kind == "network":
                    responses[1] = Response(error=requests.ConnectionError("offline"))
                before = program_snapshot(self.root)
                with (
                    patch.object(service.requests, "get", side_effect=responses),
                    self.assertLogs(service.__name__, level="ERROR"),
                    self.assertRaises((UpdateError, requests.ConnectionError)),
                ):
                    self.client.prepare_update(self.release)
                self.assertEqual(program_snapshot(self.root), before)
                self.assertFalse(list((self.root / ".update").glob("download-*")))

    def test_cancellation_removes_partial_download(self):
        cancelled = Event()
        cancelled.set()
        with (
            patch.object(service.requests, "get", side_effect=self.responses()),
            self.assertLogs(service.__name__, level="ERROR"),
            self.assertRaises(service.UpdateCancelled),
        ):
            self.client.prepare_update(self.release, cancelled=cancelled)
        self.assertFalse(list((self.root / ".update").glob("download-*")))

    def test_busy_installation_does_not_spawn_updater(self):
        with patch.object(service.requests, "get", side_effect=self.responses()):
            prepared = self.client.prepare_update(self.release)
        with (
            patch.object(service, "helper_processes", return_value=[12345]),
            patch.object(service.subprocess, "Popen") as spawn,
            self.assertRaises(UpdateError),
        ):
            self.client.start_update(prepared)
        spawn.assert_not_called()

    def test_installer_handoff_uses_copied_worker_and_parent_identity(self):
        with patch.object(service.requests, "get", side_effect=self.responses()):
            prepared = self.client.prepare_update(self.release)

        def start(command, **kwargs):
            self.assertNotEqual(Path(command[0]), self.root / UPDATER_EXE)
            self.assertEqual(
                Path(command[0]).read_bytes(), (self.root / UPDATER_EXE).read_bytes()
            )
            self.assertIn("--parent-created", command)
            self.assertIn("--restart", command)
            self.assertEqual(kwargs["env"]["PYINSTALLER_RESET_ENVIRONMENT"], "1")
            Path(command[command.index("--ready") + 1]).write_text('{"status":"ready"}')
            return Mock()

        with (
            patch.object(service, "helper_processes", return_value=[]),
            patch.object(service.subprocess, "Popen", side_effect=start),
        ):
            result = self.client.start_update(prepared)
        self.assertEqual(result.name, "result.json")

    def test_facade_delegates_update_operations(self):
        app = AppService()
        app._updates = Mock()
        progress, cancelled = Mock(), Event()
        app.check_update()
        app.get_update_info()
        app.prepare_update(self.release, progress=progress, cancelled=cancelled)
        prepared = service.PreparedUpdate(self.directory, "1.10.0")
        app.start_update(prepared)
        app._updates.check_update.assert_called_once_with()
        app._updates.get_update_info.assert_called_once_with()
        app._updates.prepare_update.assert_called_once_with(
            self.release, progress=progress, cancelled=cancelled
        )
        app._updates.start_update.assert_called_once_with(prepared)
