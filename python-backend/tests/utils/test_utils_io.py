"""配置读写的缓存选择、外部改动、原子写与格式保留。"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.utils import utils_io as mod


class TestConfigFileIO(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        mod._parse_yaml.cache_clear()
        mod._parse_json.cache_clear()
        self.addCleanup(mod._parse_yaml.cache_clear)
        self.addCleanup(mod._parse_json.cache_clear)

    def test_cached_and_uncached_reads_are_explicit_and_isolated(self):
        for suffix, decoder, target in (
            ("json", json.loads, "src.utils.utils_io.json.loads"),
            ("yml", mod.YAML_INSTANCE.load, "src.utils.utils_io.YAML_INSTANCE.load"),
        ):
            with self.subTest(suffix=suffix):
                path = self.root / f"config.{suffix}"
                mod.save_data(path, {"tasks": [{"name": "original"}]})
                with patch(target, wraps=decoder) as parse:
                    first = mod.load_data(path, cached=True)
                    first["tasks"][0]["name"] = "changed"
                    self.assertEqual(
                        mod.load_data(path, cached=True),
                        {"tasks": [{"name": "original"}]},
                    )
                    self.assertEqual(parse.call_count, 1)
                    mod.load_data(path, cached=False)
                    mod.load_data(path, cached=False)
                    self.assertEqual(parse.call_count, 3)

    def test_external_replacement_with_same_size_and_timestamp_is_visible(self):
        for suffix in ("json", "yaml"):
            with self.subTest(suffix=suffix):
                path = self.root / f"config.{suffix}"
                mod.save_data(path, {"value": "before"})
                self.assertEqual(mod.load_data(path, cached=True)["value"], "before")
                stat = path.stat()
                mod.save_data(path, {"value": "after!"})
                os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
                self.assertEqual(path.stat().st_size, stat.st_size)
                self.assertEqual(path.stat().st_mtime_ns, stat.st_mtime_ns)
                self.assertEqual(mod.load_data(path, cached=True)["value"], "after!")
                path.unlink()
                with self.assertRaises(FileNotFoundError):
                    mod.load_data(path, cached=True)

    def test_yaml_comments_quotes_and_time_survive_round_trip(self):
        path = self.root / "config.yml"
        path.write_text("# 注释\ntime: '04:10'\nempty: ''\n", encoding="utf-8")
        data = mod.load_data(path)
        self.assertEqual(data["time"], "04:10")
        data["name"] = "更新"
        mod.save_data(path, data)
        self.assertIn("# 注释", path.read_text(encoding="utf-8"))
        self.assertIn("empty: ''", path.read_text(encoding="utf-8"))
        self.assertEqual(mod.load_data(path), data)

    def test_atomic_replace_failure_preserves_existing_file(self):
        for suffix in ("json", "yml"):
            with self.subTest(suffix=suffix):
                path = self.root / f"config.{suffix}"
                mod.save_data(path, {"value": "original"})
                original = path.read_bytes()
                with (
                    patch.object(mod.os, "replace", side_effect=OSError("failed")),
                    self.assertRaisesRegex(OSError, "failed"),
                ):
                    mod.save_data(path, {"value": "new"})
                self.assertEqual(path.read_bytes(), original)

    def test_serialization_failure_does_not_touch_target_or_temporary_file(self):
        path = self.root / "config.json"
        mod.save_data(path, {"value": "original"})
        original = path.read_bytes()
        with self.assertRaises(TypeError):
            mod.save_data(path, {"value": object()})
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse(Path(f"{path}.tmp").exists())

    def test_explicit_format_handles_staged_files_and_bom(self):
        path = self.root / "config.tmp"
        mod.save_data(path, {"value": "文本"}, file_format="json", encoding="utf-8-sig")
        self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf"))
        self.assertEqual(
            mod.load_data(path, file_format="json", encoding="utf-8-sig"),
            {"value": "文本"},
        )

    def test_invalid_content_does_not_fall_back_to_cached_data(self):
        path = self.root / "config.json"
        mod.save_data(path, {"value": "valid"})
        mod.load_data(path, cached=True)
        path.write_text("{", encoding="utf-8")
        with self.assertRaises(json.JSONDecodeError):
            mod.load_data(path, cached=True)

    def test_unsupported_format_is_rejected_before_writing(self):
        path = self.root / "config.unknown"
        with self.assertRaisesRegex(ValueError, "不支持的配置文件格式"):
            mod.save_data(path, {})
        self.assertFalse(path.exists())
        self.assertFalse(Path(f"{path}.tmp").exists())
