"""远端 ZIP 的按需读取与增量准备路径；用本地 HTTP 服务真实走范围请求。"""

import hashlib
import http.server
import json
import logging
import os
import re
import struct
import tempfile
import threading
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path
from threading import Event
from unittest.mock import Mock, patch

import requests
from urllib3.response import HTTPResponse

from src.update import remote, service
from src.update.package import MANIFEST, load_manifest, unpack_package, write_manifest
from tests.support.update_package import archive_package, make_package

SHARED_BYTES = 500_000
logger = logging.getLogger(__name__)


def build_pair(directory: Path):
    """构造两个程序包：只有 `_internal/small.bin` 与 version.json 不同。"""
    shared = {
        "_internal/shared.bin": os.urandom(SHARED_BYTES),
        "_internal/small.bin": b"old",
    }
    installed = make_package(directory / "installed", "1.0.0", extra=dict(shared))
    extra = dict(shared)
    extra["version.json"] = json.dumps({"version": "1.10.0"}).encode()
    target = make_package(directory / "next", "1.0.0", extra=extra)
    (target / "_internal/small.bin").write_bytes(b"new")
    names = [
        path.relative_to(target).as_posix()
        for path in sorted(target.rglob("*"))
        if path.is_file() and path.name != MANIFEST
    ]
    write_manifest(target, names, "1.10.0")
    return installed, target


class RangeHandler(http.server.BaseHTTPRequestHandler):
    """按单区间返回归档内容；关闭 supports_range 时退化为整包响应。"""

    def do_HEAD(self):
        self.server.requests.append((self.path, None))
        if not self.server.supports_head:
            self.send_response(405)
        elif self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/archive.zip")
        else:
            self.send_response(200)
            self.send_header("Content-Length", str(len(self.server.payload)))
        self.end_headers()

    def do_GET(self):
        data = self.server.payload
        start, end = 0, len(data) - 1
        header = self.headers.get("Range")
        self.server.requests.append((self.path, header))
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/archive.zip")
            self.end_headers()
            return
        if header != "bytes=0-0" and self.server.fail_ranges:
            self.send_error(503)
            return
        partial = header is not None and self.server.supports_range
        if partial:
            match = re.fullmatch(r"bytes=(\d+)-(\d+)", header)
            if match is None:
                self.send_error(400)
                return
            start, end = int(match[1]), min(int(match[2]), len(data) - 1)
        body = data[start : end + 1]
        if header != "bytes=0-0" and self.server.invalid_length:
            body = body + b"x" if self.server.invalid_length == "long" else body[:-1]
        length = len(body)
        self.send_response(206 if partial else 200)
        if self.server.invalid_length != "unframed-short":
            declared = (
                end - start + 1 if self.server.invalid_length == "truncated" else length
            )
            self.send_header("Content-Length", str(declared))
        if partial:
            shift = int(self.server.wrong_range and header != "bytes=0-0")
            self.send_header(
                "Content-Range", f"bytes {start + shift}-{end + shift}/{len(data)}"
            )
        self.end_headers()
        self.server.served += length
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError) as exc:
            logger.debug("测试客户端结束范围请求: %s", type(exc).__name__)

    def log_message(self, *_args):
        """测试内静音访问日志。"""


class FullResponse:
    """整包下载路径的最小响应替身。"""

    def __init__(self, content=b""):
        self.content = content

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def raise_for_status(self):
        """测试替身不产生 HTTP 错误。"""

    def iter_content(self, _size):
        yield self.content


