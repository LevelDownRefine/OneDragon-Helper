"""远端 ZIP 按需读取；remotezip 负责定位与读取，下载适配负责取消及响应校验。"""

import io
import re
import stat
import zipfile
import zlib
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from threading import Event

from src.update.package import (
    MANIFEST,
    MAX_PACKAGE_BYTES,
    UpdateCancelled,
    UpdateError,
    managed_path,
)

ARCHIVE_PREFIX = "OneDragon-Helper/"
CHUNK_BYTES = 65536


class RemoteUnavailable(UpdateError):
    """远端 ZIP 结构不支持按需读取；调用方应回退全量下载。"""


def open_archive(url: str, *, cancelled: Event | None = None) -> "RemoteArchive":
    """探测归档大小与重定向后的签名地址，建立按需读取器。"""
    import requests

    if cancelled is not None and cancelled.is_set():
        raise UpdateCancelled("下载已取消")
    session = requests.Session()
    session.headers["Accept-Encoding"] = "identity"
    try:
        with session.get(
            url, stream=True, headers={"Range": "bytes=0-0"}, timeout=(10, 30)
        ) as response:
            response.raise_for_status()
            if response.status_code != 206:
                raise RemoteUnavailable("远端不支持范围读取")
            match = re.fullmatch(
                r"bytes 0-0/(\d+)", response.headers.get("Content-Range", "")
            )
            if match is None or not 0 < int(match[1]) <= MAX_PACKAGE_BYTES:
                raise RemoteUnavailable("远端未返回有效归档大小")
            return RemoteArchive(session, response.url, int(match[1]), cancelled)
    except (OSError, ValueError):
        session.close()
        raise


