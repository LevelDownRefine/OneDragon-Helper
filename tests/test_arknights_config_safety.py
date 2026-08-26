"""明日方舟（MAA / 粥）config 安全性测试。

用一份「脱敏后的真实 gui.new.json」当夹具（tests/fixtures/maa_gui.new.scrubbed.json），
跑 init_config / set_dungeon / set_weekly，对每次落盘做全量字段 diff，
断言「只动了该动的字段，其余（含注入的金丝雀字段）原封不动」。

设计目的：验证 index 定位（_task_map 来自模板）不会把 IsEnable / 药配置
写到错误的 TaskQueue 项，也不会波及 Gui / Toolbox / 其它无关字段。
"""

import copy
import json
import os
import unittest
from unittest.mock import patch

from src.config import set_config as sc_mod
from src.config.set_config import ArknightsConfig

FIXTURE = os.path.join(
    os.path.dirname(__file__), "fixtures", "maa_gui.new.scrubbed.json"
)

# TaskQueue 中 6 个 FightTask 的索引（与模板 MAA一条龙.json 一致）
FIGHT_IDX = (1, 2, 3, 4, 5, 6)  # 剿灭, 红票, 经验, 龙门币, 活动土, 土

# set_dungeon 只允许改动的字段路径集合
ALLOWED_DUNGEON = {f"Configurations.Default.TaskQueue[{i}].IsEnable" for i in FIGHT_IDX}
# set_weekly 只允许改动的字段路径集合
ALLOWED_WEEKLY = {
    f"Configurations.Default.TaskQueue[{i}].UseExpiringMedicine" for i in FIGHT_IDX
} | {f"Configurations.Default.TaskQueue[{i}].MedicineExpireDays" for i in FIGHT_IDX}


def load_fixture() -> dict:
    with open(FIXTURE, encoding="utf-8") as f:
        return json.load(f)


def diff_paths(before: dict, after: dict) -> list[tuple[str, object, object]]:
    """返回所有取值变化的 (json-path, before, after) 列表（点分/索引路径）。"""
    diffs: list[tuple[str, object, object]] = []

    def walk(a, b, path):
        if a == b:
            return
        if isinstance(a, dict) and isinstance(b, dict):
            for k in set(a) | set(b):
                child = k if path == "" else f"{path}.{k}"
                walk(a.get(k, "<MISSING>"), b.get(k, "<MISSING>"), child)
        elif isinstance(a, list) and isinstance(b, list):
            for i in range(max(len(a), len(b))):
                av = a[i] if i < len(a) else "<MISSING>"
                bv = b[i] if i < len(b) else "<MISSING>"
                walk(av, bv, f"{path}[{i}]")
        else:
            diffs.append((path, a, b))

    walk(before, after, "")
    return diffs


def inject_canaries(cfg: dict) -> None:
    """注入金丝雀字段，用于证明无关字段不会被改到。"""
    default = cfg["Configurations"]["Default"]
    default["CANARY_EXTRA"] = "KEEP_ME"  # 顶层额外 key
    gui = default["Gui"]
    gui["StartUpSettings"]["EmulatorPath"] = "CANARY_EMULATOR"  # 覆盖已脱敏路径
    gui["RuntimeSettings"]["PenguinId"] = "CANARY_PENGUIN"
    default["Toolbox"]["PeepTargetFps"] = 999
    for t in default["TaskQueue"]:
        if t.get("$type") == "FightTask":
            t["UseMedicine"] = True  # 药配置相关但绝不该被 set_dungeon/set_weekly 动
            t["CANARY_TASK"] = "X"


