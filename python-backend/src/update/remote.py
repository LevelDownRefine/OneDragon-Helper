"""remotezip 直接提供远端 ZipFile；仅补充响应校验、分块取消和断点缓存。"""

import io
import json
import os
import re
import zipfile
import zlib
from contextlib import contextmanager
from pathlib import Path
from threading import Event

from src.update.package import MAX_PACKAGE_BYTES, UpdateError, check_cancelled

CHUNK = 65536


class RemoteUnavailable(UpdateError):
    """远端不支持范围读取或 ZIP 目录损坏；调用方应回退全量下载。"""


class UpdateInterrupted(UpdateError):
    """网络中断或范围读取不完整；工作目录可保留续传。"""


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
            count = self.raw.readinto(memoryview(buffer)[:CHUNK])
        except (OSError, HTTPError) as exc:
            raise UpdateInterrupted(
                f"范围读取失败 ({type(exc).__name__}): {exc}"
            ) from exc
        check_cancelled(self.cancelled)
        if count > self.remaining or (not count and self.remaining):
            raise UpdateInterrupted("范围响应提前结束")
        self.remaining -= count
        return count

    def close(self):
        self.raw.close()
        self.raw.release_conn()
        super().close()


class _RangeBuffer:
    """远端坐标上的区间缓冲；已落盘的字节跨次复用，缺口按需补齐。"""

    def __init__(self, fetcher, cache: Path, start: int, end: int):
        self._fetcher = fetcher
        self._start, self._end = start, end
        self._position = start
        self._file = (cache / f"{start}-{end}.bin").open("a+b")
        self._have = self._file.seek(0, 2)
        if self._have > len(self):
            self._file.truncate(0)
            self._have = 0

    def __len__(self):
        return self._end - self._start + 1

    def tell(self):
        return self._position

    def seek(self, offset, whence=0):
        # 与 PartialBuffer 一致：越界前先更新位置，调用方靠 tell() 取文件末尾。
        from remotezip import OutOfBound

        if whence == 2:
            self._position = self._end + 1 + offset
        elif whence == 0:
            self._position = offset
        else:
            self._position += offset
        if not self._start <= self._position <= self._end:
            raise OutOfBound("位置超出区间")
        while self._start + self._have < self._position:
            if not self._pull():
                raise OutOfBound("区间数据已结束")
        return self._position

    def read(self, size=0):
        if size == 0:
            size = self._end + 1 - self._position
        size = min(size, self._end + 1 - self._position)
        chunks = []
        filled = 0
        while filled < size:
            if self._position - self._start >= self._have and not self._pull():
                break
            self._file.seek(self._position - self._start)
            chunk = self._file.read(size - filled)
            if not chunk:
                break
            self._position += len(chunk)
            filled += len(chunk)
            chunks.append(chunk)
        return b"".join(chunks)

    def close(self):
        self._file.close()

    def _pull(self) -> bool:
        """连续拉取一段并落盘，返回是否读到新字节。失败时关掉文件，避免占住断点。"""
        if self._have >= len(self):
            return False
        start = self._start + self._have
        end = min(self._end, start + CHUNK - 1)
        try:
            response = self._fetcher.range_response(start, end)
            with response:
                while self._have < end - self._start + 1:
                    chunk = response.raw.read(CHUNK)
                    if not chunk:
                        raise UpdateInterrupted("范围响应提前结束")
                    self._file.write(chunk)
                    self._have += len(chunk)
        except Exception:
            # 半截写会让文件比已收字节长，截回去才保住区间偏移与文件长度的对应。
            try:
                self._file.truncate(self._have)
            finally:
                self.close()
            raise
        return True


class ResumableFetcher:
    """remotezip 的 fetcher；按区间落盘读取，中断后只补缺口。

    远端标识（大小与 ETag）变化时丢弃缓存，避免混用两次发布的字节。
    """

    def __init__(
        self,
        url: str,
        session=None,
        support_suffix_range=True,
        *,
        cache: Path,
        **kwargs,
    ):
        self._url = url
        self._session = session
        self._cache = cache
        self._options = kwargs
        self._size = 0
        self._checked = False

    def fetch(self, data_range, stream=False):
        """按 remotezip 的区间请求返回缓冲；后缀区间自行换算为正向区间。

        两种 stream 模式都返回按需拉取的缓冲，整段不进内存。
        """
        self._check_remote()
        start, end = data_range
        if start < 0 and end is None:
            start, end = max(0, self._size + start), self._size - 1
        if not 0 <= start <= end < self._size:
            raise RemoteUnavailable("远端 ZIP 范围越界")
        return _RangeBuffer(self, self._cache, start, end)

    def range_response(self, start: int, end: int):
        """一次范围请求；状态、范围与取消由会话钩子负责。"""
        session = self._session or self._requests()
        try:
            return session.get(
                self._url,
                stream=True,
                headers={"Range": f"bytes={start}-{end}"},
                **self._options,
            )
        except OSError as exc:
            raise UpdateInterrupted(
                f"范围读取失败 ({type(exc).__name__}): {exc}"
            ) from exc

    def _check_remote(self) -> None:
        """首个读取前核对远端标识；缺失标识或不一致就清空断点缓存。"""
        if self._checked:
            return
        session = self._session or self._requests()
        response = session.head(self._url, **self._options)
        with response:
            self._size = int(response.headers["Content-Length"])
            identity = [
                self._size,
                response.headers.get("ETag")
                or response.headers.get("Last-Modified")
                or "",
            ]
        self._cache.mkdir(parents=True, exist_ok=True)
        state = self._cache / "state.json"
        stored = None
        if identity[1] and state.is_file():
            stored = json.loads(state.read_text(encoding="utf-8"))
        # 没有标识就无法判断远端是否改过，只能每次重来，避免混用两次的字节。
        if stored != identity:
            for path in self._cache.glob("*.bin"):
                path.unlink()
        # 同目录临时文件加原子替换，崩在写一半也不会留下坏 JSON 让下次判成坏缓存。
        temporary = state.with_name(state.name + ".tmp")
        temporary.write_text(json.dumps(identity), encoding="utf-8")
        os.replace(temporary, state)
        self._checked = True

    @staticmethod
    def _requests():
        import requests

        return requests


@contextmanager
def open_archive(url: str, *, cache: Path, cancelled: Event | None = None):
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
        session.hooks["response"] = [validate]
        try:
            try:
                archive = RemoteZip(
                    url,
                    session=session,
                    fetcher=ResumableFetcher,
                    support_suffix_range=False,
                    allow_redirects=True,
                    timeout=(10, 30),
                    cache=cache,
                )
            except (zipfile.BadZipFile, OutOfBound) as exc:
                raise RemoteUnavailable("远端 ZIP 目录损坏") from exc
            with archive, archive.fp:
                yield archive
        except NotImplementedError as exc:
            raise UpdateError(f"远端 ZIP 压缩方式不受支持: {exc}") from exc
        except (
            RemoteZipError,
            zipfile.BadZipFile,
            zlib.error,
            EOFError,
        ) as exc:
            raise UpdateInterrupted(
                f"范围读取失败 ({type(exc).__name__}): {exc}"
            ) from exc
