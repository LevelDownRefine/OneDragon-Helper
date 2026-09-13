"""Daily（声明规则层）与现有各脚本实现的行为等价性 —— 接线前的差分验证。

`Daily` 把「声明 → 落点 → 读写规则」从 7 个脚本子类的手写实现里抽出来。这组测试拿**现有
实现当独立裁判**：解析结果逐字段对比现有的落点读取器；写入 / 反读 / 开关逐次对比现有的公开
入口（`set_daily_task` / `_read_daily_task` / `set_daily_enabled` / `_read_daily_enabled`），
且都在同一份种子上跑、比全量 config。

这组测试是**临时脚手架**：接线后（ScriptConfig 改由 `Daily` 承担读写）上述入口会被删除，
等价性交给 `tests/golden/daily_baseline.json` 接管。
"""

import contextlib
import copy
import unittest
from unittest.mock import patch

from src.config import set_config as sc_mod
from src.config.daily import (
    AnomalyDaily,
    AnomalyHunterDaily,
    Daily,
    MaaDaily,
    NoopDaily,
)
from src.config.set_config import _CONFIGS
from src.config.task_config import get_daily_configs, load_daily_map
from tests.test_golden_daily import menu_of, resource_stub, seed_of

# 接线前「哪个日常用哪个类」的映射（接线后由 ScriptConfig 声明）；差分测试顺带验证它。
SPLIT_DAILIES = {
    "ok-nte": {"异象界域": AnomalyDaily, "追猎目标": AnomalyHunterDaily},
}
NO_OP_SCRIPTS = frozenset({"OneDragon-Launcher", "March7th-Launcher"})
STRUCTURED_SCRIPTS = frozenset({"MAA"})

ROUTINE_SEED = {
    "Routine Items": [
        {"id": "daily_anomaly", "enabled": False},
        {"id": "daily_anomaly_hunter", "enabled": True},
    ]
}


def daily_class(script_name: str, daily_name: str) -> type[Daily]:
    """该脚本该日常该用哪个类（接线前的映射）。"""
    if script_name in SPLIT_DAILIES:
        return SPLIT_DAILIES[script_name][daily_name]
    if script_name in STRUCTURED_SCRIPTS:
        return MaaDaily
    if script_name in NO_OP_SCRIPTS:
        return NoopDaily
    return Daily


def build(script_name: str) -> list[Daily]:
    """按声明造出该脚本的全部日常对象。"""
    return [
        daily_class(script_name, declaration["display_name"])(script_name, declaration)
        for declaration in load_daily_map()[script_name]
    ]


def cases(script_name: str) -> list[tuple[str, str, object]]:
    """该脚本菜单给出的全部 (日常, 一级项, 二级项) 组合（无二级时为 None）。"""
    return [
        (daily_name, task_name, sequence)
        for daily_name, tasks in menu_of(script_name).items()
        for task_name, sequences in tasks.items()
        for sequence in [seq[1] for seq in sequences] or [None]
    ]


@contextlib.contextmanager
def sandbox(script_name: str):
    """可控环境：种子 store + config I/O 与子脚本资源读取的替身；产出 (cfg, store)。

    与 golden 基线用同一套种子逻辑，故两边说的「同一份 config」是同一件事。
    """
    cfg = _CONFIGS[script_name]()
    with patch("src.config.daily_config.get_task_lists", side_effect=resource_stub):
        seed = seed_of(script_name, cfg)
    store = {cfg._config_rel_path: copy.deepcopy(seed)}
    routine_path = getattr(cfg, "_routine_config_rel_path", "")
    if routine_path:
        store[routine_path] = copy.deepcopy(ROUTINE_SEED)

    def load_config(_script_name, rel_path=None):
        return copy.deepcopy(store[rel_path or cfg._config_rel_path])

    def save_config(_script_name, rel_path, data):
        store[rel_path] = copy.deepcopy(data)

    with (
        patch.object(sc_mod, "load_config", load_config),
        patch.object(sc_mod, "save_config", save_config),
        patch("src.config.daily_config.get_task_lists", side_effect=resource_stub),
    ):
        yield cfg, store


class TestLandingPoints(unittest.TestCase):
    """声明解析出的落点必须与现有落点读取器逐字段一致。"""

    def test_matches_landing_reader(self):
        for script_name in sorted(_CONFIGS):
            expected = get_daily_configs(script_name)
            dailies = build(script_name)
            self.assertEqual(
                [daily.physical_name for daily in dailies],
                list(expected),
                f"{script_name} 的日常与落点读取器不一致",
            )
            for daily in dailies:
                want = expected[daily.physical_name]
                with self.subTest(script=script_name, daily=daily.name):
                    self.assertEqual(daily.task_field, want["task_field"])
                    self.assertEqual(daily.task_map, want["task_map"])
                    self.assertEqual(daily.option_fields, want["option_fields"])


