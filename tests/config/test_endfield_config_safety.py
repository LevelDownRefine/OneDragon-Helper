"""终末地（ok-ef / 粥）config 安全性测试。

用一份「脱敏后的真实 DailyTask.json」当夹具（tests/fixtures/ok_ef_DailyTask.scrubbed.json），
跑 init_config / set_daily_task / prepare_start_day，对每次落盘做全量字段 diff，
断言「只动了该动的字段，其余（含注入的金丝雀字段）原封不动」。

设计目的：验证 set_daily_task / prepare_start_day 不会把副本/周常以外的字段（刷体力、购物、
送礼、邮件、帝江号收菜等大量日常开关）误改，也不会波及无关的顶层设置。

允许改动字段集合严格来自实现：
- set_daily_task（EndfieldConfig）：仅写声明落点「体力本」（顶层 str，二级覆盖一级）；
- prepare_start_day（EndfieldWeekly）：仅写 _task_name="只买不卖"（顶层 bool，反相写入）。
"""

import copy
import json
import os
import unittest
from unittest.mock import patch

from src.config import set_config as sc_mod
from src.config.set_config import EndfieldConfig
from src.config.weekly import weeklies_of
from src.utils import utils_sub_config
from tests.support.config_diff import diff_paths


def _ef_weekly():
    """终末地的周常对象（卖出物资）。"""
    return weeklies_of("ok-ef")[0]


FIXTURE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "fixtures",
    "ok_ef_DailyTask.scrubbed.json",
)

# set_daily_task 只允许改动的字段路径集合（= 声明落点的 task_field）
ALLOWED_DUNGEON = {"体力本"}
# prepare_start_day 只允许改动的字段路径集合（严格按 EndfieldWeekly._task_name）
ALLOWED_WEEKLY = {"只买不卖"}


def load_fixture() -> dict:
    with open(FIXTURE, encoding="utf-8") as f:
        return json.load(f)


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

        def fake_load(script_name, rel_path=None, **kwargs):
            return copy.deepcopy(self.store[rel_path])

        def fake_save(script_name, rel_path, data):
            self.store[rel_path] = copy.deepcopy(data)
            self.saves.append((rel_path, copy.deepcopy(data)))

        # 落点读写最终都经 utils_sub_config 的两个原语；set_config 的 _init_config
        # 另持模块内绑定，故一并注册。
        self._patches = [
            patch.object(utils_sub_config, "load_config", fake_load),
            patch.object(utils_sub_config, "save_config", fake_save),
            patch.object(sc_mod, "load_config", fake_load),
            patch.object(sc_mod, "save_config", fake_save),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        # 只停 setUp 自身 start 的 patch，不用全局 stopall（避免误停他方活跃 patch）。
        for p in self._patches:
            p.stop()

    # ---- _init_config：绝不该改任何东西（不再由 __init__ 自动触发）----
    def test_init_config_touches_nothing(self):
        """_init_config 对一份已与模板对齐的真实 config 应零改动（需显式调用）。"""
        cfg = EndfieldConfig()
        cfg._init_config()
        diff = diff_paths(
            self.seed, self.store["data/apps/ok-ef/working/configs/DailyTask.json"]
        )
        self.assertEqual(diff, [], f"init_config 意外改动: {diff}")

    # ---- set_daily_task：只允许改 体力本 ----
    def test_set_daily_task_only_touches_declared_field(self):
        cfg = EndfieldConfig()
        # 强制差异：先把 体力本 拨错，逼 set_daily_task 真正落盘
        forced = copy.deepcopy(
            self.store["data/apps/ok-ef/working/configs/DailyTask.json"]
        )
        forced["体力本"] = "__WRONG__"
        self.store["data/apps/ok-ef/working/configs/DailyTask.json"] = forced
        pre = copy.deepcopy(forced)

        cfg.set_daily_task("每日任务", "能量淤积点", "枢纽区")

        post = self.store["data/apps/ok-ef/working/configs/DailyTask.json"]
        diff = diff_paths(pre, post)
        paths = {p for p, _, _ in diff}
        self.assertEqual(
            paths,
            ALLOWED_DUNGEON,
            f"set_daily_task 改动与预期不符: 多了{paths - ALLOWED_DUNGEON} 少了{ALLOWED_DUNGEON - paths}",
        )
        # 正向校验：体力本被设为期望值
        self.assertEqual(post["体力本"], "枢纽区")

    # ---- prepare_start_day：只允许改 只买不卖（反相） ----
    def test_set_weekly_only_touches_weekly_key(self):
        # 制造差异：把周常开关先拨到错误值，逼 prepare_start_day 真正落盘
        pre = copy.deepcopy(
            self.store["data/apps/ok-ef/working/configs/DailyTask.json"]
        )
        pre["只买不卖"] = True  # 与「周常启用」预期值相反，确保本次会落盘
        self.store["data/apps/ok-ef/working/configs/DailyTask.json"] = pre
        snapshot = copy.deepcopy(pre)

        # 固定周常起始日判定，避免依赖「今天星期几」导致结果不确定
        with patch("src.config.weekly.is_weekly_start_reached", return_value=True):
            _ef_weekly().prepare_start_day(1)  # 周常启用 ⇒ 只买不卖=false

        post = self.store["data/apps/ok-ef/working/configs/DailyTask.json"]
        diff = diff_paths(snapshot, post)
        paths = {p for p, _, _ in diff}
        self.assertEqual(
            paths,
            ALLOWED_WEEKLY,
            f"prepare_start_day 改到了不该改的字段: {paths - ALLOWED_WEEKLY}",
        )
        # 正向校验：周常启用 ⇒ 只买不卖=false（反相写入）
        self.assertFalse(post["只买不卖"], "周常启用时只买不卖应为 false")

    # ---- 金丝雀：无关字段全程不被触碰 ----
    def test_canaries_untouched_through_full_flow(self):
        cfg = EndfieldConfig()
        cfg.set_daily_task("每日任务", "能量淤积点", "枢纽区")
        _ef_weekly().prepare_start_day(1)

        post = self.store["data/apps/ok-ef/working/configs/DailyTask.json"]
        self.assertEqual(post.get("CANARY_EXTRA"), "KEEP_ME")
        self.assertEqual(post.get("账号列表"), "CANARY_ACCOUNTS")
        self.assertEqual(post.get("体力刷完后继续刷取次数"), 999)
        self.assertEqual(post.get("优先送礼对象"), "CANARY_FRIEND")


if __name__ == "__main__":
    unittest.main(verbosity=2)
