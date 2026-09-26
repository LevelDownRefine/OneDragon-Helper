"""远端 ZIP 的按需读取与增量准备路径；用本地 HTTP 服务真实走范围请求。"""

import hashlib
import http.server
import json
import os
import re
import tempfile
import threading
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import Mock, patch

import requests

from src.update import remote, service
from src.update.package import MANIFEST, load_manifest, write_manifest
from tests.support.update_package import archive_package, make_package

SHARED_BYTES = 500_000


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

    def do_GET(self):
        data = self.server.payload
        start, end = 0, len(data) - 1
        header = self.headers.get("Range")
        partial = header is not None and self.server.supports_range
        if partial:
            match = re.fullmatch(r"bytes=(\d+)-(\d+)", header)
            if match is None:
                self.send_error(400)
                return
            start, end = int(match[1]), min(int(match[2]), len(data) - 1)
        length = end - start + 1
        self.send_response(206 if partial else 200)
        self.send_header("Content-Length", str(length))
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
        self.end_headers()
        self.server.served += length
        self.wfile.write(data[start : end + 1])

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
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.root, target = build_pair(self.directory)
        archive = archive_package(target, self.directory / service.ZIP_NAME)
        self.payload = archive.read_bytes()
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), RangeHandler)
        self.server.payload = self.payload
        self.server.supports_range = True
        self.server.served = 0
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
                side_effect=lambda _url: remote.open_archive(self.url),
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

    def test_entries_and_fetch_read_the_requested_member(self):
        with remote.open_archive(self.url) as archive:
            entries = archive.entries()
            self.assertIn("_internal/small.bin", entries)
            blobs = archive.fetch(entries, ["_internal/small.bin"])
        self.assertEqual(blobs["_internal/small.bin"], b"new")

    def test_broken_archive_is_unavailable(self):
        self.server.payload = b"not a zip archive"
        with (
            remote.open_archive(self.url) as broken,
            self.assertRaises(remote.RemoteUnavailable),
        ):
            broken.entries()

    def test_missing_range_support_falls_back_to_full_download(self):
        self.server.supports_range = False
        digest = hashlib.sha256(self.payload).hexdigest()
        responses = [
            FullResponse(f"{digest}  {service.ZIP_NAME}\n".encode()),
            FullResponse(self.payload),
        ]
        with patch.object(requests, "get", side_effect=responses) as request:
            prepared = self.client.prepare_update(self.release)
        self.assertTrue(request.called)
        self.assertEqual(prepared.version, "1.10.0")
        self.assertEqual(
            load_manifest(prepared.directory / "package", verify=True)["version"],
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
