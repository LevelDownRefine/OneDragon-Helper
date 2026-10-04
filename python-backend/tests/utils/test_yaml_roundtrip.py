"""YAML 往返读写回归测试。

验证游戏 config 的读写（src.utils.utils_io.YAML_INSTANCE 往返实例）：
- 保留注释（含行内注释）；
- 按 YAML 1.2 解析，使 04:00 这类时间保持字符串而非六十进制 float（240.0）；
- ruamel 把带引号的空串读成 str 子类时，不破坏 safe_update 的类型检查；
- 仍保留 bool / int 的语义区分（避免误写）。
"""

import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ruamel.yaml.error import YAMLError

from src.utils import utils_io
from src.utils.utils_dict import safe_update
from src.utils.utils_io import YAML_INSTANCE, load_data, save_data


class TestYamlRoundTrip(unittest.TestCase):
    SAMPLE = (
        "# 顶部注释\n"
        "name: hello\n"
        "scheduled_time: 04:00   # 行内注释\n"
        "empty: ''               # 带引号空串（ruamel 读成 str 子类）\n"
        "enabled: true\n"
    )

    def _round_trip(self, text: str):
        loaded = YAML_INSTANCE.load(text)
        buf = io.StringIO()
        YAML_INSTANCE.dump(loaded, buf)
        dumped = buf.getvalue()
        reloaded = YAML_INSTANCE.load(dumped)
        return loaded, dumped, reloaded

    def test_comment_preserved(self):
        _, dumped, _ = self._round_trip(self.SAMPLE)
        self.assertIn("# 顶部注释", dumped)
        self.assertIn("# 行内注释", dumped)

    def test_time_stays_string_not_float(self):
        loaded, dumped, reloaded = self._round_trip(self.SAMPLE)
        self.assertEqual(loaded["scheduled_time"], "04:00")
        self.assertNotIn("240.0", dumped)
        self.assertEqual(reloaded["scheduled_time"], "04:00")

    def test_round_trip_equal(self):
        loaded, _, reloaded = self._round_trip(self.SAMPLE)
        self.assertEqual(reloaded, loaded)

    def test_safe_update_tolerates_quoted_scalar_subclass(self):
        # 带引号的空串被 ruamel 读成 str 子类，safe_update 不应误判类型不一致。
        loaded, _, _ = self._round_trip(self.SAMPLE)
        changed = safe_update(loaded, "empty", "new", "test", assert_key_exists=True)
        self.assertTrue(changed)
        self.assertEqual(loaded["empty"], "new")

    def test_safe_update_bool_int_distinction_kept(self):
        loaded, _, _ = self._round_trip(self.SAMPLE)
        with self.assertRaises(AssertionError):
            safe_update(loaded, "enabled", 1, "test")  # bool 不能当 int 写


class TestYamlReadCache(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "config.yml"
        utils_io._parse_yaml.cache_clear()
        self.addCleanup(utils_io._parse_yaml.cache_clear)

    def test_unchanged_content_parsed_once_with_independent_nested_values(self):
        self.path.write_text("tasks:\n  - name: original\n", encoding="utf-8")
        with patch.object(YAML_INSTANCE, "load", wraps=YAML_INSTANCE.load) as parse:
            first = load_data(self.path, file_format="yaml", cached=True)
            first["tasks"][0]["name"] = "edited"
            second = load_data(self.path, file_format="yaml", cached=True)
            optional = load_data(self.path, file_format="yaml", cached=True)
        self.assertEqual(parse.call_count, 1)
        self.assertEqual(second, {"tasks": [{"name": "original"}]})
        self.assertEqual(optional, second)
        self.assertIsNot(optional["tasks"], second["tasks"])

    def test_same_size_and_timestamp_replacement_reads_new_content(self):
        self.path.write_text("value: before\n", encoding="utf-8")
        self.assertEqual(
            load_data(self.path, file_format="yaml", cached=True)["value"], "before"
        )
        stat = self.path.stat()
        replacement = self.path.with_suffix(".tmp")
        replacement.write_text("value: after!\n", encoding="utf-8")
        os.utime(replacement, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        replacement.replace(self.path)
        self.assertEqual(self.path.stat().st_size, stat.st_size)
        self.assertEqual(self.path.stat().st_mtime_ns, stat.st_mtime_ns)
        self.assertEqual(
            load_data(self.path, file_format="yaml", cached=True)["value"], "after!"
        )
        self.assertEqual(
            load_data(self.path, file_format="yaml", cached=True)["value"], "after!"
        )

    def test_deleted_cached_file_does_not_return_cached_data(self):
        self.path.write_text("value: present\n", encoding="utf-8")
        load_data(self.path, file_format="yaml", cached=True)
        self.path.unlink()
        with self.assertRaises(FileNotFoundError):
            load_data(self.path, file_format="yaml", cached=True)

    def test_invalid_external_edits_do_not_return_previous_content(self):
        self.path.write_text("value: valid\n", encoding="utf-8")
        load_data(self.path, file_format="yaml", cached=True)
        for text, expected in (("", None), ("[]", [])):
            with self.subTest(text=text):
                self.path.write_text(text, encoding="utf-8")
                self.assertEqual(
                    load_data(self.path, file_format="yaml", cached=True), expected
                )
        self.path.write_text("a: [", encoding="utf-8")
        with self.assertRaises(YAMLError):
            load_data(self.path, file_format="yaml", cached=True)

    def test_cached_round_trip_preserves_comments_quotes_and_time(self):
        self.path.write_text(TestYamlRoundTrip.SAMPLE, encoding="utf-8")
        load_data(self.path, file_format="yaml", cached=True)
        data = load_data(self.path, file_format="yaml", cached=True)
        data["name"] = "updated"
        save_data(self.path, data, file_format="yaml")
        saved = self.path.read_text(encoding="utf-8")
        self.assertIn("# 顶部注释", saved)
        self.assertIn("# 行内注释", saved)
        self.assertIn("empty: ''", saved)
        self.assertEqual(
            load_data(self.path, file_format="yaml", cached=True)["name"], "updated"
        )
        self.assertEqual(
            load_data(self.path, file_format="yaml", cached=True)["scheduled_time"],
            "04:00",
        )


class TestAtomicDump(unittest.TestCase):
    """save_data 原子写（tmp + os.replace）：写入中断不留截断损坏文件。"""

    def test_no_tmp_left_and_content_round_trips(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "atomic.yml")
        save_data(path, {"a": 1, "b": "文本"}, file_format="yaml")
        self.assertEqual(os.listdir(tmp.name), ["atomic.yml"])
        self.assertEqual(
            load_data(path, file_format="yaml", cached=True), {"a": 1, "b": "文本"}
        )


if __name__ == "__main__":
    unittest.main()
