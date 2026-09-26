"""remotezip 直接提供远端 ZipFile；仅补充响应校验和分块取消。"""

import io
import re
import zipfile
import zlib
from contextlib import contextmanager
from threading import Event

from src.update.package import MAX_PACKAGE_BYTES, UpdateError, check_cancelled


class RemoteUnavailable(UpdateError):
    """远端不支持范围读取或 ZIP 目录损坏；调用方应回退全量下载。"""


class _CancellableReader(io.RawIOBase):
    """由 BufferedReader 组装读取，限制每次网络读取并检查取消及长度。"""

    def __init__(self, raw, length: int, cancelled: Event | None):
        self.raw, self.remaining, self.cancelled = raw, length, cancelled

    def readable(self):
        return True

    def tell(self):
        return self.raw.tell()

    def readinto(self, buffer):
        from urllib3.exceptions import HTTPError

        check_cancelled(self.cancelled)
        try:
            count = self.raw.readinto(memoryview(buffer)[:65536])
        except (OSError, HTTPError) as exc:
            raise UpdateError(f"范围读取失败 ({type(exc).__name__}): {exc}") from exc
        check_cancelled(self.cancelled)
        if count > self.remaining or (not count and self.remaining):
            raise UpdateError("范围响应长度不符")
        self.remaining -= count
        return count

    def close(self):
        self.raw.close()
        self.raw.release_conn()
        super().close()


@contextmanager
def open_archive(url: str, *, cancelled: Event | None = None):
    """让 remotezip 处理 HEAD、Range 和 ZIP 读取，保留更新错误语义。"""
    import requests
    from remotezip import OutOfBound, RemoteZip, RemoteZipError

    check_cancelled(cancelled)
    size = 0

    def validate(response, **_kwargs):
        nonlocal size
        if response.is_redirect:
            return response
        try:
            check_cancelled(cancelled)
            if response.request.method == "HEAD" and response.status_code in (405, 501):
                raise RemoteUnavailable("远端不支持读取归档大小")
            response.raise_for_status()
            if response.request.method == "HEAD":
                if "Content-Length" not in response.headers:
                    raise RemoteUnavailable("远端未返回归档大小")
                size = int(response.headers["Content-Length"])
                if not 22 <= size <= MAX_PACKAGE_BYTES:
                    raise RemoteUnavailable("远端 ZIP 大小无效")
                return response
            if response.status_code != 206:
                raise RemoteUnavailable("远端不支持范围读取")
            assert "Range" in response.request.headers
            match = re.fullmatch(
                r"bytes=(\d+)-(\d+)", response.request.headers["Range"]
            )
            if match is None or not 0 <= int(match[1]) <= int(match[2]) < size:
                raise RemoteUnavailable("远端 ZIP 范围越界")
            start, end = int(match[1]), int(match[2])
            if (
                "Content-Range" not in response.headers
                or response.headers["Content-Range"] != f"bytes {start}-{end}/{size}"
            ):
                raise UpdateError("范围响应位置或归档大小不符")
            length = end - start + 1
            if (
                "Content-Length" in response.headers
                and int(response.headers["Content-Length"]) != length
            ):
                raise UpdateError("范围响应长度不符")
            response.raw = io.BufferedReader(
                _CancellableReader(response.raw, length, cancelled)
            )
            return response
        except (OSError, ValueError):
            response.close()
            raise

    with requests.Session() as session:
        session.headers["Accept-Encoding"] = "identity"
        session.hooks["response"].append(validate)
        try:
            try:
                archive = RemoteZip(
                    url,
                    session=session,
                    support_suffix_range=False,
                    allow_redirects=True,
                    timeout=(10, 30),
                )
            except (zipfile.BadZipFile, OutOfBound) as exc:
                raise RemoteUnavailable("远端 ZIP 目录损坏") from exc
            with archive, archive.fp:
                yield archive
        except (
            RemoteZipError,
            zipfile.BadZipFile,
            zlib.error,
            EOFError,
            NotImplementedError,
        ) as exc:
            raise UpdateError(f"范围读取失败 ({type(exc).__name__}): {exc}") from exc
