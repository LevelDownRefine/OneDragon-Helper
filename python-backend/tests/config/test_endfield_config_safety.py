"""终末地（ok-ef）config 安全性测试。

日常子任务拆分后，参数与开关分居两份文件：体力本落在 ``configs/DailyBattleTask.json``，
开关键仍在 ``configs/DailyTask.json``；周常「只买不卖」随地区建设迁到
``configs/RegionalBuildTask.json``。夹具即这三份脱敏后的真实配置。

跑 set_daily_task / prepare_start_day，对每次落盘做全量字段 diff，断言「只动了该动的字段，
其余（含注入的金丝雀字段）原封不动，也没串到另一份文件」。

允许改动字段集合严格来自实现：
- set_daily_task（EndfieldConfig）：数据侧仅写声明落点「体力本」，开关侧仅写「⭐刷体力」；
- prepare_start_day（EndfieldWeekly）：仅写 _task_name="只买不卖"（顶层 bool，反相写入）。
"""

import copy
import json
import os
import unittest
from unittest.mock import patch

from src.config.set_config import EndfieldConfig
from src.utils import utils_sub_config
from tests.support.config_diff import diff_paths

FIXTURES = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fixtures")

DAILY_TASK = "data/apps/ok-ef/working/configs/DailyTask.json"
DAILY_BATTLE_TASK = "data/apps/ok-ef/working/configs/DailyBattleTask.json"
REGIONAL_BUILD_TASK = "data/apps/ok-ef/working/configs/RegionalBuildTask.json"

# set_daily_task 只允许改动的 {文件: 字段路径集合}（= 数据落点 + 开关落点）
ALLOWED_DUNGEON = {
    DAILY_BATTLE_TASK: {"体力本"},
    DAILY_TASK: {"⭐刷体力"},
}
# prepare_start_day 只允许改动的 {文件: 字段路径集合}（严格按 EndfieldWeekly 的 config 与 key）
ALLOWED_WEEKLY = {REGIONAL_BUILD_TASK: {"只买不卖"}}


def load_fixture(name: str) -> dict:
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return json.load(f)


def inject_canaries(cfg: dict) -> None:
    """注入金丝雀字段，用于证明无关字段不会被改到。

    金丝雀只放在「落点之外的字段」上——写入只碰声明的那个字段，不会遍历到它们。
    """
    cfg["CANARY_EXTRA"] = "KEEP_ME"  # 顶层额外 key（模板无）
    cfg["账号列表"] = "CANARY_ACCOUNTS"  # 模板无的顶层字段
    cfg["体力刷完后继续刷取次数"] = 999  # 数值型金丝雀（与体力本同文件，模板无）
    cfg["优先送礼对象"] = "CANARY_FRIEND"  # 模板无


class TestEndfieldConfigSafety(unittest.TestCase):
    def setUp(self):
        self.seed = {
            DAILY_TASK: load_fixture("ok_ef_DailyTask.scrubbed.json"),
            DAILY_BATTLE_TASK: load_fixture("ok_ef_DailyBattleTask.scrubbed.json"),
            REGIONAL_BUILD_TASK: load_fixture("ok_ef_RegionalBuildTask.scrubbed.json"),
        }
        for config in self.seed.values():
            inject_canaries(config)
        self.store = copy.deepcopy(self.seed)

        def fake_load(script_name, rel_path=None, **kwargs):
            return copy.deepcopy(self.store[rel_path])

        def fake_save(script_name, rel_path, data):
            self.store[rel_path] = copy.deepcopy(data)

        # 落点读写都经 utils_sub_config 的两个原语。
        self._patches = [
            patch.object(utils_sub_config, "load_config", fake_load),
            patch.object(utils_sub_config, "save_config", fake_save),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        # 只停 setUp 自身 start 的 patch，不用全局 stopall（避免误停他方活跃 patch）。
        for p in self._patches:
            p.stop()

    def misalign(self) -> None:
        """把三个落点都拨到目标值的反面，逼迫后续写入真正落盘。"""
        self.store[DAILY_BATTLE_TASK]["体力本"] = "__WRONG__"
        self.store[DAILY_TASK]["⭐刷体力"] = False
        # 周常启用时目标为 false（反相写入），故拨成 true。
        self.store[REGIONAL_BUILD_TASK]["只买不卖"] = True

    def changed_fields(self, before: dict) -> dict[str, set[str]]:
        """各文件相对 ``before`` 实际改动的字段路径；无改动的文件不出现。"""
        changes = {}
        for path, config in before.items():
            fields = {p for p, _, _ in diff_paths(config, self.store[path])}
            if fields:
                changes[path] = fields
        return changes

    # ---- set_daily_task：只允许改 体力本（数据）与 ⭐刷体力（开关） ----
    def test_set_daily_task_only_touches_declared_fields(self):
        cfg = EndfieldConfig()
        self.misalign()
        before = copy.deepcopy(self.store)

        cfg.set_daily_task("每日任务", "能量淤积点", "枢纽区")

        self.assertEqual(
            self.changed_fields(before),
            ALLOWED_DUNGEON,
            "set_daily_task 只应写副本数据与开关两个落点，且不串文件",
        )
        # 正向校验：副本与开关都到达期望值
        self.assertEqual(self.store[DAILY_BATTLE_TASK]["体力本"], "枢纽区")
        self.assertTrue(self.store[DAILY_TASK]["⭐刷体力"])

    # ---- prepare_start_day：只允许改 只买不卖（反相） ----
    def test_set_weekly_only_touches_weekly_key(self):
        cfg = EndfieldConfig()
        self.misalign()
        before = copy.deepcopy(self.store)

        # 固定周常起始日判定，避免依赖「今天星期几」导致结果不确定
        with patch("src.config.weekly.is_weekly_start_reached", return_value=True):
            cfg.prepare_weekly_start_days({"卖出物资": 1})  # 周常启用 ⇒ 只买不卖=false

        self.assertEqual(
            self.changed_fields(before),
            ALLOWED_WEEKLY,
            "prepare_start_day 改到了不该改的字段或文件",
        )
        self.assertFalse(
            self.store[REGIONAL_BUILD_TASK]["只买不卖"], "周常启用时只买不卖应为 false"
        )

    # ---- 金丝雀：无关字段全程不被触碰 ----
    def test_canaries_untouched_through_full_flow(self):
        cfg = EndfieldConfig()
        self.misalign()  # 逼两条写入路径都真正落盘
        cfg.set_daily_task("每日任务", "能量淤积点", "枢纽区")
        with patch("src.config.weekly.is_weekly_start_reached", return_value=True):
            cfg.prepare_weekly_start_days({"卖出物资": 1})

        for path in (DAILY_TASK, DAILY_BATTLE_TASK, REGIONAL_BUILD_TASK):
            with self.subTest(config=path):
                config = self.store[path]
                self.assertEqual(config.get("CANARY_EXTRA"), "KEEP_ME")
                self.assertEqual(config.get("账号列表"), "CANARY_ACCOUNTS")
                self.assertEqual(config.get("体力刷完后继续刷取次数"), 999)
                self.assertEqual(config.get("优先送礼对象"), "CANARY_FRIEND")


if __name__ == "__main__":
    unittest.main(verbosity=2)
