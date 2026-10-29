"""Offline source cache tests; Git downloads are mocked."""

import importlib.util
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SKILL_DIR = Path(
    os.environ.get(
        "ODH_SKILL_DIR",
        Path(__file__).resolve().parents[2] / ".agents/skills/onedragon-helper",
    )
)
MODULE_PATH = SKILL_DIR / "scripts/source_cache.py"
if (
    "ODH_SKILL_DIR" not in os.environ
    and Path(__file__).with_name("source_cache.py").is_file()
):
    MODULE_PATH = Path(__file__).with_name("source_cache.py")
SPEC = importlib.util.spec_from_file_location("skill_source_cache", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
source_cache = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(source_cache)


class SourceCacheTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.cache = self.root / "cache"
        self.calls = []
        self.commit = "old-commit"
        self.dirty = ""
        self.remote = source_cache.REPOSITORY
        self.branch = "main"
        self.remote_head = "ref: refs/heads/main\tHEAD\nlatest-commit\tHEAD"
        self.top = None

    def make_source(self, path, *, git=True):
        for name in source_cache.REQUIRED_FILES:
            target = path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("fixture", encoding="utf-8")
        if git:
            (path / ".git").mkdir()

    def fake_git(self, *args, cwd=None):
        self.calls.append((args, cwd))
        if args[0] == "clone":
            self.make_source(Path(args[-1]))
            self.commit = "latest-commit"
            return ""
        if args[0] == "pull":
            self.commit = "latest-commit"
            return ""
        if args == ("rev-parse", "--show-toplevel"):
            return str(self.top or cwd)
        if args == ("rev-parse", "HEAD"):
            return self.commit
        if args[0] == "remote":
            return self.remote
        if args[0] == "status":
            return self.dirty
        if args == ("branch", "--show-current"):
            return self.branch
        if args == ("ls-remote", "--symref", "origin", "HEAD"):
            return self.remote_head
        self.fail(f"Unexpected Git call: {args}")

    def test_first_setup_clones_and_returns_metadata(self):
        with patch.object(source_cache, "_git", side_effect=self.fake_git):
            info = source_cache.ensure_source(self.cache, refresh=True)
        self.assertEqual(info["path"], str(self.cache))
        self.assertEqual(info["commit"], "latest-commit")
        self.assertEqual(info["branch"], "main")
        self.assertEqual(info["repository"], source_cache.REPOSITORY)
        clone = self.calls[0][0]
        self.assertEqual(clone[:-1], ("clone", "--depth", "1", self.remote))
        self.assertEqual(list(self.root.iterdir()), [self.cache])

    def test_clean_cache_updates_without_reset(self):
        self.make_source(self.cache)
        with patch.object(source_cache, "_git", side_effect=self.fake_git):
            info = source_cache.ensure_source(self.cache, refresh=True)
        self.assertEqual(info["commit"], "latest-commit")
        self.assertIn((("pull", "--ff-only", "origin", "main"), self.cache), self.calls)
        self.assertFalse(any(args[0] == "reset" for args, _ in self.calls))

    def test_dirty_cache_is_preserved(self):
        self.make_source(self.cache)
        self.dirty = " M python-backend/src/utils/__init__.py"
        marker = self.cache / "keep.txt"
        marker.write_text("user content", encoding="utf-8")
        with (
            patch.object(source_cache, "_git", side_effect=self.fake_git),
            self.assertRaisesRegex(source_cache.SourceCacheError, "local changes"),
        ):
            source_cache.ensure_source(self.cache, refresh=True)
        self.assertEqual(marker.read_text(encoding="utf-8"), "user content")
        self.assertFalse(any(args[0] == "pull" for args, _ in self.calls))

    def test_switched_branch_and_unknown_remote_head_are_rejected(self):
        self.make_source(self.cache)
        for branch, remote_head, message in (
            ("feature", self.remote_head, "not the remote default branch"),
            ("main", "latest-commit\tHEAD", "Cannot determine"),
            ("main", "ref: refs/tags/v1\tHEAD", "Cannot determine"),
        ):
            with self.subTest(branch=branch, remote_head=remote_head):
                self.branch, self.remote_head = branch, remote_head
                with (
                    patch.object(source_cache, "_git", side_effect=self.fake_git),
                    self.assertRaisesRegex(source_cache.SourceCacheError, message),
                ):
                    source_cache.ensure_source(self.cache, refresh=True)
        self.assertFalse(
            any(args[0] in {"pull", "checkout", "switch"} for args, _ in self.calls)
        )

    def test_default_branch_can_have_slashes(self):
        self.make_source(self.cache)
        self.branch = "release/current"
        self.remote_head = "ref: refs/heads/release/current\tHEAD\nlatest-commit\tHEAD"
        with patch.object(source_cache, "_git", side_effect=self.fake_git):
            info = source_cache.ensure_source(self.cache, refresh=True)
        self.assertEqual(info["branch"], self.branch)
        self.assertIn(
            (("pull", "--ff-only", "origin", self.branch), self.cache), self.calls
        )

    def test_wrong_remote_and_nested_repository_are_rejected(self):
        self.make_source(self.cache)
        for remote, top, message in (
            ("https://example.com/other.git", None, "origin"),
            (source_cache.REPOSITORY, self.root, "top-level"),
        ):
            with self.subTest(message=message):
                self.remote, self.top = remote, top
                with (
                    patch.object(source_cache, "_git", side_effect=self.fake_git),
                    self.assertRaisesRegex(source_cache.SourceCacheError, message),
                ):
                    source_cache.ensure_source(self.cache, refresh=True)
        self.assertFalse(any(args[0] == "pull" for args, _ in self.calls))

    def test_failed_clone_cleans_only_its_temporary_directory(self):
        marker = self.root / "unrelated.txt"
        marker.write_text("keep", encoding="utf-8")
        with (
            patch.object(
                source_cache,
                "_git",
                side_effect=source_cache.SourceCacheError("download failed"),
            ),
            self.assertRaisesRegex(source_cache.SourceCacheError, "download failed"),
        ):
            source_cache.ensure_source(self.cache, refresh=True)
        self.assertEqual(list(self.root.iterdir()), [marker])

    def test_failed_pull_preserves_existing_cache(self):
        self.make_source(self.cache)

        def git(*args, cwd=None):
            if args[0] == "pull":
                raise source_cache.SourceCacheError("Not possible to fast-forward")
            return self.fake_git(*args, cwd=cwd)

        with (
            patch.object(source_cache, "_git", side_effect=git),
            self.assertRaisesRegex(source_cache.SourceCacheError, "fast-forward"),
        ):
            source_cache.ensure_source(self.cache, refresh=True)
        self.assertTrue((self.cache / source_cache.REQUIRED_FILES[0]).is_file())

    def test_temporary_clone_cleanup_accepts_readonly_pack_files(self):
        temporary = self.root / ".cache-clone-fixture"
        pack = temporary / ".git/objects/pack/fixture.pack"
        pack.parent.mkdir(parents=True)
        pack.write_bytes(b"fixture")
        pack.chmod(stat.S_IREAD)
        source_cache._remove_temporary(temporary, self.root, ".cache-clone-")
        self.assertFalse(temporary.exists())

    def test_detached_head_is_not_updated(self):
        self.make_source(self.cache)

        def git(*args, cwd=None):
            if args == ("branch", "--show-current"):
                return ""
            return self.fake_git(*args, cwd=cwd)

        with (
            patch.object(source_cache, "_git", side_effect=git),
            self.assertRaisesRegex(source_cache.SourceCacheError, "detached HEAD"),
        ):
            source_cache.ensure_source(self.cache, refresh=True)
        self.assertFalse(any(args[0] == "pull" for args, _ in self.calls))

    def test_read_only_source_needs_neither_git_nor_clean_remote(self):
        self.make_source(self.cache, git=False)
        with patch.object(source_cache, "_git") as git:
            info = source_cache.source_info(self.cache)
        git.assert_not_called()
        self.assertIsNone(info["commit"])
        (self.cache / ".git").mkdir()
        self.remote, self.dirty = "custom-origin", " M changed.py"
        with patch.object(source_cache, "_git", side_effect=self.fake_git):
            info = source_cache.ensure_source(self.cache)
        self.assertEqual(info["repository"], "custom-origin")
        self.assertFalse(any(args[0] in {"status", "pull"} for args, _ in self.calls))

    def test_missing_cache_and_incomplete_source(self):
        with self.assertRaisesRegex(source_cache.SourceCacheError, "setup first"):
            source_cache.ensure_source(self.cache)
        self.cache.mkdir()
        with self.assertRaisesRegex(source_cache.SourceCacheError, "missing"):
            source_cache.source_info(self.cache)

    def test_metadata_errors_are_reported(self):
        self.make_source(self.cache)
        with patch.object(
            source_cache,
            "_git",
            side_effect=source_cache.SourceCacheError("git missing"),
        ):
            info = source_cache.source_info(self.cache)
        self.assertIsNone(info["commit"])
        self.assertEqual(len(info["git_errors"]), 3)

    def test_platform_cache_locations(self):
        for platform, variable in (
            ("win32", "LOCALAPPDATA"),
            ("linux", "XDG_CACHE_HOME"),
        ):
            with (
                self.subTest(platform=platform),
                patch.object(source_cache.sys, "platform", platform),
                patch.dict(os.environ, {variable: str(self.root)}, clear=True),
            ):
                self.assertEqual(
                    source_cache.default_cache(),
                    self.root / "OneDragon-Helper/skill-source",
                )

    def test_git_ignores_caller_repository_but_preserves_connection_settings(self):
        selectors = dict.fromkeys(
            (
                "GIT_DIR",
                "GIT_WORK_TREE",
                "GIT_COMMON_DIR",
                "GIT_INDEX_FILE",
                "GIT_OBJECT_DIRECTORY",
                "GIT_ALTERNATE_OBJECT_DIRECTORIES",
                "GIT_PREFIX",
            ),
            "caller-repository",
        )
        connection = {
            "HTTPS_PROXY": "http://proxy.example:8080",
            "GIT_ASKPASS": "credential-helper",
            "GIT_CONFIG_GLOBAL": "custom-gitconfig",
        }
        inherited = {**selectors, **connection, "GIT_TERMINAL_PROMPT": "1"}
        result = subprocess.CompletedProcess(["git"], 0, "source-commit\n", "")
        with (
            patch.dict(os.environ, inherited),
            patch.object(source_cache.subprocess, "run", return_value=result) as run,
        ):
            self.assertEqual(source_cache._git("rev-parse", "HEAD"), "source-commit")
            child_env = run.call_args.kwargs["env"]
            self.assertTrue(selectors.keys().isdisjoint(child_env))
            for name, value in connection.items():
                self.assertEqual(child_env[name], value)
            self.assertEqual(child_env["GIT_TERMINAL_PROMPT"], "0")
            for name, value in inherited.items():
                self.assertEqual(os.environ[name], value)

    def test_git_errors_and_utf8_timeout_options(self):
        result = subprocess.CompletedProcess(["git"], 1, "", "中文错误")
        with (
            patch.object(source_cache.subprocess, "run", return_value=result) as run,
            self.assertRaisesRegex(source_cache.SourceCacheError, "中文错误"),
        ):
            source_cache._git("pull", "--ff-only", cwd=self.root)
        self.assertEqual(run.call_args.kwargs["encoding"], "utf-8")
        self.assertEqual(run.call_args.kwargs["timeout"], source_cache.GIT_TIMEOUT)
        self.assertEqual(run.call_args.kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")
        for error in (FileNotFoundError("git"), subprocess.TimeoutExpired("git", 60)):
            with (
                self.subTest(error=type(error).__name__),
                patch.object(source_cache.subprocess, "run", side_effect=error),
                self.assertRaises(source_cache.SourceCacheError),
            ):
                source_cache._git("clone", "source")


if __name__ == "__main__":
    unittest.main()