class TestRemoteArchive(unittest.TestCase):
    def setUp(self):
        self.enterContext(
            patch.dict(
                os.environ,
                {"NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"},
            )
        )
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.root, target = build_pair(self.directory)
        self.target = target
        archive = archive_package(target, self.directory / service.ZIP_NAME)
        self.payload = archive.read_bytes()
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), RangeHandler)
        self.server.payload = self.payload
        self.server.supports_head = True
        self.server.supports_range = True
        self.server.fail_ranges = False
        self.server.wrong_range = False
        self.server.invalid_length = ""
        self.server.served = 0
        self.server.requests = []
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(self.server.shutdown)
        self.url = (
            f"http://127.0.0.1:{self.server.server_address[1]}/{service.ZIP_NAME}"
        )
        self.enterContext(
            patch.object(
                service,
                "open_archive",
                side_effect=lambda _url, **kwargs: remote.open_archive(
                    self.url, **kwargs
                ),
            )
        )
        self.enterContext(patch.object(service.sys, "frozen", True, create=True))
        prefix = f"https://github.com/{service.REPOSITORY}/releases/download/v1.10.0/"
        self.release = service.ReleaseUpdate(
            "1.10.0",
            "notes",
            prefix + service.ZIP_NAME,
            prefix + service.ZIP_NAME + ".sha256",
            len(self.payload),
        )
        self.client = service.UpdateService(self.root)

    def test_incremental_preparation_fetches_only_changed_entries(self):
        progress = Mock()
        prepared = self.client.prepare_update(self.release, progress=progress)

        package = prepared.directory / "package"
        manifest = load_manifest(package, verify=True)
        self.assertEqual(manifest["version"], "1.10.0")
        self.assertEqual((package / "_internal/small.bin").read_bytes(), b"new")
        self.assertEqual(
            (package / "_internal/shared.bin").read_bytes(),
            (self.root / "_internal/shared.bin").read_bytes(),
        )
        self.assertIn("_internal/shared.bin", manifest["files"])
        self.assertLess(self.server.served, len(self.payload))
        self.assertLess(progress.call_args.args[1], len(self.payload))

    def test_remotezip_reads_the_requested_member(self):
        with remote.open_archive(self.url) as archive:
            self.assertIsInstance(archive, zipfile.ZipFile)
            self.assertEqual(
                archive.read("OneDragon-Helper/_internal/small.bin"), b"new"
            )

    def test_remotezip_follows_redirects_with_positive_ranges(self):
        url = f"http://127.0.0.1:{self.server.server_address[1]}/redirect"
        with remote.open_archive(url) as archive:
            self.assertEqual(
                archive.read("OneDragon-Helper/_internal/small.bin"), b"new"
            )
        self.assertEqual(self.server.requests[0], ("/redirect", None))
        self.assertIn(("/archive.zip", None), self.server.requests)
        ranges = [
            header for _path, header in self.server.requests if header is not None
        ]
        self.assertTrue(ranges)
        for header in ranges:
            self.assertRegex(header, r"^bytes=\d+-\d+$")

    def test_cached_members_finish_progress_without_more_requests(self):
        (self.target / "_internal/shared.bin").write_bytes(b"cached member")
        write_manifest(self.target, list(load_manifest(self.target)["files"]), "1.10.0")
        self.server.payload = archive_package(
            self.target, self.directory / "cached.zip"
        ).read_bytes()
        self.assertLess(len(self.server.payload), 65536)
        with remote.open_archive(self.url) as archive:
            requests_before = len(self.server.requests)
            progress = Mock()
            destination = self.directory / "cached"
            unpack_package(
                archive, destination, "1.10.0", reuse_root=self.root, progress=progress
            )
        self.assertEqual(
            (destination / "_internal/shared.bin").read_bytes(), b"cached member"
        )
        self.assertEqual(len(self.server.requests), requests_before)
        received, total = progress.call_args.args
        self.assertGreater(total, 0)
        self.assertEqual(received, total)

    def test_cancellation_during_directory_download_removes_workspace(self):
        cancelled = Event()
        readinto = HTTPResponse.readinto

        def cancel_on_chunk(response, buffer):
            count = readinto(response, buffer)
            cancelled.set()
            return count

        with (
            patch.object(HTTPResponse, "readinto", cancel_on_chunk),
            patch.object(requests, "get") as full_download,
            self.assertLogs(service.__name__, level="ERROR"),
            self.assertRaises(service.UpdateCancelled),
        ):
            self.client.prepare_update(self.release, cancelled=cancelled)
        full_download.assert_not_called()
        self.assertFalse(list((self.root / ".update").glob("download-*")))

    def test_invalid_range_length_does_not_trigger_full_download(self):
        for kind in ("short", "long", "truncated", "unframed-short"):
            with self.subTest(kind=kind):
                self.server.invalid_length = kind
                with (
                    patch.object(requests, "get") as full_download,
                    self.assertLogs(service.__name__, level="ERROR"),
                    self.assertRaisesRegex(
                        service.UpdateError, "范围响应|范围读取失败"
                    ),
                ):
                    self.client.prepare_update(self.release)
                full_download.assert_not_called()
                self.assertFalse(list((self.root / ".update").glob("download-*")))

    def test_long_names_and_extra_fields_remain_incremental(self):
        for name, extra, zip64 in (
            (
                "_internal/PySide6/plugins/platforminputcontexts/qtvirtualkeyboardplugin.dll",
                b"",
                False,
            ),
            ("assets/" + "资源" * 20 + ".bin", b"", False),
            (
                "_internal/extra.bin",
                struct.pack("<HH", 0xCAFE, 200) + b"x" * 200,
                False,
            ),
            ("_internal/local-zip64.bin", b"", True),
        ):
            with self.subTest(name=name):
                path = self.directory / "long-path.zip"
                with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
                    info = zipfile.ZipInfo("OneDragon-Helper/" + name)
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.extra = extra
                    with archive.open(info, "w", force_zip64=zip64) as output:
                        output.write(b"changed member")
                    archive.writestr(
                        "OneDragon-Helper/" + "_internal/padding.bin",
                        os.urandom(SHARED_BYTES),
                    )
                self.server.payload = path.read_bytes()
                self.server.served = 0
                with remote.open_archive(self.url) as archive:
                    self.assertEqual(
                        archive.read("OneDragon-Helper/" + name), b"changed member"
                    )
                self.assertLess(self.server.served, len(self.server.payload))

    def test_local_missing_or_modified_file_is_downloaded_again(self):
        name = "_internal/python.dll"
        path = self.root / name
        expected = path.read_bytes()
        for kind in ("missing", "modified"):
            with self.subTest(kind=kind):
                if kind == "missing":
                    path.unlink()
                else:
                    path.write_bytes(b"locally changed")
                self.server.served = 0
                with patch.object(requests, "get") as full_download:
                    prepared = self.client.prepare_update(self.release)
                full_download.assert_not_called()
                self.assertEqual(
                    (prepared.directory / "package" / name).read_bytes(), expected
                )
                load_manifest(prepared.directory / "package", verify=True)
                self.assertLess(self.server.served, len(self.payload))
                if kind == "missing":
                    self.assertFalse(path.exists())
                else:
                    self.assertEqual(path.read_bytes(), b"locally changed")
                path.write_bytes(expected)

    def test_cancel_during_last_range_removes_workspace(self):
        cancelled = Event()

        def cancel(received, total):
            if received == total:
                cancelled.set()

        with (
            self.assertLogs(service.__name__, level="ERROR"),
            self.assertRaises(service.UpdateCancelled),
        ):
            self.client.prepare_update(
                self.release,
                progress=cancel,
                cancelled=cancelled,
            )
        self.assertFalse(list((self.root / ".update").glob("download-*")))

    def test_large_range_reports_progress_before_completion_and_can_cancel(self):
        (self.target / "_internal/shared.bin").write_bytes(os.urandom(SHARED_BYTES))
        names = list(load_manifest(self.target)["files"])
        write_manifest(self.target, names, "1.10.0")
        self.server.payload = archive_package(
            self.target, self.directory / "large.zip"
        ).read_bytes()
        release = replace(self.release, size=len(self.server.payload))
        cancelled = Event()
        progress = []

        def cancel(received, total):
            progress.append((received, total))
            if 65536 <= received < total:
                staging = list((self.root / ".update").glob("download-*/package"))
                self.assertEqual(len(staging), 1)
                partial = staging[0] / "_internal/shared.bin"
                self.assertTrue(partial.is_file())
                self.assertGreater(partial.stat().st_size, 0)
                self.assertLess(partial.stat().st_size, SHARED_BYTES)
                cancelled.set()

        with (
            self.assertLogs(service.__name__, level="ERROR"),
            self.assertRaises(service.UpdateCancelled),
        ):
            self.client.prepare_update(release, progress=cancel, cancelled=cancelled)
        self.assertTrue(progress)
        self.assertLess(progress[0][0], progress[0][1])
        self.assertFalse(list((self.root / ".update").glob("download-*")))

    def test_cancel_while_copying_reused_files_removes_workspace(self):
        cancelled = Event()
        copy = service.shutil.copy2

        def cancel_after_copy(source, target):
            result = copy(source, target)
            cancelled.set()
            return result

        with (
            patch.object(service.shutil, "copy2", side_effect=cancel_after_copy),
            self.assertLogs(service.__name__, level="ERROR"),
            self.assertRaises(service.UpdateCancelled),
        ):
            self.client.prepare_update(self.release, cancelled=cancelled)
        self.assertFalse(list((self.root / ".update").glob("download-*")))

    def test_broken_archive_is_unavailable(self):
        for payload in (
            b"not a zip archive",
            b"PK\x05\x06" + b"\0" * 3,
            b"not a zip archive" * 10,
            b"x" * 100 + b"PK\x05\x06" + b"\0" * 3,
        ):
            with self.subTest(payload=payload):
                self.server.payload = payload
                with (
                    self.assertRaises(remote.RemoteUnavailable),
                    remote.open_archive(self.url) as broken,
                ):
                    broken.namelist()

    def test_http_error_and_wrong_range_do_not_trigger_full_download(self):
        for kind, message in (("http", "范围读取失败"), ("range", "范围响应位置")):
            with self.subTest(kind=kind):
                self.server.fail_ranges = kind == "http"
                self.server.wrong_range = kind == "range"
                with (
                    patch.object(requests, "get") as full_download,
                    self.assertLogs(service.__name__, level="ERROR"),
                    self.assertRaisesRegex(service.UpdateError, message),
                ):
                    self.client.prepare_update(self.release)
                full_download.assert_not_called()
                self.assertFalse(list((self.root / ".update").glob("download-*")))

    def test_remote_hash_mismatch_does_not_trigger_full_download(self):
        # ZIP 本身有效，但其中一项与发布清单不符。
        (self.target / "_internal/small.bin").write_bytes(b"bad")
        self.server.payload = archive_package(
            self.target, self.directory / "bad.zip"
        ).read_bytes()
        self.assertEqual(len(self.server.payload), self.release.size)
        with (
            patch.object(requests, "get") as full_download,
            self.assertLogs(service.__name__, level="ERROR"),
            self.assertRaisesRegex(service.UpdateError, "程序文件校验失败"),
        ):
            self.client.prepare_update(self.release)
        full_download.assert_not_called()
        self.assertEqual((self.root / "_internal/small.bin").read_bytes(), b"old")
        self.assertFalse(list((self.root / ".update").glob("download-*")))

    def test_missing_range_support_falls_back_to_full_download(self):
        digest = hashlib.sha256(self.payload).hexdigest()
        for missing in ("head", "range"):
            with self.subTest(missing=missing):
                self.server.supports_head = missing != "head"
                self.server.supports_range = missing != "range"
                responses = [
                    FullResponse(f"{digest}  {service.ZIP_NAME}\n".encode()),
                    FullResponse(self.payload),
                ]
                with patch.object(requests, "get", side_effect=responses) as request:
                    prepared = self.client.prepare_update(self.release)
                self.assertEqual(request.call_count, 2)
                self.assertEqual(prepared.version, "1.10.0")
                self.assertEqual(
                    load_manifest(prepared.directory / "package", verify=True)[
                        "version"
                    ],
                    "1.10.0",
                )

    def test_cancellation_removes_incremental_workspace(self):
        cancelled = Event()
        cancelled.set()
        with (
            self.assertLogs(service.__name__, level="ERROR"),
            self.assertRaises(service.UpdateCancelled),
        ):
            self.client.prepare_update(self.release, cancelled=cancelled)
        self.assertFalse(list((self.root / ".update").glob("download-*")))
