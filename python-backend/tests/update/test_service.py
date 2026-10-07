"""手动更新的网络输入、下载校验与取消路径。"""

import hashlib
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import Mock, patch

import requests

from src.service.app_service import AppService
from src.update import service
from src.update.package import UPDATER_EXE, UpdateCancelled, UpdateError, load_manifest
from src.update.service import (
    PreparedUpdate,
    ReleaseUpdate,
    UpdateInfo,
    UpdateService,
    UpdateSession,
)
from src.utils.utils_job import InvalidJob, JobExecutor
from tests.support.update_package import archive_package, make_package, program_snapshot


class Response:
    def __init__(
        self, data=None, content=b"", error=None, status_code=200, headers=None
    ):
        self.data, self.content, self.error = data, content, error
        self.status_code, self.headers = status_code, headers or {}

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

    def assert_workspace(self, kept: bool):
        """可重试的失败保留工作目录，确定性失败清空。"""
        found = [path.name for path in (self.root / ".update").glob("download-*")]
        self.assertEqual(found, ["download-v1.10.0"] if kept else [])

    def test_linked_workspace_is_rejected_before_any_request(self):
        with (
            patch.object(
                service,
                "linked_path",
                side_effect=lambda path: path.name.startswith("download-"),
            ),
            patch.object(requests, "get") as request,
            self.assertRaisesRegex(UpdateError, "链接"),
        ):
            self.client.prepare_update(self.release)
        request.assert_not_called()
        self.assertFalse(list((self.root / ".update").glob("download-*")))

    def test_stale_workspace_is_cleared_but_newer_one_is_kept(self):
        update = self.root / ".update"
        (update / "download-v1.0.0").mkdir(parents=True)
        (update / "download-v1.20.0").mkdir()
        with patch.object(requests, "get", side_effect=self.responses()):
            self.client.prepare_update(self.release)
        self.assertEqual(
            sorted(path.name for path in update.glob("download-*")),
            ["download-v1.10.0", "download-v1.20.0"],
        )

    def test_bad_checksum_or_interrupted_download_preserves_installation(self):
        for kind, kept in (("checksum", False), ("truncated", True), ("network", True)):
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
                self.assert_workspace(kept)

    def test_cancellation_keeps_partial_download_for_resume(self):
        cancelled = Event()
        cancelled.set()
        with (
            patch.object(requests, "get", side_effect=self.responses()),
            self.assertNoLogs(service.__name__, level="ERROR"),
            self.assertRaises(service.UpdateCancelled),
        ):
            self.client.prepare_update(self.release, cancelled=cancelled)
        self.assert_workspace(kept=True)

    def test_interrupted_full_download_resumes_from_saved_bytes(self):
        partial = len(self.archive) // 2
        with (
            patch.object(
                requests,
                "get",
                side_effect=[
                    self.responses()[0],
                    Response(content=self.archive[:partial]),
                ],
            ),
            self.assertLogs(service.__name__, level="ERROR"),
            self.assertRaises(service.UpdateInterrupted),
        ):
            self.client.prepare_update(self.release)
        self.assert_workspace(kept=True)

        resumed = Response(content=self.archive[partial:])
        resumed.status_code = 206
        resumed.headers = {
            "Content-Range": (
                f"bytes {partial}-{len(self.archive) - 1}/{len(self.archive)}"
            )
        }
        with patch.object(
            requests, "get", side_effect=[self.responses()[0], resumed]
        ) as request:
            prepared = self.client.prepare_update(self.release)
        self.assertEqual(
            request.call_args.kwargs["headers"], {"Range": f"bytes={partial}-"}
        )
        # 成功后包已是完整副本，整包与校验文件都不留。
        self.assertEqual(
            sorted(path.name for path in prepared.directory.iterdir()), ["package"]
        )
        self.assertEqual(
            load_manifest(prepared.directory / "package", verify=True)["version"],
            "1.10.0",
        )

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


class UpdateSessionTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.service = Mock(spec=UpdateService)
        self.service.get_update_info.return_value = UpdateInfo("1.0.0")
        self.release = ReleaseUpdate(
            "2.0.0", "更新说明", "verified-url", "checksum", 100
        )
        self.service.check_update.return_value = self.release
        self.jobs = JobExecutor()
        self.addCleanup(self.jobs.close)
        self.session = UpdateSession(self.service, self.jobs)

    def finished(self, task):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result = self.jobs.poll(task["id"])
            if result["state"] != "running":
                return result
            time.sleep(0.01)
        self.fail("更新任务未结束")

    def test_local_info_is_read_only_and_download_requires_checked_release(self):
        self.assertEqual(self.session.view()["version"], "1.0.0")
        self.service.check_update.assert_not_called()
        with self.assertRaisesRegex(UpdateError, "先检查"):
            self.session.download()
        self.service.get_update_info.return_value = UpdateInfo("源码运行", "不支持")
        with self.assertRaisesRegex(UpdateError, "不支持"):
            self.session.check()
        self.assertFalse(self.jobs.running)

    def test_check_download_progress_and_private_prepared_directory(self):
        checked = self.finished(self.session.check())
        self.assertEqual(
            checked["result"]["release"],
            {"version": "2.0.0", "notes": "更新说明", "size": 100},
        )

        def download(release, *, progress, cancelled):
            self.assertIs(release, self.release)
            self.assertFalse(cancelled.is_set())
            progress(75, 100)
            return PreparedUpdate(self.root / "private-package", "2.0.0")

        self.service.prepare_update.side_effect = download
        downloaded = self.finished(self.session.download())
        self.assertEqual(downloaded["result"], {"version": "2.0.0"})
        self.assertEqual(downloaded["progress"], {"received": 75, "total": 100})
        self.assertEqual(self.session.view()["prepared_version"], "2.0.0")
        self.assertNotIn("private-package", str(self.session.view()))
        self.service.start_update.assert_not_called()

    def test_cancel_or_eof_cancels_download_and_retains_no_prepared_package(self):
        for eof in (False, True):
            with self.subTest(eof=eof):
                jobs = JobExecutor()
                session = UpdateSession(self.service, jobs)
                checked = session.check()
                deadline = time.monotonic() + 5
                while jobs.poll(checked["id"])["state"] == "running":
                    self.assertLess(time.monotonic(), deadline)
                    time.sleep(0.01)
                entered = Event()

                def download(_release, *, progress, cancelled, entered=entered):
                    progress(1, 10)
                    entered.set()
                    if not cancelled.wait(5):
                        raise TimeoutError("取消未送达")
                    raise UpdateCancelled("已取消")

                self.service.prepare_update.side_effect = download
                task = session.download()
                try:
                    self.assertTrue(entered.wait(3))
                    with self.assertRaises(InvalidJob):
                        session.check()
                    if not eof:
                        self.assertTrue(jobs.cancel(task["id"]))
                finally:
                    jobs.close()
                self.assertEqual(jobs.poll(task["id"])["state"], "cancelled")
                self.assertIsNone(session.view()["prepared_version"])
                self.assertFalse(jobs.cancel(task["id"]))
                with self.assertRaises(InvalidJob):
                    jobs.cancel("old")

    def test_failed_check_can_retry_and_restore_cannot_be_cancelled(self):
        self.service.check_update.side_effect = OSError("网络中断")
        with self.assertLogs("src.utils.utils_job", level="ERROR"):
            failed = self.finished(self.session.check())
        self.assertIn("网络中断", failed["error"])
        self.assertIsNone(self.session.view()["release"])
        self.service.check_update.side_effect = None
        self.service.check_update.return_value = None
        self.assertIsNone(self.finished(self.session.check())["result"]["release"])
        task = self.jobs.start("restore", lambda: {})
        with self.assertRaisesRegex(InvalidJob, "不支持"):
            self.jobs.cancel(task["id"])

    def test_install_requires_download_and_failed_handoff_needs_explicit_retry(self):
        with self.assertRaisesRegex(UpdateError, "先下载"):
            self.session.install()
        self.finished(self.session.check())
        prepared = PreparedUpdate(self.root / "private-package", "2.0.0")
        self.service.prepare_update.return_value = prepared
        self.finished(self.session.download())
        self.service.start_update.side_effect = UpdateError("仍有任务运行")
        with self.assertLogs("src.utils.utils_job", level="ERROR"):
            failed = self.finished(self.session.install())
        self.assertIn("仍有任务运行", failed["error"])
        self.assertFalse(self.session.view()["handoff_ready"])
        self.assertEqual(self.session.view()["prepared_version"], "2.0.0")
        self.service.start_update.assert_called_once_with(prepared)
        self.service.start_update.reset_mock()
        entered, release = Event(), Event()
        self.addCleanup(release.set)

        def handoff(package):
            self.assertIs(package, prepared)
            entered.set()
            if not release.wait(5):
                raise TimeoutError("test did not release handoff")
            return self.root / "private-result.json"

        self.service.start_update.side_effect = handoff
        task = self.session.install()
        self.assertTrue(entered.wait(3))
        with self.assertRaisesRegex(InvalidJob, "不支持"):
            self.jobs.cancel(task["id"])
        with self.assertRaises(InvalidJob):
            self.session.install()
        release.set()
        self.assertEqual(
            self.finished(task)["result"], {"version": "2.0.0", "ready": True}
        )
        self.assertTrue(self.session.view()["handoff_ready"])
        self.assertNotIn("private-result", str(self.session.view()))
        for method in (self.session.check, self.session.download, self.session.install):
            with self.assertRaisesRegex(UpdateError, "就绪"):
                method()
        self.service.start_update.assert_called_once_with(prepared)
