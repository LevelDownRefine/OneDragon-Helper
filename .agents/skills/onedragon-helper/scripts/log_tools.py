"""Discover and read declared logs without inferring execution outcomes."""

from __future__ import annotations

import codecs
import fnmatch
import os
import stat
from collections import deque
from datetime import UTC, datetime
from pathlib import Path

MAX_OUTPUT_CHARS = 64_000
MAX_OUTPUT_LINES = 2_000
MAX_CONTEXT_LINES = 50
MAX_MATCHES = 100
MAX_FILES = 1_000


def _integer(name: str, value: int, minimum: int, maximum: int | None = None) -> None:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be <= {maximum}")


def _check_pattern(path: Path) -> None:
    if any(char in str(path.parent) for char in "*?") or "**" in path.name:
        raise ValueError("Only the filename may contain a non-recursive glob")


def list_log_files(patterns: dict[str, str | None], limit: int = 10) -> dict:
    """List unique matching files by mtime, with explicit missing/error records."""
    _integer("limit", limit, 1, MAX_FILES)
    if not isinstance(patterns, dict):
        raise ValueError("patterns must be an object")
    files: dict[str, dict] = {}
    missing = []
    errors = []
    for kind, raw in patterns.items():
        if not isinstance(kind, str) or not kind:
            raise ValueError("pattern kinds must be non-empty strings")
        if raw is None:
            missing.append({"kind": kind, "pattern": None, "reason": "not_declared"})
            continue
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError(f"Pattern {kind} must be non-empty text or null")
        pattern = Path(raw.replace("\\", "/"))
        _check_pattern(pattern)
        pattern = pattern.absolute()
        found = 0
        pattern_errors = 0

        def error(
            path: Path,
            exc: OSError,
            *,
            log_kind: str = kind,
            log_pattern: Path = pattern,
        ) -> None:
            nonlocal pattern_errors
            pattern_errors += 1
            errors.append(
                {
                    "kind": log_kind,
                    "pattern": str(log_pattern),
                    "path": str(path),
                    "error": type(exc).__name__,
                    "message": str(exc),
                }
            )

        try:
            # iterdir surfaces directory errors; glob may silently suppress them.
            for path in pattern.parent.iterdir():
                if not fnmatch.fnmatch(path.name, pattern.name):
                    continue
                try:
                    info = path.stat()
                    if not stat.S_ISREG(info.st_mode):
                        continue
                    absolute = path.resolve()
                except OSError as exc:
                    error(path, exc)
                    continue
                found += 1
                identity = os.path.normcase(str(absolute))
                if identity in files:
                    if kind not in files[identity]["kinds"]:
                        files[identity]["kinds"].append(kind)
                    continue
                timestamp = datetime.fromtimestamp(info.st_mtime, tz=UTC)
                files[identity] = {
                    "path": str(absolute),
                    "size": info.st_size,
                    "mtime": info.st_mtime,
                    "mtime_iso": timestamp.isoformat(),
                    "timezone": "UTC",
                    "kinds": [kind],
                }
        except FileNotFoundError:
            missing.append(
                {"kind": kind, "pattern": str(pattern), "reason": "directory_missing"}
            )
            continue
        except OSError as exc:
            error(pattern.parent, exc)
        if found == 0 and pattern_errors == 0:
            missing.append(
                {"kind": kind, "pattern": str(pattern), "reason": "no_matches"}
            )
    ordered = sorted(files.values(), key=lambda row: (-row["mtime"], row["path"]))
    return {
        "files": ordered[:limit],
        "total": len(ordered),
        "truncated": len(ordered) > limit,
        "omitted": max(0, len(ordered) - limit),
        "missing": missing,
        "errors": errors,
    }