class TestArknightsConfigSafety(unittest.TestCase):
    def setUp(self):
        self.seed = load_fixture()
        inject_canaries(self.seed)
        self.store = {"config/gui.new.json": copy.deepcopy(self.seed)}
        self.saves: list[tuple[str, dict]] = []

        def fake_load(script_name, rel_path=None):
            return copy.deepcopy(self.store[rel_path])

        def fake_save(script_name, rel_path, data):
            self.store[rel_path] = copy.deepcopy(data)
            self.saves.append((rel_path, copy.deepcopy(data)))

        self._lp = patch.object(sc_mod, "load_config", fake_load)
        self._sp = patch.object(sc_mod, "save_config", fake_save)
        self._lp.start()
        self._sp.start()

    def tearDown(self):
        patch.stopall()

    # ---- 实例化：绝不该改任何东西（反读/只读入口依赖此不变量）----
    def test_instantiation_touches_nothing(self):
        """ArknightsConfig() 实例化不得触碰 config（反读路径依赖此不变量）。"""
        ArknightsConfig()
        diff = diff_paths(self.seed, self.store["config/gui.new.json"])
        self.assertEqual(diff, [], f"实例化意外改动: {diff}")

    # ---- set_dungeon：只允许改 FightTask 的 IsEnable ----
    def test_set_dungeon_only_touches_is_enable(self):
        cfg = ArknightsConfig()
        # 强制差异：先把所有 FightTask IsEnable 拨错，逼 set_dungeon 真正落盘
        forced = copy.deepcopy(self.store["config/gui.new.json"])
        for t in forced["Configurations"]["Default"]["TaskQueue"]:
            if t.get("$type") == "FightTask":
                t["IsEnable"] = False
        self.store["config/gui.new.json"] = forced
        pre = copy.deepcopy(forced)

        cfg.set_dungeon("土")

        post = self.store["config/gui.new.json"]
        diff = diff_paths(pre, post)
        paths = {p for p, _, _ in diff}
        # 期望恰好改 2 个：剿灭/土 → true（活动土未维护，不动）
        expected = {
            "Configurations.Default.TaskQueue[1].IsEnable",
            "Configurations.Default.TaskQueue[6].IsEnable",
        }
        self.assertEqual(
            paths,
            expected,
            f"set_dungeon 改动与预期不符: 多了{paths - expected} 少了{expected - paths}",
        )
        # 正向校验：开启项符合预期（剿灭/土）
        tq = post["Configurations"]["Default"]["TaskQueue"]
        by_name = {t["Name"]: t for t in tq if t.get("$type") == "FightTask"}
        self.assertTrue(by_name["剿灭"]["IsEnable"])
        self.assertTrue(by_name["土"]["IsEnable"])
        self.assertFalse(by_name["红票"]["IsEnable"])
        self.assertFalse(by_name["经验"]["IsEnable"])
        self.assertFalse(by_name["龙门币"]["IsEnable"])

    # ---- set_weekly：只允许改 6 个 FightTask 的 UseExpiringMedicine / MedicineExpireDays ----
    def test_set_weekly_only_touches_medicine_fields(self):
        cfg = ArknightsConfig()
        cfg.set_dungeon("土")  # 先把 IsEnable 设到日常态

        # 制造差异：把药配置先拨到错误值，逼 set_weekly 真正落盘
        pre = copy.deepcopy(self.store["config/gui.new.json"])
        for t in pre["Configurations"]["Default"]["TaskQueue"]:
            if t.get("$type") == "FightTask":
                t["UseExpiringMedicine"] = False
                t["MedicineExpireDays"] = 1
        self.store["config/gui.new.json"] = pre
        snapshot = copy.deepcopy(pre)

        cfg.set_weekly(1)  # 周几起=1 ⇒ MedicineExpireDays=7

        post = self.store["config/gui.new.json"]
        diff = diff_paths(snapshot, post)
        paths = {p for p, _, _ in diff}
        self.assertLessEqual(
            paths,
            ALLOWED_WEEKLY,
            f"set_weekly 改到了不该改的字段: {paths - ALLOWED_WEEKLY}",
        )
        # 正向校验：开启副本吃药、剿灭不吃、窗口=7
        tq = post["Configurations"]["Default"]["TaskQueue"]
        by_name = {t["Name"]: t for t in tq if t.get("$type") == "FightTask"}
        self.assertFalse(by_name["剿灭"]["UseExpiringMedicine"], "剿灭不应吃药")
        self.assertTrue(by_name["土"]["UseExpiringMedicine"])
        self.assertTrue(by_name["活动土"]["UseExpiringMedicine"])
        self.assertFalse(by_name["红票"]["UseExpiringMedicine"])
        self.assertEqual(by_name["土"]["MedicineExpireDays"], 7)
        self.assertEqual(by_name["剿灭"]["MedicineExpireDays"], 7)

    # ---- 金丝雀：无关字段全程不被触碰 ----
    def test_canaries_untouched_through_full_flow(self):
        cfg = ArknightsConfig()
        cfg.set_dungeon("土")
        cfg.set_weekly(1)

        post = self.store["config/gui.new.json"]
        default = post["Configurations"]["Default"]
        self.assertEqual(default.get("CANARY_EXTRA"), "KEEP_ME")
        self.assertEqual(
            default["Gui"]["StartUpSettings"]["EmulatorPath"], "CANARY_EMULATOR"
        )
        self.assertEqual(
            default["Gui"]["RuntimeSettings"]["PenguinId"], "CANARY_PENGUIN"
        )
        self.assertEqual(default["Toolbox"]["PeepTargetFps"], 999)
        for t in default["TaskQueue"]:
            if t.get("$type") == "FightTask":
                self.assertTrue(
                    t.get("UseMedicine"), "FightTask.UseMedicine 被意外改动"
                )
                self.assertEqual(t.get("CANARY_TASK"), "X")


if __name__ == "__main__":
    unittest.main(verbosity=2)
