"""游戏 config 往返保真测试（以「类似崩铁 M7A」的夹具驱动真实读写路径）。

验证 src.utils_sub_config 的 load_config / save_config：
- 读后写回，解析结果与原 config 数据等价（reloaded == original）；
- 注释（含行内注释）保留；
- 04:00 / 4:00 这类时间保持字符串，绝不变 240.0 浮点污染；
- 模拟 StarRailConfig.set_weekly 的真实写入（currencywars_enable / echo_of_war_start_day_of_week）
  后，仍保真、注释不丢。

夹具：tests/fixtures/starrail_config.yaml（不依赖真实游戏目录，可移植）。
"""

import os
import tempfile
import unittest
from unittest.mock import patch

from src import utils_sub_config

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "starrail_config.yaml")


class TestGameConfigRoundTrip(unittest.TestCase):
    def _load_fixture(self):
        """经由真实 load_config 读夹具（mock 路径解析，避免依赖游戏目录）。"""
        with patch.object(
            utils_sub_config, "get_sub_config_path", return_value=FIXTURE
        ):
            return utils_sub_config.load_config("starrail-test", "config.yaml")

    def _save_to_temp(self, data):
        with tempfile.NamedTemporaryFile(
            "w", suffix=".yaml", encoding="utf-8", delete=False
        ) as tmp:
            tmp_path = tmp.name
        with patch.object(
            utils_sub_config, "get_sub_config_path", return_value=tmp_path
        ):
            utils_sub_config.save_config("starrail-test", "config.yaml", data)
        return tmp_path

    def test_loaded_values_match_original(self):
        """读到的关键值与夹具一致（时间保字符串、bool/int 未被 yaml 1.1 吞掉）。"""
        cfg = self._load_fixture()
        self.assertEqual(cfg["scheduled_time"], "4:00")
        self.assertEqual(cfg["scheduled_run_time"], "04:00")
        self.assertIs(type(cfg["currencywars_enable"]), bool)
        self.assertTrue(cfg["currencywars_enable"])
        self.assertIs(type(cfg["echo_of_war_start_day_of_week"]), int)
        self.assertEqual(cfg["echo_of_war_start_day_of_week"], 1)
        self.assertEqual(cfg["instance_names"]["历战余响"], "无")
        self.assertEqual(cfg["python_exe_path"], "")
        self.assertEqual(cfg["notify_list"], ["bark", "mail"])

    def test_noop_round_trip_equal_and_comments_kept(self):
        """读后原样写回：解析结果等价 + 注释保留 + 04:00 不变 float。"""
        cfg = self._load_fixture()
        tmp_path = self._save_to_temp(cfg)

        with patch.object(
            utils_sub_config, "get_sub_config_path", return_value=tmp_path
        ):
            reloaded = utils_sub_config.load_config("starrail-test", "config.yaml")

        self.assertEqual(reloaded, cfg)  # 数据等价（reloaded == original）

        with open(tmp_path, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("# 语言设置", text)
        self.assertIn("# 货币战争总开关", text)
        self.assertIn("scheduled_time: 4:00", text)
        self.assertIn("scheduled_run_time: 04:00", text)
        self.assertNotIn("240.0", text)  # 关键：六十进制污染绝不可出现

    def test_starrail_weekly_write_round_trip(self):
        """模拟 StarRailConfig.set_weekly 的真实写入后，仍保真且注释不丢。"""
        cfg = self._load_fixture()
        # 与 set_config.py 中 StarRailConfig.set_weekly 的落盘一致
        cfg["currencywars_enable"] = True
        cfg["echo_of_war_start_day_of_week"] = 3

        tmp_path = self._save_to_temp(cfg)

        with patch.object(
            utils_sub_config, "get_sub_config_path", return_value=tmp_path
        ):
            reloaded = utils_sub_config.load_config("starrail-test", "config.yaml")

        self.assertEqual(reloaded, cfg)
        self.assertTrue(reloaded["currencywars_enable"])
        self.assertEqual(reloaded["echo_of_war_start_day_of_week"], 3)
        self.assertEqual(reloaded["instance_names"]["历战余响"], "无")  # 副本选型不被动

        with open(tmp_path, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("# 语言设置", text)  # 注释仍保留
        self.assertIn("scheduled_run_time: 04:00", text)
        self.assertNotIn("240.0", text)


if __name__ == "__main__":
    unittest.main()
