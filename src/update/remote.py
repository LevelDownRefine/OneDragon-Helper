"""release ZIP 的按需读取；只拉取变化条目，供增量更新使用。

发布侧仍只产出一个 ZIP：这里用 HTTP 范围请求读它的中央目录，再按需取回变化的
条目，避免整包重下。远端不支持范围读取或结构异常时抛 `RemoteUnavailable`，
由调用方回退全量下载。
"""

import logging
import struct
import zlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from threading import Event

from src.update.package import UpdateCancelled, UpdateError, managed_path

logger = logging.getLogger(__name__)

ARCHIVE_PREFIX = "OneDragon-Helper/"
TAIL_BYTES = 65536
MERGE_GAP = 65536
LOCAL_HEADER_BYTES = 30
CENTRAL_HEADER_BYTES = 46
EXTRA_GUESS = 64
_DEFLATE = 8
_END_OF_CENTRAL = b"PK\x05\x06"
_CENTRAL_RECORD = b"PK\x01\x02"
_LOCAL_HEADER = b"PK\x03\x04"
_ZIP64_MARKER = 0xFFFFFFFF


class RemoteUnavailable(UpdateError):
    """远端 ZIP 结构不支持按需读取；调用方应回退全量下载。"""


@dataclass(frozen=True)
class ZipEntry:
    """中央目录的一条记录；偏移相对归档起点，大小为压缩后字节数。"""

    offset: int
    compressed_size: int
    file_size: int


def open_archive(url: str) -> "RemoteArchive":
    """探测归档大小与重定向后的签名地址，建立按需读取器。"""
    import requests

    session = requests.Session()
    session.headers["Accept-Encoding"] = "identity"
    try:
        with session.get(
            url, stream=True, headers={"Range": "bytes=0-0"}, timeout=(10, 60)
        ) as response:
            response.raise_for_status()
            if response.status_code != 206:
                raise RemoteUnavailable("远端不支持范围读取")
            _, _, total = response.headers.get("Content-Range", "").partition("/")
            if not total.isdigit():
                raise RemoteUnavailable("远端未返回归档大小")
            return RemoteArchive(session, response.url, int(total))
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


