"""配置读写的缓存选择、外部改动、原子写与格式保留。"""

import json
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
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
                mod.save_data(
                    path,
                    {"tasks": [{"name": "original"}]},
                    file_format="json" if path.suffix == ".json" else "yaml",
                )
                with patch(target, wraps=decoder) as parse:
                    first = mod.load_data(
                        path,
                        cached=True,
                        file_format="json" if path.suffix == ".json" else "yaml",
                    )
                    first["tasks"][0]["name"] = "changed"
                    self.assertEqual(
                        mod.load_data(
                            path,
                            cached=True,
                            file_format="json" if path.suffix == ".json" else "yaml",
                        ),
                        {"tasks": [{"name": "original"}]},
                    )
                    self.assertEqual(parse.call_count, 1)
                    mod.load_data(
                        path,
                        cached=False,
                        file_format="json" if path.suffix == ".json" else "yaml",
                    )
                    mod.load_data(
                        path,
                        cached=False,
                        file_format="json" if path.suffix == ".json" else "yaml",
                    )
                    self.assertEqual(parse.call_count, 3)

    def test_external_replacement_with_same_size_and_timestamp_is_visible(self):
        for suffix in ("json", "yaml"):
            with self.subTest(suffix=suffix):
                path = self.root / f"config.{suffix}"
                mod.save_data(
                    path,
                    {"value": "before"},
                    file_format="json" if path.suffix == ".json" else "yaml",
                )
                self.assertEqual(
                    mod.load_data(
                        path,
                        cached=True,
                        file_format="json" if path.suffix == ".json" else "yaml",
                    )["value"],
                    "before",
                )
                stat = path.stat()
                mod.save_data(
                    path,
                    {"value": "after!"},
                    file_format="json" if path.suffix == ".json" else "yaml",
                )
                os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
                self.assertEqual(path.stat().st_size, stat.st_size)
                self.assertEqual(path.stat().st_mtime_ns, stat.st_mtime_ns)
                self.assertEqual(
                    mod.load_data(
                        path,
                        cached=True,
                        file_format="json" if path.suffix == ".json" else "yaml",
                    )["value"],
                    "after!",
                )
                path.unlink()
                with self.assertRaises(FileNotFoundError):
                    mod.load_data(
                        path,
                        cached=True,
                        file_format="json" if path.suffix == ".json" else "yaml",
                    )

    def test_yaml_comments_quotes_and_time_survive_round_trip(self):
        path = self.root / "config.yml"
        path.write_text("# 注释\ntime: '04:10'\nempty: ''\n", encoding="utf-8")
        data = mod.load_data(
            path, file_format="json" if path.suffix == ".json" else "yaml"
        )
        self.assertEqual(data["time"], "04:10")
        data["name"] = "更新"
        mod.save_data(
            path, data, file_format="json" if path.suffix == ".json" else "yaml"
        )
        self.assertIn("# 注释", path.read_text(encoding="utf-8"))
        self.assertIn("empty: ''", path.read_text(encoding="utf-8"))
        self.assertEqual(
            mod.load_data(
                path, file_format="json" if path.suffix == ".json" else "yaml"
            ),
            data,
        )

    def test_atomic_replace_failure_preserves_existing_file(self):
        for suffix in ("json", "yml"):
            with self.subTest(suffix=suffix):
                path = self.root / f"config.{suffix}"
                mod.save_data(
                    path,
                    {"value": "original"},
                    file_format="json" if path.suffix == ".json" else "yaml",
                )
                original = path.read_bytes()
                with (
                    patch.object(mod.os, "replace", side_effect=OSError("failed")),
                    self.assertRaisesRegex(OSError, "failed"),
                ):
                    mod.save_data(
                        path,
                        {"value": "new"},
                        file_format="json" if path.suffix == ".json" else "yaml",
                    )
                self.assertEqual(path.read_bytes(), original)
                self.assertFalse(list(self.root.glob("*.tmp")))

    def test_failed_write_closes_and_removes_temporary_file(self):
        """写入中断时保留目标，关闭文件后移除临时文件。"""
        path = self.root / "config.json"
        mod.save_data(path, {"value": "original"}, "json")
        original = path.read_bytes()
        temporary = self.enterContext(
            tempfile.NamedTemporaryFile(mode="w", dir=self.root, delete=False)
        )
        with (
            patch.object(mod.tempfile, "NamedTemporaryFile", return_value=temporary),
            patch.object(temporary, "write", side_effect=OSError("write failed")),
            self.assertRaisesRegex(OSError, "write failed"),
        ):
            mod.save_data(path, {"value": "new"}, "json")
        self.assertTrue(temporary.file.closed)
        self.assertFalse(Path(temporary.name).exists())
        self.assertEqual(path.read_bytes(), original)

    def test_overlapping_saves_use_independent_temporary_files(self):
        """强制两次保存同时到达替换阶段，各自提交完整且独立的内容。"""
        path = self.root / "config.json"
        barrier = threading.Barrier(2)
        replacement_lock = threading.Lock()
        temporary_paths = []
        contents = []
        replace = os.replace
        values = [{"value": "first"}, {"value": "second"}]

        def replace_together(source, target):
            temporary_paths.append(Path(source))
            contents.append(mod.load_data(source, "json"))
            barrier.wait(timeout=5)
            # 两个写入已重叠；串行替换避免 Windows 同时替换目标的共享冲突。
            with replacement_lock:
                replace(source, target)

        with (
            patch.object(mod.os, "replace", side_effect=replace_together),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            futures = [
                executor.submit(mod.save_data, path, value, "json") for value in values
            ]
            for future in futures:
                future.result(timeout=10)
        self.assertEqual(len(set(temporary_paths)), 2)
        self.assertTrue(
            all(temporary.parent == path.parent for temporary in temporary_paths)
        )
        self.assertCountEqual(contents, values)
        self.assertIn(mod.load_data(path, "json"), values)
        self.assertFalse(list(self.root.glob("*.tmp")))

    def test_serialization_failure_does_not_touch_target_or_temporary_file(self):
        path = self.root / "config.json"
        mod.save_data(
            path,
            {"value": "original"},
            file_format="json" if path.suffix == ".json" else "yaml",
        )
        original = path.read_bytes()
        with self.assertRaises(TypeError):
            mod.save_data(
                path,
                {"value": object()},
                file_format="json" if path.suffix == ".json" else "yaml",
            )
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse(Path(f"{path}.tmp").exists())

    def test_explicit_format_handles_staged_files_and_bom(self):
        path = self.root / "config.tmp"
        mod.save_data(path, {"value": "文本"}, "json", 4, "utf-8-sig")
        self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf"))
        self.assertEqual(
            mod.load_data(path, "json", True, "utf-8-sig"),
            {"value": "文本"},
        )
        text = mod.dump_data_str({"value": "文本"}, "json", 2)
        self.assertEqual(mod.parse_data(text, "json", True), {"value": "文本"})

    def test_format_parameter_controls_codec_independently_of_extension(self):
        path = self.root / "config.json"
        mod.save_data(path, {"value": "文本"}, file_format="yaml")
        self.assertEqual(mod.load_data(path, file_format="yaml"), {"value": "文本"})
        with self.assertRaises(json.JSONDecodeError):
            mod.load_data(path, file_format="json")

    def test_invalid_content_does_not_fall_back_to_cached_data(self):
        path = self.root / "config.json"
        mod.save_data(
            path,
            {"value": "valid"},
            file_format="json" if path.suffix == ".json" else "yaml",
        )
        mod.load_data(
            path, cached=True, file_format="json" if path.suffix == ".json" else "yaml"
        )
        path.write_text("{", encoding="utf-8")
        with self.assertRaises(json.JSONDecodeError):
            mod.load_data(
                path,
                cached=True,
                file_format="json" if path.suffix == ".json" else "yaml",
            )

    def test_invalid_format_is_rejected_before_writing(self):
        path = self.root / "config.unknown"
        with self.assertRaisesRegex(AssertionError, "未知文件格式"):
            mod.save_data(path, {}, file_format="unknown")
        self.assertFalse(path.exists())
        self.assertFalse(Path(f"{path}.tmp").exists())
