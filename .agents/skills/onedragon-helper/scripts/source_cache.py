"""Fetch the existing backend source without replacing local changes."""

import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

REPOSITORY = "https://github.com/LevelDownRefine/OneDragon-Helper.git"
GIT_TIMEOUT = 60
REQUIRED_FILES = (
    "python-backend/src/utils/__init__.py",
    "config/log_analysis.yml",
)


class SourceCacheError(RuntimeError):
    """Source setup or validation failed; existing changes were preserved."""


def default_cache() -> Path:
    """Return the platform's default source cache, without creating it."""
    if sys.platform == "win32":
        base = Path(
            os.environ.get("LOCALAPPDATA", None) or Path.home() / "AppData/Local"
        )
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", None) or Path.home() / ".cache")
    return base / "OneDragon-Helper" / "skill-source"


def _git(*args: str, cwd: Path | None = None) -> str:
    env = dict(os.environ)
    # Commands target the source tree, even when called from another Git process.
    for name in (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_COMMON_DIR",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_PREFIX",
    ):
        env.pop(name, None)
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GIT_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SourceCacheError(f"git {args[0]} failed: {exc}") from exc
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise SourceCacheError(f"git {args[0]} failed ({result.returncode}): {detail}")
    return result.stdout.strip()


def _source_path(path: Path) -> Path:
    path = Path(path).expanduser().resolve()
    if not path.is_dir():
        raise SourceCacheError(f"Source directory does not exist: {path}")
    missing = [name for name in REQUIRED_FILES if not (path / name).is_file()]
    if missing:
        raise SourceCacheError(
            f"Incomplete source at {path}: missing {', '.join(missing)}"
        )
    return path


def source_info(path: Path) -> dict:
    """Inspect a source tree; an explicit development tree need not be managed."""
    path = _source_path(path)
    result = {"path": str(path), "commit": None, "branch": None, "repository": None}
    if not (path / ".git").exists():
        return result
    errors = []
    for field, args in (
        ("commit", ("rev-parse", "HEAD")),
        ("branch", ("branch", "--show-current")),
        ("repository", ("remote", "get-url", "origin")),
    ):
        try:
            result[field] = _git(*args, cwd=path) or None
        except SourceCacheError as exc:
            errors.append(str(exc))
    if errors:
        result["git_errors"] = errors
    return result


def _managed_info(path: Path) -> dict:
    path = _source_path(path)
    top = Path(_git("rev-parse", "--show-toplevel", cwd=path)).resolve()
    if top != path:
        raise SourceCacheError(f"Cache must be the Git top-level directory: {path}")
    remote = _git("remote", "get-url", "--all", "origin", cwd=path)
    if remote != REPOSITORY:
        raise SourceCacheError(f"Cache origin must be {REPOSITORY}; found {remote!r}")
    if _git("status", "--porcelain", "--untracked-files=all", cwd=path):
        raise SourceCacheError(f"Cache has local changes; refusing to update: {path}")
    branch = _git("branch", "--show-current", cwd=path)
    if not branch:
        raise SourceCacheError(f"Cache has a detached HEAD; refusing to update: {path}")
    return {
        "path": str(path),
        "commit": _git("rev-parse", "HEAD", cwd=path),
        "branch": branch,
        "repository": remote,
    }


def _remove_temporary(path: Path, parent: Path, prefix: str) -> None:
    """Only remove the temporary clone directory created by this invocation."""
    if not path.exists():
        return
    if (
        path.is_symlink()
        or path.resolve().parent != parent
        or not path.name.startswith(prefix)
    ):
        raise SourceCacheError(f"Refusing to clean unexpected temporary path: {path}")

    def retry_readonly(function, name, exc_info):
        error = exc_info[1]
        if not isinstance(error, PermissionError) or function not in (
            os.unlink,
            os.remove,
            os.rmdir,
        ):
            raise error
        target = Path(name)
        if target.is_symlink() or not target.resolve().is_relative_to(path):
            raise SourceCacheError(
                f"Refusing to change unexpected temporary path: {name}"
            )
        target.chmod(stat.S_IREAD | stat.S_IWRITE)
        function(name)

    shutil.rmtree(path, onerror=retry_readonly)


def _default_branch(path: Path) -> str:
    response = _git("ls-remote", "--symref", "origin", "HEAD", cwd=path)
    branches = []
    for line in response.splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[0] == "ref:" and fields[2] == "HEAD":
            if fields[1].startswith("refs/heads/"):
                branches.append(fields[1].removeprefix("refs/heads/"))
    if len(branches) != 1 or not branches[0]:
        raise SourceCacheError("Cannot determine the remote HEAD default branch")
    return branches[0]


def ensure_source(cache: Path, refresh: bool = False) -> dict:
    """Read cached metadata, or explicitly clone/update the latest source."""
    cache = Path(cache).expanduser().resolve()
    if not refresh:
        if not cache.exists():
            raise SourceCacheError(f"Source is not cached at {cache}; run setup first.")
        return source_info(cache)
    if cache.exists():
        info = _managed_info(cache)
        default_branch = _default_branch(cache)
        if info["branch"] != default_branch:
            raise SourceCacheError(
                f"Cache branch {info['branch']!r} is not the remote default branch "
                f"{default_branch!r}; refusing to update"
            )
        _git("pull", "--ff-only", "origin", info["branch"], cwd=cache)
        return _managed_info(cache)

    cache.parent.mkdir(parents=True, exist_ok=True)
    prefix = f".{cache.name}-clone-"
    temporary = Path(tempfile.mkdtemp(prefix=prefix, dir=cache.parent)).resolve()
    try:
        _git("clone", "--depth", "1", REPOSITORY, str(temporary))
        info = _managed_info(temporary)
        if cache.exists():
            raise SourceCacheError(
                f"Cache appeared during download; refusing to replace: {cache}"
            )
        temporary.rename(cache)
        info["path"] = str(cache)
        return info
    finally:
        _remove_temporary(temporary, cache.parent, prefix)