class RemoteArchive:
    """按需读取远端 ZIP；连接复用，条目数据按需拉取。"""

    def __init__(self, session, url: str, size: int):
        self._session = session
        self.url = url
        self.size = size

    def __enter__(self) -> "RemoteArchive":
        return self

    def __exit__(self, *_args) -> None:
        self._session.close()

    def _get(self, start: int, end: int) -> bytes:
        with self._session.get(
            self.url,
            stream=True,
            headers={"Range": f"bytes={start}-{end}"},
            timeout=(10, 60),
        ) as response:
            if response.status_code != 206:
                raise RemoteUnavailable("远端不支持范围读取")
            block = response.content
        if len(block) != end - start + 1:
            raise UpdateError(f"范围响应长度不符: {len(block)} != {end - start + 1}")
        return block

    def entries(self) -> dict[str, ZipEntry]:
        """读取中央目录；结构或路径异常时抛 RemoteUnavailable。"""
        tail = self._get(max(0, self.size - TAIL_BYTES), self.size - 1)
        position = tail.rfind(_END_OF_CENTRAL)
        if position < 0:
            raise RemoteUnavailable("远端 ZIP 缺少中央目录结尾")
        count, size, offset = struct.unpack("<HII", tail[position + 10 : position + 20])
        if offset == _ZIP64_MARKER or size == _ZIP64_MARKER:
            raise RemoteUnavailable("远端 ZIP 使用 ZIP64，不支持按需读取")
        central = self._get(offset, offset + size - 1)
        entries: dict[str, ZipEntry] = {}
        cursor = 0
        for _ in range(count):
            if central[cursor : cursor + 4] != _CENTRAL_RECORD:
                raise RemoteUnavailable("远端 ZIP 中央目录损坏")
            (method,) = struct.unpack_from("<H", central, cursor + 10)
            compressed, file_size = struct.unpack_from("<II", central, cursor + 20)
            name_length, extra_length, comment_length = struct.unpack_from(
                "<HHH", central, cursor + 28
            )
            (header_offset,) = struct.unpack_from("<I", central, cursor + 42)
            name = central[
                cursor + CENTRAL_HEADER_BYTES : cursor
                + CENTRAL_HEADER_BYTES
                + name_length
            ].decode("utf-8")
            cursor += CENTRAL_HEADER_BYTES + name_length + extra_length + comment_length
            if method != _DEFLATE:
                raise RemoteUnavailable(f"不支持的压缩方式: {name}")
            if not name.startswith(ARCHIVE_PREFIX):
                raise RemoteUnavailable(f"远端 ZIP 包含非程序路径: {name}")
            relative = name[len(ARCHIVE_PREFIX) :]
            if not managed_path(relative) or relative in entries:
                raise RemoteUnavailable(f"远端 ZIP 文件重复或不允许: {relative}")
            entries[relative] = ZipEntry(header_offset, compressed, file_size)
        return entries

    def fetch(
        self,
        entries: dict[str, ZipEntry],
        names: Iterable[str],
        *,
        progress: Callable[[int, int], None] | None = None,
        cancelled: Event | None = None,
    ) -> dict[str, bytes]:
        """取回指定条目并解压；返回条目名到字节的映射。

        按预估值把每个条目的完整区间（条目头加数据）合并成少数几次请求，下载后
        再校验条目头定位数据。余量只多取 EXTRA_GUESS 字节。
        """
        selected: dict[str, ZipEntry] = {}
        for name in names:
            if name not in entries:
                raise RemoteUnavailable(f"远端 ZIP 缺少条目: {name}")
            selected[name] = entries[name]
        spans = self._fetch_spans(selected, progress, cancelled)
        blobs: dict[str, bytes] = {}
        for name, entry in selected.items():
            head = _locate(spans, entry.offset, entry.offset + LOCAL_HEADER_BYTES - 1)
            if head is None or head[:4] != _LOCAL_HEADER:
                raise RemoteUnavailable(f"远端 ZIP 条目头超出预估范围: {name}")
            name_length, extra_length = struct.unpack_from("<HH", head, 26)
            start = entry.offset + LOCAL_HEADER_BYTES + name_length + extra_length
            raw = _locate(spans, start, start + entry.compressed_size - 1)
            if raw is None:
                raise RemoteUnavailable(f"远端 ZIP 条目数据超出预估范围: {name}")
            try:
                blob = zlib.decompress(raw, -15)
            except zlib.error as exc:
                raise UpdateError(f"条目解压失败: {name}") from exc
            if len(blob) != entry.file_size:
                raise UpdateError(f"条目解压大小不符: {name}")
            blobs[name] = blob
        return blobs

    def _fetch_spans(
        self,
        selected: dict[str, ZipEntry],
        progress: Callable[[int, int], None] | None,
        cancelled: Event | None,
    ) -> list[tuple[int, int, bytes]]:
        """按合并后的区间下载，返回 (起, 止, 字节) 列表。"""
        merged = _merge(
            (
                entry.offset,
                min(
                    entry.offset
                    + LOCAL_HEADER_BYTES
                    + EXTRA_GUESS
                    + entry.compressed_size,
                    self.size,
                )
                - 1,
            )
            for entry in selected.values()
        )
        limit = sum(end - start + 1 for start, end in merged)
        received = 0
        spans = []
        for start, end in merged:
            if cancelled is not None and cancelled.is_set():
                raise UpdateCancelled("下载已取消")
            block = self._get(start, end)
            received += len(block)
            if progress is not None:
                progress(received, limit)
            spans.append((start, end, block))
        return spans


def _locate(spans: list[tuple[int, int, bytes]], start: int, end: int) -> bytes | None:
    """已下载区间里取子区间；未覆盖时返回 None。"""
    for span_start, span_end, block in spans:
        if span_start <= start and end <= span_end:
            origin = start - span_start
            return block[origin : origin + end - start + 1]
    return None