class RemoteArchive(AbstractContextManager):
    """封装 remotezip，保留更新包边界与可取消的分块下载。"""

    def __init__(self, session, url: str, size: int, cancelled: Event | None = None):
        self._session = session
        self.url = url
        self.size = size
        self._cancelled = cancelled
        self._archive: zipfile.ZipFile | None = None
        self._progress: Callable[[int], None] | None = None

    def close(self) -> None:
        if self._archive is not None:
            self._archive.close()
        self._session.close()

    def __exit__(self, *_args):
        self.close()
        return False

    def _check_cancelled(self) -> None:
        if self._cancelled is not None and self._cancelled.is_set():
            raise UpdateCancelled("下载已取消")

    def _get(self, start: int, end: int) -> bytes:
        self._check_cancelled()
        if not 0 <= start <= end < self.size:
            raise RemoteUnavailable("远端 ZIP 范围越界")
        limit = end - start + 1
        with self._session.get(
            self.url,
            stream=True,
            headers={"Range": f"bytes={start}-{end}"},
            timeout=(10, 30),
        ) as response:
            response.raise_for_status()
            if response.status_code != 206:
                raise RemoteUnavailable("远端不支持范围读取")
            if response.headers.get("Content-Range", "") != (
                f"bytes {start}-{end}/{self.size}"
            ):
                raise UpdateError("范围响应位置或归档大小不符")
            block = bytearray()
            for chunk in response.iter_content(CHUNK_BYTES):
                self._check_cancelled()
                block.extend(chunk)
                if len(block) > limit:
                    raise UpdateError("范围响应数据超出预期大小")
                if self._progress is not None:
                    self._progress(len(chunk))
                self._check_cancelled()
        if len(block) != limit:
            raise UpdateError(f"范围响应长度不符: {len(block)} != {limit}")
        return bytes(block)

    def entries(self) -> dict[str, zipfile.ZipInfo]:
        """延迟加载 remotezip，检查程序路径及解压大小边界。"""
        from remotezip import OutOfBound, RemoteFetcher, RemoteZip, RemoteZipError

        archive = self

        class Fetcher(RemoteFetcher):
            # 使用已探测的大小，避免 suffix Range 和额外的 HEAD 请求。
            def get_file_size(self):
                return archive.size

            def _request(self, kwargs):
                assert "headers" in kwargs and "Range" in kwargs["headers"]
                match = re.fullmatch(r"bytes=(\d+)-(\d+)", kwargs["headers"]["Range"])
                if match is None:
                    raise RemoteUnavailable("远端 ZIP 范围越界")
                start, end = int(match[1]), int(match[2])
                try:
                    block = archive._get(start, end)
                except OSError as exc:
                    # 网络错误不能被 zipfile 转成目录损坏后触发整包回退。
                    raise UpdateError(
                        f"范围读取失败 ({type(exc).__name__}): {exc}"
                    ) from exc
                return io.BytesIO(block), f"bytes {start}-{end}/{archive.size}"

        try:
            self._archive = RemoteZip(
                self.url,
                session=self._session,
                fetcher=Fetcher,
                support_suffix_range=False,
            )
        except (zipfile.BadZipFile, OutOfBound) as exc:
            raise RemoteUnavailable("远端 ZIP 目录损坏") from exc
        except RemoteZipError as exc:
            raise UpdateError(f"远端 ZIP 读取失败: {exc}") from exc
        members = self._archive.infolist()
        if (
            len(members) > 20000
            or sum(item.file_size for item in members) > MAX_PACKAGE_BYTES
        ):
            raise UpdateError("更新包解压后过大")
        entries = {}
        folded = set()
        for item in members:
            name = item.filename
            if (
                item.is_dir()
                or stat.S_ISLNK(item.external_attr >> 16)
                or item.flag_bits & 1
                or item.compress_type != zipfile.ZIP_DEFLATED
                or not name.startswith(ARCHIVE_PREFIX)
                or not 0 <= item.header_offset < self.size
            ):
                raise RemoteUnavailable(f"远端 ZIP 条目不支持按需读取: {name}")
            relative = name[len(ARCHIVE_PREFIX) :]
            if not managed_path(relative) or relative.casefold() in folded:
                raise RemoteUnavailable(f"远端 ZIP 文件重复或不允许: {relative}")
            if relative == MANIFEST and item.file_size > 4 * 1024**2:
                raise UpdateError("更新清单过大")
            entries[relative] = item
            folded.add(relative.casefold())
        return entries

    def fetch(
        self,
        entries: dict[str, zipfile.ZipInfo],
        names: Iterable[str],
        *,
        progress: Callable[[int, int], None] | None = None,
        cancelled: Event | None = None,
    ) -> dict[str, bytes]:
        """逐条读取变化文件；按所选 ZIP 区间报告准备进度。"""
        from remotezip import RemoteZipError

        assert self._archive is not None
        if cancelled is not None:
            self._cancelled = cancelled
        self._check_cancelled()
        selected = {}
        for name in names:
            if name not in entries:
                raise RemoteUnavailable(f"远端 ZIP 缺少条目: {name}")
            selected[name] = entries[name]
        # 区间仅用于进度总量；条目定位及实际请求范围由 remotezip 决定。
        offsets = sorted({entry.header_offset for entry in entries.values()})
        ends = dict(zip(offsets, [*offsets[1:], self._archive.start_dir], strict=True))
        limit = 0
        for entry in selected.values():
            assert entry.header_offset in ends
            limit += ends[entry.header_offset] - entry.header_offset
        received = 0

        def report(chunk_size: int) -> None:
            nonlocal received
            received += chunk_size
            if progress is not None:
                progress(min(received, limit), limit)

        blobs = {}
        self._progress = report
        try:
            for name, entry in selected.items():
                self._check_cancelled()
                with self._archive.open(entry) as source:
                    blob = bytearray()
                    while chunk := source.read(CHUNK_BYTES):
                        self._check_cancelled()
                        blob.extend(chunk)
                blobs[name] = bytes(blob)
            # 包尾缓存中的条目无需下载，也计入已完成的准备进度。
            if progress is not None:
                progress(limit, limit)
            self._check_cancelled()
        except (zipfile.BadZipFile, zlib.error, EOFError, RemoteZipError) as exc:
            raise UpdateError("下载 ZIP 条目损坏") from exc
        finally:
            self._progress = None
        return blobs
