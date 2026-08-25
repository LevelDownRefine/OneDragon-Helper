"""终末地（ok-ef / 粥）config 安全性测试。

用一份「脱敏后的真实 DailyTask.json」当夹具（tests/fixtures/ok_ef_DailyTask.scrubbed.json），
跑 init_config / set_dungeon / set_weekly，对每次落盘做全量字段 diff，
断言「只动了该动的字段，其余（含注入的金丝雀字段）原封不动」。

设计目的：验证 set_dungeon / set_weekly 不会把副本/周常以外的字段（刷体力、购物、
送礼、邮件、帝江号收菜等大量日常开关）误改，也不会波及无关的顶层设置。

允许改动字段集合严格来自 EndfieldConfig 实现：
- set_dungeon：仅写 _task_key="体力本"（顶层 str），无 sequence 通道；
- set_weekly：仅写 _weekly_task_name="只买不卖"（顶层 bool，反相写入）。
"""

import copy
import json
import os
import unittest
from unittest.mock import patch

from src.config import set_config as sc_mod
from src.config.set_config import EndfieldConfig

FIXTURE = os.path.join(
    os.path.dirname(__file__), "fixtures", "ok_ef_DailyTask.scrubbed.json"
)

# set_dungeon 只允许改动的字段路径集合（严格按 EndfieldConfig._task_key）
ALLOWED_DUNGEON = {"体力本"}
# set_weekly 只允许改动的字段路径集合（严格按 EndfieldConfig._weekly_task_name）
ALLOWED_WEEKLY = {"只买不卖"}


def load_fixture() -> dict:
    with open(FIXTURE, encoding="utf-8") as f:
        return json.load(f)


def diff_paths(before: dict, after: dict) -> list[tuple[str, object, object]]:
    """返回所有取值变化的 (json-path, before, after) 列表（点分路径）。"""
    diffs: list[tuple[str, object, object]] = []

    def walk(a, b, path):
        if a == b:
            return
        if isinstance(a, dict) and isinstance(b, dict):
            for k in set(a) | set(b):
                child = k if path == "" else f"{path}.{k}"
                walk(a.get(k, "<MISSING>"), b.get(k, "<MISSING>"), child)
        else:
            diffs.append((path, a, b))

    walk(before, after, "")
    return diffs


def inject_canaries(cfg: dict) -> None:
    """注入金丝雀字段，用于证明无关字段不会被改到。

    金丝雀只放在「模板之外的字段」上——reconcile 只遍历模板 key，绝不碰这些
    字段；若放在模板字段（如 ⭐收邮件）上，会改变其类型并触发 reconcile 的类型
    守卫，不再是合法金丝雀。
    """
    cfg["CANARY_EXTRA"] = "KEEP_ME"  # 顶层额外 key（模板无）
    cfg["账号列表"] = "CANARY_ACCOUNTS"  # 模板无的顶层字段
    cfg["体力刷完后继续刷取次数"] = 999  # 数值型金丝雀（模板无）
    cfg["优先送礼对象"] = "CANARY_FRIEND"  # 模板无


class TestEndfieldConfigSafety(unittest.TestCase):
    def setUp(self):
        self.seed = load_fixture()
        inject_canaries(self.seed)
        self.store = {
            "data/apps/ok-ef/working/configs/DailyTask.json": copy.deepcopy(self.seed)
        }
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

    # ---- init_config：绝不该改任何东西 ----
    def test_init_config_touches_nothing(self):
        """init_config 对一份已与模板对齐的真实 config 应零改动。"""
        EndfieldConfig()  # __init__ 内跑 _init_config
        diff = diff_paths(
            self.seed, self.store["data/apps/ok-ef/working/configs/DailyTask.json"]
        )
        self.assertEqual(diff, [], f"init_config 意外改动: {diff}")

    # ---- set_dungeon：只允许改 体力本 ----
    def test_set_dungeon_only_touches_task_key(self):
        cfg = EndfieldConfig()
        # 强制差异：先把 体力本 拨错，逼 set_dungeon 真正落盘
        forced = copy.deepcopy(
            self.store["data/apps/ok-ef/working/configs/DailyTask.json"]
        )
        forced["体力本"] = "__WRONG__"
        self.store["data/apps/ok-ef/working/configs/DailyTask.json"] = forced
        pre = copy.deepcopy(forced)

        cfg.set_dungeon("枢纽区")

        post = self.store["data/apps/ok-ef/working/configs/DailyTask.json"]
        diff = diff_paths(pre, post)
        paths = {p for p, _, _ in diff}
        self.assertEqual(
            paths,
            ALLOWED_DUNGEON,
            f"set_dungeon 改动与预期不符: 多了{paths - ALLOWED_DUNGEON} 少了{ALLOWED_DUNGEON - paths}",
        )
        # 正向校验：体力本被设为期望值
        self.assertEqual(post["体力本"], "枢纽区")

    # ---- set_weekly：只允许改 只买不卖（反相） ----
    def test_set_weekly_only_touches_weekly_key(self):
        cfg = EndfieldConfig()

        # 制造差异：把周常开关先拨到错误值，逼 set_weekly 真正落盘
        pre = copy.deepcopy(
            self.store["data/apps/ok-ef/working/configs/DailyTask.json"]
        )
        pre["只买不卖"] = True  # 与「周常启用」预期值相反，确保本次会落盘
        self.store["data/apps/ok-ef/working/configs/DailyTask.json"] = pre
        snapshot = copy.deepcopy(pre)

        # 固定周常起始日判定，避免依赖「今天星期几」导致结果不确定
        with patch("src.config.set_config.is_weekly_start_reached", return_value=True):
            cfg.set_weekly(1)  # 周常启用 ⇒ 只买不卖=false

        post = self.store["data/apps/ok-ef/working/configs/DailyTask.json"]
        diff = diff_paths(snapshot, post)
        paths = {p for p, _, _ in diff}
        self.assertEqual(
            paths,
            ALLOWED_WEEKLY,
            f"set_weekly 改到了不该改的字段: {paths - ALLOWED_WEEKLY}",
        )
        # 正向校验：周常启用 ⇒ 只买不卖=false（反相写入）
        self.assertFalse(post["只买不卖"], "周常启用时只买不卖应为 false")

    # ---- 金丝雀：无关字段全程不被触碰 ----
    def test_canaries_untouched_through_full_flow(self):
        cfg = EndfieldConfig()
        cfg.set_dungeon("枢纽区")
        cfg.set_weekly(1)

        post = self.store["data/apps/ok-ef/working/configs/DailyTask.json"]
        self.assertEqual(post.get("CANARY_EXTRA"), "KEEP_ME")
        self.assertEqual(post.get("账号列表"), "CANARY_ACCOUNTS")
        self.assertEqual(post.get("体力刷完后继续刷取次数"), 999)
        self.assertEqual(post.get("优先送礼对象"), "CANARY_FRIEND")


if __name__ == "__main__":
    unittest.main(verbosity=2)