def _encoding(path: Path, requested: str) -> str:
    if not isinstance(requested, str) or not requested:
        raise ValueError("encoding must be a non-empty string")
    if requested != "auto":
        try:
            return codecs.lookup(requested).name
        except LookupError as exc:
            raise ValueError(f"Unknown encoding: {requested}") from exc
    with path.open("rb") as source:
        prefix = source.read(4)
        if prefix.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
            return "utf-32"
        if prefix.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
            return "utf-16"
        if prefix.startswith(codecs.BOM_UTF8):
            return "utf-8-sig"
    return "utf-8"


def read_log(
    path: Path,
    start_line: int = 1,
    lines: int = 200,
    find: str | None = None,
    context: int = 3,
    max_matches: int = 20,
    encoding: str = "auto",
) -> dict:
    """Read numbered lines or literal-match context, bounded by lines and characters.

    Search starts at start_line and scans to EOF. Context never precedes start_line.
    Matches count matching lines, not occurrences. File/decoding errors propagate.
    """
    _integer("start_line", start_line, 1)
    _integer("lines", lines, 1, MAX_OUTPUT_LINES)
    _integer("context", context, 0, MAX_CONTEXT_LINES)
    _integer("max_matches", max_matches, 1, MAX_MATCHES)
    if find is not None and (not isinstance(find, str) or not find):
        raise ValueError("find must be non-empty text or null")
    if find is not None and ("\n" in find or "\r" in find):
        raise ValueError("find must be a single-line literal")
    path = Path(path).resolve()
    selected_encoding = _encoding(path, encoding)
    try:
        return _read_log(
            path, start_line, lines, find, context, max_matches, selected_encoding
        )
    except UnicodeDecodeError:
        if encoding != "auto" or selected_encoding != "utf-8":
            raise
    # Restart with fresh output, context and counters after a failed UTF-8 pass.
    return _read_log(path, start_line, lines, find, context, max_matches, "gb18030")


def _read_log(
    path: Path,
    start_line: int,
    lines: int,
    find: str | None,
    context: int,
    max_matches: int,
    selected_encoding: str,
) -> dict:
    output = []
    matches = []
    reasons = set()
    used_chars = 0
    last_selected = 0
    selected_lines = 0
    total_lines = 0
    total_matches = 0
    context_until = 0
    previous: deque[tuple[int, str]] = deque(maxlen=context)

    def add(number: int, text: str) -> None:
        nonlocal used_chars, last_selected, selected_lines
        if number <= last_selected:
            return
        last_selected = number
        selected_lines += 1
        if len(output) >= lines:
            reasons.add("line_limit")
            return
        remaining = MAX_OUTPUT_CHARS - used_chars
        if remaining <= 0:
            reasons.add("character_limit")
            return
        row = {"line": number, "text": text[:remaining]}
        if len(text) > remaining:
            row["truncated"] = True
            reasons.add("character_limit")
        output.append(row)
        used_chars += len(row["text"])

    with path.open("r", encoding=selected_encoding, errors="strict") as source:
        for number, raw in enumerate(source, start=1):
            total_lines = number
            if number < start_line:
                continue
            text = raw.rstrip("\r\n")
            if find is None:
                add(number, text)
                continue
            if find in text:
                total_matches += 1
                if len(matches) < max_matches:
                    matches.append(number)
                    for preceding_number, preceding_text in previous:
                        add(preceding_number, preceding_text)
                    add(number, text)
                    context_until = number + context
                else:
                    reasons.add("match_limit")
            if number <= context_until:
                add(number, text)
            # One extra character preserves truncation evidence for long lines.
            previous.append((number, text[: MAX_OUTPUT_CHARS + 1]))
    return {
        "path": str(path),
        "encoding": selected_encoding,
        "start_line": start_line,
        "total_lines": total_lines,
        "lines": output,
        "find": find,
        "matches": matches,
        "total_matches": total_matches,
        "selected_lines": selected_lines,
        "truncated": bool(reasons),
        "truncation_reasons": sorted(reasons),
        "max_output_chars": MAX_OUTPUT_CHARS,
    }
