"""远端 ZIP 按需读取；HTTP 负责范围下载，zipfile 负责归档解析与解压。"""

import io
import re
import stat
import zipfile
import zlib
from collections.abc import Callable, Iterable
from threading import Event

from src.update.package import (
    MANIFEST,
    MAX_PACKAGE_BYTES,
    UpdateCancelled,
    UpdateError,
    managed_path,
)

ARCHIVE_PREFIX = "OneDragon-Helper/"
TAIL_BYTES = 65558
MERGE_GAP = 65536
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


def _merge(
    ranges: Iterable[tuple[int, int]], gap: int = MERGE_GAP
) -> list[tuple[int, int]]:
    """合并间隔不超过 gap 的区间，减少请求次数。"""
    merged: list[list[int]] = []
    for start, end in sorted(ranges):
        if merged and start - merged[-1][1] <= gap:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


class RemoteArchive(io.RawIOBase):
    """为 zipfile 提供可 seek 的范围读取，缓存目录并预取选中条目。"""

    def __init__(self, session, url: str, size: int, cancelled: Event | None = None):
        self._session = session
        self.url = url
        self.size = size
        self._cancelled = cancelled
        self._position = 0
        self._spans: list[tuple[int, int, bytes]] = []
        self._archive: zipfile.ZipFile | None = None

    def close(self) -> None:
        if self._archive is not None:
            self._archive.close()
        self._session.close()
        super().close()

    def seekable(self) -> bool:
        return True

    def readable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._position

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_SET:
            position = offset
        elif whence == io.SEEK_CUR:
            position = self._position + offset
        else:
            assert whence == io.SEEK_END
            position = self.size + offset
        if position < 0:
            raise OSError("归档读取偏移不能为负数")
        self._position = position
        return position

    def _check_cancelled(self) -> None:
        if self._cancelled is not None and self._cancelled.is_set():
            raise UpdateCancelled("下载已取消")

    def read(self, size: int = -1) -> bytes:
        self._check_cancelled()
        start = self._position
        end = self.size - 1 if size < 0 else min(start + size, self.size) - 1
        if end < start:
            return b""
        for span_start, span_end, block in self._spans:
            if span_start <= start and end <= span_end:
                self._position = end + 1
                return block[start - span_start : end - span_start + 1]
        # zipfile 会分别读取尾记录和 ZIP64 定位记录，一次缓存包尾避免碎请求。
        fetch_start = min(start, max(0, self.size - TAIL_BYTES))
        try:
            block = self._get(fetch_start, end)
        except OSError as exc:
            # zipfile 会将 OSError 转成 BadZipFile；网络错误不能因此触发整包回退。
            raise UpdateError(f"范围读取失败 ({type(exc).__name__}): {exc}") from exc
        self._spans.append((fetch_start, end, block))
        self._position = end + 1
        return block[start - fetch_start :]

    def _get(
        self, start: int, end: int, progress: Callable[[int], None] | None = None
    ) -> bytes:
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
                if progress is not None:
                    progress(len(chunk))
                self._check_cancelled()
        if len(block) != limit:
            raise UpdateError(f"范围响应长度不符: {len(block)} != {limit}")
        return bytes(block)

    def entries(self) -> dict[str, zipfile.ZipInfo]:
        """用标准库读取目录，检查程序路径及解压大小边界。"""
        try:
            self._archive = zipfile.ZipFile(self)
        except zipfile.BadZipFile as exc:
            raise RemoteUnavailable("远端 ZIP 目录损坏") from exc
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
        """预取选中条目到下一条目头的区间，交由标准库定位并解压。"""
        assert self._archive is not None
        if cancelled is not None:
            self._cancelled = cancelled
        self._check_cancelled()
        selected = {}
        for name in names:
            if name not in entries:
                raise RemoteUnavailable(f"远端 ZIP 缺少条目: {name}")
            selected[name] = entries[name]
        offsets = sorted({entry.header_offset for entry in entries.values()})
        ends = dict(zip(offsets, [*offsets[1:], self.size], strict=True))
        ranges = []
        for entry in selected.values():
            assert entry.header_offset in ends
            ranges.append((entry.header_offset, ends[entry.header_offset] - 1))
        merged = _merge(ranges)
        limit = sum(end - start + 1 for start, end in merged)
        received = 0

        def report(chunk_size: int) -> None:
            nonlocal received
            received += chunk_size
            if progress is not None:
                progress(received, limit)

        cached = len(self._spans)
        blobs = {}
        try:
            for start, end in merged:
                self._spans.append((start, end, self._get(start, end, report)))
            for name, entry in selected.items():
                self._check_cancelled()
                with self._archive.open(entry) as source:
                    blob = bytearray()
                    while chunk := source.read(CHUNK_BYTES):
                        self._check_cancelled()
                        blob.extend(chunk)
                blobs[name] = bytes(blob)
        except (zipfile.BadZipFile, zlib.error, EOFError) as exc:
            raise UpdateError("下载 ZIP 条目损坏") from exc
        finally:
            del self._spans[cached:]
        self._check_cancelled()
        return blobs
