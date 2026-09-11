"""tools/sync_oknte_dungeons.py 离线回归测试（不联网，monkeypatch 抓取）。

覆盖：异象界域数字解析、追猎目标字符串解析、yml 读取、新增补齐（数字 + boss 名）。
"""

import os
import sys
import tempfile
import unittest

from src.utils.utils_yaml import load_yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import sync_oknte_dungeons as m

_ANOMALY = """
EXP_COIN_ID_RANGE = (1, 3)
ABILITY_ID_RANGE = (1, 5)
ARC_ID_RANGE = (1, 5)
CONSOLE_ID_RANGE = (1, 6)
"""

_HUNTER = """
TARGET_SOUND_KING = "音霸魔王"
TARGET_HEADLESS_RIDER = "无首铁驭"
TARGET_SERENITY = "塞润尼缇"
TARGET_BLACK_BOOK = "黑之书"
TARGET_SEA_PRISONER = "海囚"
TARGET_NEST_BIRD = "围巢鸟"
TARGET_SPOTTED_BUTTERFLY = "斑蝶"

HUNTER_TARGETS = [
    TARGET_SOUND_KING,
    TARGET_HEADLESS_RIDER,
    TARGET_SERENITY,
    TARGET_BLACK_BOOK,
    TARGET_SEA_PRISONER,
    TARGET_NEST_BIRD,
    TARGET_SPOTTED_BUTTERFLY,
]
"""


def _fake_fetch(url: str) -> str:
    if "AnomalyTask" in url:
        return _ANOMALY
    if "AnomalyHunter" in url:
        return _HUNTER
    raise AssertionError(url)


_YML = """ok-nte:
- display_name: 异象界域
  type: daily
  physical_name: daily_anomaly
  allow_disable: true
  options:
    key: 任务类型
    values:
    - display_name: 空幕
      options:
        key: 空幕序号
        values:
        - display_name: 光暗
          physical_name: 1
        - display_name: 魂相
          physical_name: 2
    - display_name: 异能升级材料
      options:
        values:
        - display_name: 鸟
          physical_name: 1
    - display_name: 弧盘突破材料
      options:
        values:
        - display_name: 苹果
          physical_name: 1
- display_name: 追猎目标
  type: daily
  physical_name: daily_anomaly_hunter
  allow_disable: true
  options:
    key: 追猎目标
    values:
    - display_name: 音霸魔王
      physical_name: 音霸魔王
    - display_name: 无首铁驭
      physical_name: 无首铁驭
- display_name: 另一个日常
  type: daily
  options:
    values:
    - display_name: 保留
"""


class SyncOknteTest(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_fetch = m._fetch_url
        self._orig_path = m._DUNGEON_PATH
        m._fetch_url = _fake_fetch
        with tempfile.NamedTemporaryFile(
            "w", suffix=".yml", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(_YML)
            self.tmp_path = tmp.name
        m._DUNGEON_PATH = self.tmp_path

    def tearDown(self) -> None:
        m._fetch_url = self._orig_fetch
        m._DUNGEON_PATH = self._orig_path
        os.unlink(self.tmp_path)

    def test_fetch_anomaly_totals(self) -> None:
        self.assertEqual(
            m._fetch_anomaly_totals(),
            {"空幕": 6, "异能升级材料": 5, "弧盘突破材料": 5},
        )

    def test_fetch_hunter_targets(self) -> None:
        self.assertEqual(
            m._fetch_hunter_targets(),
            ["音霸魔王", "无首铁驭", "塞润尼缇", "黑之书", "海囚", "围巢鸟", "斑蝶"],
        )

    def test_load_numeric_skips_non_int(self) -> None:
        numeric = m._load_numeric()
        assert "追猎目标" not in numeric
        self.assertEqual(numeric["空幕"], [1, 2])

    def test_load_hunter(self) -> None:
        self.assertEqual(m._load_hunter(), ["音霸魔王", "无首铁驭"])

    def test_apply_numeric_and_hunter(self) -> None:
        before = load_yaml(self.tmp_path)
        m._apply_numeric(m._fetch_anomaly_totals())
        m._apply_hunter(m._fetch_hunter_targets())
        data = load_yaml(self.tmp_path)
        self.assertEqual(data["ok-nte"][2], before["ok-nte"][2])
        for daily in data["ok-nte"][:2]:
            self.assertTrue(daily["allow_disable"])
        by_name = {d["display_name"]: d for d in data["ok-nte"][0]["options"]["values"]}
        self.assertEqual(data["ok-nte"][0]["physical_name"], "daily_anomaly")
        self.assertEqual(data["ok-nte"][0]["options"]["key"], "任务类型")
        self.assertEqual(by_name["空幕"]["options"]["key"], "空幕序号")
        self.assertEqual(data["ok-nte"][1]["physical_name"], "daily_anomaly_hunter")
        self.assertEqual(data["ok-nte"][1]["options"]["key"], "追猎目标")
        self.assertEqual(
            [s["physical_name"] for s in by_name["空幕"]["options"]["values"]],
            [1, 2, 3, 4, 5, 6],
        )
        self.assertEqual(
            [s["physical_name"] for s in by_name["异能升级材料"]["options"]["values"]],
            [1, 2, 3, 4, 5],
        )
        self.assertEqual(
            [s["physical_name"] for s in by_name["弧盘突破材料"]["options"]["values"]],
            [1, 2, 3, 4, 5],
        )
        self.assertEqual(
            [
                s.get("physical_name", s["display_name"])
                for s in data["ok-nte"][1]["options"]["values"]
            ],
            ["音霸魔王", "无首铁驭", "塞润尼缇", "黑之书", "海囚", "围巢鸟", "斑蝶"],
        )

    def test_main_no_diff_after_apply(self) -> None:
        assert m.main() == 1  # 首次检测有差异（数字缺 3-6、追猎缺 5 个）
        sys.argv = [sys.argv[0], "--apply"]
        assert m.main() == 0  # apply 后补齐并返回 0
        sys.argv = [sys.argv[0]]
        assert m.main() == 0  # 再次检测无差异


if __name__ == "__main__":
    unittest.main()