class TestWrite(unittest.TestCase):
    """按声明落点写入的结果必须与现有实现一致（逐组合比全量 config）。"""

    def test_write_matches_current_implementation(self):
        for script_name in sorted(_CONFIGS):
            if script_name in NO_OP_SCRIPTS:
                continue
            by_name = {daily.name: daily for daily in build(script_name)}
            with sandbox(script_name) as (cfg, store):
                path = cfg._config_rel_path
                seed = copy.deepcopy(store[path])
                for daily_name, task_name, sequence in cases(script_name):
                    where = f"{script_name}/{daily_name}/{task_name}/{sequence}"
                    daily = by_name[daily_name]
                    store[path] = copy.deepcopy(seed)
                    daily.write(
                        daily.section(store[path]),
                        task_name,
                        sequence,
                        cfg.display_name,
                    )
                    mine = store[path]
                    store[path] = copy.deepcopy(seed)
                    cfg.set_daily_task(daily_name, task_name, sequence)
                    self.assertEqual(store[path], mine, f"写入结果不一致: {where}")


class TestRead(unittest.TestCase):
    """反读结果必须与现有实现一致（种子态与写入态各测一遍）。"""

    def test_read_matches_current_implementation(self):
        for script_name in sorted(_CONFIGS):
            by_name = {daily.name: daily for daily in build(script_name)}
            with sandbox(script_name) as (cfg, store):
                path = cfg._config_rel_path
                seed = copy.deepcopy(store[path])
                for daily_name, task_name, sequence in cases(script_name):
                    where = f"{script_name}/{daily_name}/{task_name}/{sequence}"
                    daily = by_name[daily_name]
                    store[path] = copy.deepcopy(seed)
                    section = daily.section(store[path])
                    self.assertEqual(
                        daily.read(section),
                        cfg._read_daily_task(daily_name),
                        f"种子态反读不一致: {where}",
                    )
                    if script_name in NO_OP_SCRIPTS:
                        continue
                    daily.write(section, task_name, sequence, cfg.display_name)
                    self.assertEqual(
                        daily.read(section),
                        cfg._read_daily_task(daily_name),
                        f"写入后反读不一致: {where}",
                    )


class TestEnabled(unittest.TestCase):
    """日常开关的读写必须与现有实现一致；无开关文件的脚本恒为 None。"""

    def test_read_enabled_matches_current_implementation(self):
        for script_name in sorted(_CONFIGS):
            with sandbox(script_name) as (cfg, _store):
                routine_path = getattr(cfg, "_routine_config_rel_path", "")
                routine = cfg._load(routine_path, allow_missing=True)
                for daily in build(script_name):
                    self.assertEqual(
                        daily.read_enabled(routine),
                        cfg._read_daily_enabled(daily.name),
                        f"开关反读不一致: {script_name}/{daily.name}",
                    )

    def test_set_enabled_matches_current_implementation(self):
        script_name = "ok-nte"
        by_name = {daily.name: daily for daily in build(script_name)}
        with sandbox(script_name) as (cfg, store):
            path = cfg._routine_config_rel_path
            seed = copy.deepcopy(store[path])
            for daily_name in by_name:
                mode_id = cfg._daily_physical_name(daily_name)
                for enabled in (True, False):
                    for seed_enabled in (True, False):
                        where = f"{daily_name}/{enabled}/{seed_enabled}"
                        store[path] = copy.deepcopy(seed)
                        next(
                            i
                            for i in store[path]["Routine Items"]
                            if i["id"] == mode_id
                        )["enabled"] = seed_enabled
                        mine_changed = by_name[daily_name].set_enabled(
                            store[path], enabled
                        )
                        mine = store[path]
                        store[path] = copy.deepcopy(seed)
                        next(
                            i
                            for i in store[path]["Routine Items"]
                            if i["id"] == mode_id
                        )["enabled"] = seed_enabled
                        before = copy.deepcopy(store[path])
                        cfg.set_daily_enabled(daily_name, enabled)
                        self.assertEqual(store[path], mine, f"开关写入不一致: {where}")
                        # 现有实现只在有变化时落盘，故「有变化」⇔「落盘发生了」
                        self.assertEqual(
                            mine_changed,
                            store[path] != before,
                            f"「有无变化」判定不一致: {where}",
                        )

    def test_read_enabled_is_none_without_routine_file(self):
        """无开关文件的脚本：读恒为 None，写报错（界面据此不提供「不启用」）。"""
        with sandbox("ok-ww") as (cfg, store):
            daily = build("ok-ww")[0]
            self.assertIsNone(daily.read_enabled(None))
            self.assertIsNone(cfg._read_daily_enabled(daily.name))
            with self.assertRaisesRegex(AssertionError, "未支持停用日常"):
                daily.set_enabled(store[cfg._config_rel_path], True)


class TestDeclarationErrors(unittest.TestCase):
    """声明本身的约束：必须有选项，且不能混用单层与两层。"""

    def test_empty_options_rejected(self):
        with self.assertRaisesRegex(AssertionError, "必须声明选项"):
            Daily("脚本", {"display_name": "日常", "options": {"values": []}})

    def test_mixed_layers_rejected(self):
        declaration = {
            "display_name": "日常",
            "options": {
                "values": [
                    {"display_name": "两层", "options": {"key": "k", "values": []}},
                    {"display_name": "单层"},
                ]
            },
        }
        with self.assertRaisesRegex(AssertionError, "不能混用单层与两层"):
            Daily("脚本", declaration)


if __name__ == "__main__":
    unittest.main()
