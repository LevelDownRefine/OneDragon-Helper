"""远端 ZIP 的按需读取与增量准备路径；用本地 HTTP 服务真实走范围请求。"""

import hashlib
import http.server
import json
import logging
import os
import re
import shutil
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

    def send_identity(self):
        self.send_header(
            "ETag", '"' + hashlib.sha256(self.server.payload).hexdigest() + '"'
        )

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
            self.send_identity()
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
        self.send_identity()
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

    def __init__(self, content=b"", status_code=200, headers=None):
        self.content, self.status_code = content, status_code
        self.headers = headers or {}

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
        self.ranges = self.directory / "ranges"
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

    def forget_workspace(self):
        """丢掉上一轮的断点与已下载的包，让下一次从零开始。"""
        shutil.rmtree(self.root / ".update", ignore_errors=True)

    def assert_workspace(self, kept: bool):
        """可重试的失败与坏区间缓存保留工作目录，其余确定性失败清空。"""
        found = [path.name for path in (self.root / ".update").glob("download-*")]
        self.assertEqual(found, ["download-v1.10.0"] if kept else [])

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
        with remote.open_archive(self.url, cache=self.ranges) as archive:
            self.assertIsInstance(archive, zipfile.ZipFile)
            self.assertEqual(
                archive.read("OneDragon-Helper/_internal/small.bin"), b"new"
            )

    def test_remotezip_follows_redirects_with_positive_ranges(self):
        url = f"http://127.0.0.1:{self.server.server_address[1]}/redirect"
        with remote.open_archive(url, cache=self.ranges) as archive:
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
        with remote.open_archive(self.url, cache=self.ranges) as archive:
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

    def test_cancellation_during_directory_download_keeps_workspace(self):
        cancelled = Event()
        readinto = HTTPResponse.readinto

        def cancel_on_chunk(response, buffer):
            count = readinto(response, buffer)
            cancelled.set()
            return count

        with (
            patch.object(HTTPResponse, "readinto", cancel_on_chunk),
            patch.object(requests, "get") as full_download,
            self.assertNoLogs(service.__name__, level="ERROR"),
            self.assertRaises(service.UpdateCancelled),
        ):
            self.client.prepare_update(self.release, cancelled=cancelled)
        full_download.assert_not_called()
        self.assert_workspace(kept=True)

    def test_invalid_range_length_does_not_trigger_full_download(self):
        # 声明长度对不上属于坏响应，直接丢弃；只是流提前结束则可以续传。
        for kind, resumable in (
            ("short", False),
            ("long", False),
            ("truncated", True),
            ("unframed-short", True),
        ):
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
                self.assert_workspace(kept=resumable)

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
                with remote.open_archive(self.url, cache=self.ranges) as archive:
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
                self.forget_workspace()
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

    def test_cancel_during_last_range_keeps_workspace(self):
        cancelled = Event()

        def cancel(received, total):
            if received == total:
                cancelled.set()

        with (
            self.assertNoLogs(service.__name__, level="ERROR"),
            self.assertRaises(service.UpdateCancelled),
        ):
            self.client.prepare_update(
                self.release,
                progress=cancel,
                cancelled=cancelled,
            )
        self.assert_workspace(kept=True)

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
            self.assertNoLogs(service.__name__, level="ERROR"),
            self.assertRaises(service.UpdateCancelled),
        ):
            self.client.prepare_update(release, progress=cancel, cancelled=cancelled)
        self.assertTrue(progress)
        self.assertLess(progress[0][0], progress[0][1])
        self.assert_workspace(kept=True)

    def test_interrupted_incremental_download_resumes_inside_the_member(self):
        (self.target / "_internal/shared.bin").write_bytes(os.urandom(SHARED_BYTES))
        write_manifest(self.target, list(load_manifest(self.target)["files"]), "1.10.0")
        archive = archive_package(self.target, self.directory / "large.zip")
        self.server.payload = archive.read_bytes()
        release = replace(self.release, size=len(self.server.payload))
        cancelled = Event()
        progress = []

        def cancel(received, total):
            progress.append((received, total))
            if received > 2 * 65536:
                cancelled.set()

        with (
            self.assertNoLogs(service.__name__, level="ERROR"),
            self.assertRaises(service.UpdateCancelled),
        ):
            self.client.prepare_update(release, progress=cancel, cancelled=cancelled)
        self.assert_workspace(kept=True)
        total = progress[0][1]
        with zipfile.ZipFile(archive) as source:
            member = source.getinfo("OneDragon-Helper/_internal/shared.bin")
        ranges = self.root / ".update/download-v1.10.0/ranges"
        cached = list(ranges.glob(f"{member.header_offset}-*.bin"))
        self.assertEqual(len(cached), 1)
        saved_size = cached[0].stat().st_size
        self.assertGreater(saved_size, 0)
        self.assertLess(saved_size, member.compress_size)

        self.server.requests = []
        self.server.served = 0
        progress.clear()
        prepared = self.client.prepare_update(
            release, progress=lambda received, size: progress.append((received, size))
        )
        load_manifest(prepared.directory / "package", verify=True)
        self.assertTrue(all(size == total for _received, size in progress))
        self.assertEqual(progress[-1], (total, total))
        starts = [
            int(header[6:].split("-")[0])
            for _path, header in self.server.requests
            if header is not None
        ]
        self.assertTrue(starts)
        self.assertNotIn(member.header_offset, starts)
        self.assertIn(member.header_offset + saved_size, starts)
        self.assertLess(self.server.served, SHARED_BYTES)

    def test_cancel_while_copying_reused_files_keeps_workspace(self):
        cancelled = Event()
        copy = service.shutil.copy2

        def cancel_after_copy(source, target):
            result = copy(source, target)
            cancelled.set()
            return result

        with (
            patch.object(service.shutil, "copy2", side_effect=cancel_after_copy),
            self.assertNoLogs(service.__name__, level="ERROR"),
            self.assertRaises(service.UpdateCancelled),
        ):
            self.client.prepare_update(self.release, cancelled=cancelled)
        self.assert_workspace(kept=True)

    def test_resume_keeps_copied_files_out_of_download_progress(self):
        cancelled = Event()
        progress = []
        copy = service.shutil.copy2
        copied = self.root / ".update/download-v1.10.0/package/_internal/shared.bin"

        def cancel_after_shared_copy(source, target):
            result = copy(source, target)
            if target == copied:
                cancelled.set()
            return result

        with (
            patch.object(service.shutil, "copy2", side_effect=cancel_after_shared_copy),
            self.assertNoLogs(service.__name__, level="ERROR"),
            self.assertRaises(service.UpdateCancelled),
        ):
            self.client.prepare_update(
                self.release,
                progress=lambda received, total: progress.append((received, total)),
                cancelled=cancelled,
            )
        self.assertEqual(
            copied.read_bytes(), (self.root / "_internal/shared.bin").read_bytes()
        )
        total = (self.target / "version.json").stat().st_size + len(b"new")
        self.assertTrue(progress)
        self.assertTrue(all(size == total for _received, size in progress))
        received_before = progress[-1][0]

        # 连续暂停两次，已复制的文件不能再计入下载，已完成的下载不能丢失。
        for _ in range(2):
            progress.clear()
            cancelled.clear()

            def pause(received, size):
                progress.append((received, size))
                cancelled.set()

            self.server.requests.clear()
            with self.assertRaises(service.UpdateCancelled):
                self.client.prepare_update(
                    self.release, progress=pause, cancelled=cancelled
                )
            self.assertEqual(progress, [(received_before, total)])
            self.assertTrue(
                all(header is None for _path, header in self.server.requests)
            )

        progress.clear()
        self.server.served = 0
        with patch.object(requests, "get") as full_download:
            prepared = self.client.prepare_update(
                self.release,
                progress=lambda received, size: progress.append((received, size)),
            )
        full_download.assert_not_called()
        self.assertEqual(progress[0], (received_before, total))
        self.assertEqual(progress[-1], (total, total))
        self.assertTrue(all(size == total for _received, size in progress))
        self.assertLess(self.server.served, SHARED_BYTES)
        load_manifest(prepared.directory / "package", verify=True)

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
                    remote.open_archive(self.url, cache=self.ranges) as broken,
                ):
                    broken.namelist()

    def test_http_error_and_wrong_range_do_not_trigger_full_download(self):
        for kind, message, resumable in (
            ("http", "范围读取失败", True),
            ("range", "范围响应位置", False),
        ):
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
                self.assert_workspace(kept=resumable)

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
        self.assert_workspace(kept=False)

    def test_corrupt_member_is_not_treated_as_resumable(self):
        # 改一个成员（确保会被下载）后翻转它压缩数据中间一个字节。
        (self.target / "_internal/shared.bin").write_bytes(os.urandom(SHARED_BYTES))
        write_manifest(self.target, list(load_manifest(self.target)["files"]), "1.10.0")
        archive = archive_package(self.target, self.directory / "corrupt.zip")
        raw = bytearray(archive.read_bytes())
        with zipfile.ZipFile(archive) as source:
            member = source.getinfo("OneDragon-Helper/_internal/shared.bin")
        data_start = (
            member.header_offset
            + 30
            + len(member.filename.encode())
            + len(member.extra)
        )
        raw[data_start + member.compress_size // 2] ^= 0xFF
        self.server.payload = bytes(raw)
        release = replace(self.release, size=len(raw))

        with (
            self.assertLogs(service.__name__, level="ERROR"),
            self.assertRaises(service.RangeCacheCorrupt) as raised,
        ):
            self.client.prepare_update(release)
        # 坏字节必须当确定性失败：重放同一份断点缓存只会一直失败。
        self.assertIn("数据损坏", str(raised.exception))
        work = self.root / ".update" / "download-v1.10.0"
        # 只丢区间缓存；已解包并校验过的条目留着，重跑从缺口继续。
        self.assertFalse(list((work / "ranges").glob("*.bin")))
        self.assertTrue((work / "package" / MANIFEST).is_file())
        self.assert_workspace(kept=True)

        # 远端恢复正常后重跑：只重取区间缓存，整包与留下的条目都不再重下。
        self.server.payload = self.payload
        self.server.served = 0
        prepared = self.client.prepare_update(self.release)
        self.assertEqual(
            load_manifest(prepared.directory / "package", verify=True)["version"],
            "1.10.0",
        )
        self.assertLess(self.server.served, len(self.payload))

    def test_missing_range_support_falls_back_to_full_download(self):
        digest = hashlib.sha256(self.payload).hexdigest()
        for missing in ("head", "range"):
            with self.subTest(missing=missing):
                self.forget_workspace()
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

    def test_cancellation_keeps_incremental_workspace(self):
        cancelled = Event()
        cancelled.set()
        with (
            self.assertNoLogs(service.__name__, level="ERROR"),
            self.assertRaises(service.UpdateCancelled),
        ):
            self.client.prepare_update(self.release, cancelled=cancelled)
        self.assert_workspace(kept=True)
