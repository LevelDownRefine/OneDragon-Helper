"""tools/sync_oknte_dungeons.py 离线回归测试（不联网，monkeypatch 抓取）。

覆盖：异象界域数字解析、追猎目标字符串解析、yml 读取、新增补齐（数字 + boss 名）。
"""

import os
import sys
import tempfile
import unittest

from src.utils_yaml import SAFE_YAML as _yaml

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


_YML = """
ok-nte:
  dungeons:
  - name: 未选择
  - name: 空幕
    sequences:
    - {display: 光暗, value: 1}
    - {display: 魂相, value: 2}
  - name: 异能升级材料
    sequences:
    - {display: 鸟, value: 1}
  - name: 弧盘突破材料
    sequences:
    - {display: 苹果, value: 1}
  - name: 追猎目标
    sequences:
    - {display: 音霸魔王, value: 音霸魔王}
    - {display: 无首铁驭, value: 无首铁驭}
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
        m._apply_numeric(m._fetch_anomaly_totals())
        m._apply_hunter(m._fetch_hunter_targets())
        with open(self.tmp_path, encoding="utf-8") as f:
            data = _yaml.load(f)
        by_name = {d["name"]: d for d in data["ok-nte"]["dungeons"]}
        self.assertEqual(
            [s["value"] for s in by_name["空幕"]["sequences"]], [1, 2, 3, 4, 5, 6]
        )
        self.assertEqual(
            [s["value"] for s in by_name["异能升级材料"]["sequences"]], [1, 2, 3, 4, 5]
        )
        self.assertEqual(
            [s["value"] for s in by_name["弧盘突破材料"]["sequences"]], [1, 2, 3, 4, 5]
        )
        self.assertEqual(
            [s["value"] for s in by_name["追猎目标"]["sequences"]],
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
