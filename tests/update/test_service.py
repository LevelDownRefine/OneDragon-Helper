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

from src.service.app_service import AppService
from src.update import service
from src.update.package import UPDATER_EXE, UpdateError, load_manifest
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
        # 本文件覆盖整包下载路径；增量路径见 tests/update/test_remote.py。
        self.enterContext(
            patch.object(
                service, "open_archive", side_effect=service.RemoteUnavailable("禁用")
            )
        )
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

    def test_local_info_has_no_network_or_disk_side_effects(self):
        with (
            patch.object(service, "get_root_dir", return_value=str(self.root)),
            patch.object(requests, "get") as request,
        ):
            info = AppService().get_update_info()
        self.assertEqual(info.version, "1.0.0")
        self.assertEqual(info.unavailable_reason, "")
        self.assertIsNone(info.previous_result)
        self.assertFalse((self.root / ".update").exists())
        request.assert_not_called()

    def test_unsupported_build_explains_reason_without_querying_releases(self):
        for kind, version, reason in (
            ("source", "1.0.0", "源码"),
            ("development", "1.0.0+dev.1234567", "开发"),
            ("legacy", "1.0.0", "手动安装"),
        ):
            with self.subTest(kind=kind):
                root = make_package(self.directory / kind, version)
                if kind == "legacy":
                    (root / "update-manifest.json").unlink()
                client = service.UpdateService(root)
                with (
                    patch.object(sys, "frozen", kind != "source"),
                    patch.object(requests, "get") as request,
                ):
                    self.assertIn(reason, client.get_update_info().unavailable_reason)
                    with self.assertRaisesRegex(UpdateError, reason):
                        client.check_update()
                request.assert_not_called()

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

    def test_check_offers_only_semantically_newer_versions(self):
        for installed, expected in (
            ("1.9.0", self.release),
            ("1.10.0-rc.1", self.release),
            ("1.10.0", None),
            ("1.11.0", None),
        ):
            with self.subTest(installed=installed):
                root = make_package(self.directory / installed, installed)
                with patch.object(
                    requests, "get", return_value=Response(self.data)
                ) as request:
                    self.assertEqual(
                        service.UpdateService(root).check_update(), expected
                    )
                request.assert_called_once()
                self.assertIn("timeout", request.call_args.kwargs)

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
                    patch.object(requests, "get", return_value=Response(data)),
                    self.assertRaises(UpdateError),
                ):
                    self.client.check_update()

    def responses(self, archive=None, checksum=None):
        content = self.archive if archive is None else archive
        digest = (
            hashlib.sha256(self.archive).hexdigest() if checksum is None else checksum
        )
        return [
            Response(content=f"{digest}  {service.ZIP_NAME}\n".encode()),
            Response(content=content),
        ]

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
                    patch.object(requests, "get", side_effect=responses),
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
            patch.object(requests, "get", side_effect=self.responses()),
            self.assertLogs(service.__name__, level="ERROR"),
            self.assertRaises(service.UpdateCancelled),
        ):
            self.client.prepare_update(self.release, cancelled=cancelled)
        self.assertFalse(list((self.root / ".update").glob("download-*")))

    def test_facade_prepares_verified_update_and_hands_off_when_idle(self):
        with patch.object(service, "get_root_dir", return_value=str(self.root)):
            app = AppService()
        before = program_snapshot(self.root)
        progress = Mock()
        with patch.object(
            requests,
            "get",
            side_effect=[Response(self.data), *self.responses()],
        ):
            release = app.check_update()
            self.assertEqual(release, self.release)
            prepared = app.prepare_update(release, progress=progress)
        self.assertEqual(
            load_manifest(prepared.directory / "package", verify=True)["version"],
            release.version,
        )
        self.assertEqual(program_snapshot(self.root), before)
        progress.assert_called_once_with(len(self.archive), len(self.archive))
        with (
            patch.object(service, "helper_processes", return_value=[12345]),
            patch.object(service.subprocess, "Popen") as spawn,
            self.assertRaises(UpdateError),
        ):
            app.start_update(prepared)
        spawn.assert_not_called()

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
            result = app.start_update(prepared)
        self.assertEqual(result.name, "result.json")
        self.assertEqual(program_snapshot(self.root), before)
