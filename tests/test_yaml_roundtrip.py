"""YAML 往返读写回归测试。

验证游戏 config 的读写（src.utils.utils_yaml.YAML_INSTANCE 往返实例）：
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

from src.utils import utils_yaml
from src.utils.utils_dict import safe_update
from src.utils.utils_yaml import (
    YAML_INSTANCE,
    dump_yaml,
    load_yaml,
    load_yaml_optional,
)


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
        utils_yaml._parse_yaml.cache_clear()
        self.addCleanup(utils_yaml._parse_yaml.cache_clear)

    def test_unchanged_content_parsed_once_with_independent_nested_values(self):
        self.path.write_text("tasks:\n  - name: original\n", encoding="utf-8")
        with patch.object(YAML_INSTANCE, "load", wraps=YAML_INSTANCE.load) as parse:
            first = load_yaml(self.path)
            first["tasks"][0]["name"] = "edited"
            second = load_yaml(self.path)
            optional = load_yaml_optional(self.path)
        self.assertEqual(parse.call_count, 1)
        self.assertEqual(second, {"tasks": [{"name": "original"}]})
        self.assertEqual(optional, second)
        self.assertIsNot(optional["tasks"], second["tasks"])

    def test_same_size_and_timestamp_replacement_reads_new_content(self):
        self.path.write_text("value: before\n", encoding="utf-8")
        self.assertEqual(load_yaml(self.path)["value"], "before")
        stat = self.path.stat()
        replacement = self.path.with_suffix(".tmp")
        replacement.write_text("value: after!\n", encoding="utf-8")
        os.utime(replacement, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        replacement.replace(self.path)
        self.assertEqual(self.path.stat().st_size, stat.st_size)
        self.assertEqual(self.path.stat().st_mtime_ns, stat.st_mtime_ns)
        self.assertEqual(load_yaml(self.path)["value"], "after!")
        self.assertEqual(load_yaml_optional(self.path)["value"], "after!")

    def test_deleted_cached_file_keeps_required_and_optional_contracts(self):
        self.path.write_text("value: present\n", encoding="utf-8")
        load_yaml(self.path)
        self.path.unlink()
        with self.assertRaisesRegex(AssertionError, "配置文件缺失"):
            load_yaml(self.path)
        self.assertEqual(load_yaml_optional(self.path), {})

    def test_invalid_external_edits_do_not_return_previous_content(self):
        self.path.write_text("value: valid\n", encoding="utf-8")
        load_yaml(self.path)
        for text, error in (
            ("", AssertionError),
            ("[]", AssertionError),
            ("a: [", YAMLError),
        ):
            self.path.write_text(text, encoding="utf-8")
            for read in (load_yaml, load_yaml_optional):
                with (
                    self.subTest(text=text, read=read.__name__),
                    self.assertRaises(error),
                ):
                    read(self.path)

    def test_cached_round_trip_preserves_comments_quotes_and_time(self):
        self.path.write_text(TestYamlRoundTrip.SAMPLE, encoding="utf-8")
        load_yaml(self.path)
        data = load_yaml(self.path)
        data["name"] = "updated"
        dump_yaml(self.path, data)
        saved = self.path.read_text(encoding="utf-8")
        self.assertIn("# 顶部注释", saved)
        self.assertIn("# 行内注释", saved)
        self.assertIn("empty: ''", saved)
        self.assertEqual(load_yaml(self.path)["name"], "updated")
        self.assertEqual(load_yaml(self.path)["scheduled_time"], "04:00")


class TestAtomicDump(unittest.TestCase):
    """dump_yaml 原子写（tmp + os.replace）：写入中断不留截断损坏文件。"""

    def test_no_tmp_left_and_content_round_trips(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "atomic.yml")
        dump_yaml(path, {"a": 1, "b": "文本"})
        self.assertFalse(os.path.exists(path + ".tmp"))
        self.assertEqual(load_yaml(path), {"a": 1, "b": "文本"})


if __name__ == "__main__":
    unittest.main()
