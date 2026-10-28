"""Independent tests for the distributable log helpers."""

import codecs
import importlib.util
import os
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
MODULE_PATH = SKILL_DIR / "scripts/log_tools.py"
SPEC = importlib.util.spec_from_file_location("skill_log_tools", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
log_tools = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(log_tools)


class LogToolsTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()

    def write(self, name, content, encoding="utf-8"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding=encoding)
        return path

    def test_listing_deduplicates_and_reports_missing_and_limit(self):
        old = self.write("logs/2026-10-27.log", "old")
        newest = self.write("logs/2026-10-28.log", "new")
        self.write("logs/nested/2026-10-29.log", "not recursive")
        self.write("logs/launcher.log", "not matched")
        os.utime(old, (100, 100))
        os.utime(newest, (200, 200))
        pattern = str(self.root / "logs/[0-9]*.log")
        result = log_tools.list_log_files(
            {
                "realtime": pattern,
                "analysis": pattern,
                "absent": str(self.root / "absent/*.log"),
                "no_match": str(self.root / "logs/*.txt"),
                "undeclared": None,
            },
            limit=1,
        )
        self.assertEqual(result["total"], 2)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["omitted"], 1)
        self.assertEqual(result["files"][0]["path"], str(newest))
        self.assertEqual(result["files"][0]["kinds"], ["realtime", "analysis"])
        self.assertEqual(result["files"][0]["mtime"], 200)
        self.assertEqual(result["files"][0]["timezone"], "UTC")
        self.assertEqual(
            {row["reason"] for row in result["missing"]},
            {"not_declared", "directory_missing", "no_matches"},
        )
        self.assertEqual(result["errors"], [])

    def test_listing_surfaces_directory_errors(self):
        with patch.object(Path, "iterdir", side_effect=PermissionError("denied")):
            result = log_tools.list_log_files({"realtime": str(self.root / "*.log")})
        self.assertEqual(result["missing"], [])
        self.assertEqual(result["errors"][0]["error"], "PermissionError")

    def test_auto_encoding_and_line_numbers(self):
        text = "启动\n中文错误\n完成\n"
        for encoding in ("utf-8", "utf-8-sig", "utf-16", "gb18030"):
            with self.subTest(encoding=encoding):
                path = self.write(f"{encoding}.log", text, encoding)
                result = log_tools.read_log(path, start_line=2, lines=1)
                self.assertEqual(result["encoding"], encoding)
                self.assertEqual(result["lines"], [{"line": 2, "text": "中文错误"}])
                self.assertEqual(result["total_lines"], 3)
                self.assertEqual(result["truncation_reasons"], ["line_limit"])
        path = self.root / "utf-16-be.log"
        path.write_bytes(codecs.BOM_UTF16_BE + text.encode("utf-16-be"))
        self.assertEqual(log_tools.read_log(path)["lines"][0]["text"], "启动")

    def test_literal_context_merges_and_limits_matching_lines(self):
        path = self.write(
            "run.log", "before\n[ERR] one\n[ERR] two\nafter\nend\n[ERR] three\n"
        )
        result = log_tools.read_log(path, find="[ERR]", context=1, max_matches=2)
        self.assertEqual([row["line"] for row in result["lines"]], [1, 2, 3, 4])
        self.assertEqual(result["matches"], [2, 3])
        self.assertEqual(result["total_matches"], 3)
        self.assertEqual(result["truncation_reasons"], ["match_limit"])
        result = log_tools.read_log(path, start_line=3, find="[ERR]", context=1)
        self.assertEqual([row["line"] for row in result["lines"]], [3, 4, 5, 6])
        self.assertEqual(result["matches"], [3, 6])

    def test_character_limit_and_no_matches(self):
        path = self.write("long.log", "x" * (log_tools.MAX_OUTPUT_CHARS + 10))
        result = log_tools.read_log(path)
        self.assertEqual(len(result["lines"][0]["text"]), log_tools.MAX_OUTPUT_CHARS)
        self.assertTrue(result["lines"][0]["truncated"])
        self.assertEqual(result["truncation_reasons"], ["character_limit"])
        result = log_tools.read_log(path, find="absent")
        self.assertEqual(result["lines"], [])
        self.assertFalse(result["truncated"])
        result = log_tools.read_log(path, start_line=2)
        self.assertEqual(result["lines"], [])
        self.assertEqual(result["total_lines"], 1)

    def test_input_boundaries_and_missing_files(self):
        path = self.write("small.log", "one\n")
        for values in (
            {"start_line": 0},
            {"start_line": True},
            {"lines": 0},
            {"lines": log_tools.MAX_OUTPUT_LINES + 1},
            {"context": -1},
            {"max_matches": 0},
            {"find": ""},
            {"find": "two\nlines"},
            {"encoding": "not-an-encoding"},
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                log_tools.read_log(path, **values)
        with self.assertRaises(FileNotFoundError):
            log_tools.read_log(self.root / "absent.log")
        for limit in (0, True, log_tools.MAX_FILES + 1):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                log_tools.list_log_files({}, limit=limit)


if __name__ == "__main__":
    unittest.main()
