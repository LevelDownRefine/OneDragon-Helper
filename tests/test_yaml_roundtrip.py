"""YAML 往返读写回归测试。

验证游戏 config 的读写（src.utils.utils_yaml.YAML_INSTANCE 往返实例）：
- 保留注释（含行内注释）；
- 按 YAML 1.2 解析，使 04:00 这类时间保持字符串而非六十进制 float（240.0）；
- ruamel 把带引号的空串读成 str 子类时，不破坏 safe_update 的类型检查；
- 仍保留 bool / int 的语义区分（避免误写）。
"""

import io
import unittest

from src.config.set_config import safe_update
from src.utils.utils_yaml import YAML_INSTANCE


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


if __name__ == "__main__":
    unittest.main()
