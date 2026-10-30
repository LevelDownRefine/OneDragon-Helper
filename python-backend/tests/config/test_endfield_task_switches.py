"""终末地新版日常总开关：用仓库声明在隔离配置中读写。"""

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from src.config.native_task_switch import NativeTaskSwitch, load_native_task_switch_map
from src.config.set_config import EndfieldConfig
from src.config.task.task_options import load_declarations

_GROUPS = {
    "帝江号任务": ["送礼", "帝江号整理", "帝江号收菜"],
    "其他任务": [
        "收邮件",
        "清理基质",
        "转交运送委托",
        "地区建设",
        "造装备",
        "收信用",
        "买信用商店",
    ],
    "战斗任务": ["演算", "影拓丰碑"],
    "奖励任务": ["活动奖励", "日常奖励"],
    "农牧任务": ["农牧相关"],
    "自动送货任务": ["自动送货"],
    "收尾任务": ["传送到帝江号右侧传送点"],
}
_SUBTASKS = {
    "RegionalBuildTask.json": {"⭐地区建设": ["据点兑换", "买物资", "买卖货"]},
    "BoatHarvestTask.json": {"⭐帝江号收菜": ["收集线索", "使用制造舱助力"]},
    "ActivityRewardTask.json": {"⭐活动奖励": ["周常奖励", "理智补给", "刮刮乐"]},
}


class TestEndfieldTaskSwitches(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.config_dir = root / "data/apps/ok-ef/working/configs"
        self.config_dir.mkdir(parents=True)
        self.enterContext(
            patch(
                "src.utils.utils_sub_config.get_script_root_dir", return_value=str(root)
            )
        )
        fixtures = Path(__file__).resolve().parents[1] / "fixtures"
        for name in ("DailyTask", "DailyBattleTask"):
            source = fixtures / f"ok_ef_{name}.scrubbed.json"
            (self.config_dir / f"{name}.json").write_bytes(source.read_bytes())
        for name, config in _SUBTASKS.items():
            self.save(name, config)
        self.switch = NativeTaskSwitch("ok-ef", load_native_task_switch_map()["ok-ef"])

    def load(self, name="DailyTask.json"):
        """读取沙箱配置，验证实际落盘值。"""
        return json.loads((self.config_dir / name).read_text(encoding="utf-8"))

    def save(self, name, config):
        """写入沙箱种子。"""
        (self.config_dir / name).write_text(
            json.dumps(config, ensure_ascii=False), encoding="utf-8"
        )

    def snapshot(self):
        """记录所有配置文件，检测跨文件误写。"""
        return {path.name: path.read_bytes() for path in self.config_dir.iterdir()}

    def test_reads_all_daily_switches_once_and_keeps_existing_subtasks(self):
        expected = [name for names in _GROUPS.values() for name in names]
        expected.append("执行外部命令")
        expected.extend(
            name
            for config in _SUBTASKS.values()
            for names in config.values()
            for name in names
        )
        before = self.snapshot()
        self.assertEqual(
            self.switch.read(),
            [
                {
                    "name": name,
                    "enabled": name not in {"执行外部命令", "清理基质", "影拓丰碑"},
                }
                for name in expected
            ],
        )
        self.assertEqual(len(expected), 26)
        self.assertEqual(len(set(expected)), len(expected))
        self.assertNotIn("刷体力", expected)
        self.assertEqual(self.snapshot(), before)

    def test_batch_round_trip_preserves_other_members_fields_and_files(self):
        seed = self.load()
        for group, names in _GROUPS.items():
            seed[group].append("上游新增任务")
            for name in names:
                if name not in seed[group]:
                    seed[group].append(name)
                seed[f"⭐{name}"] = False
        seed["⭐刷体力"] = False
        seed["⭐新增布尔设置"] = True
        self.save("DailyTask.json", seed)
        before = self.snapshot()
        states = {name: False for names in _GROUPS.values() for name in names}
        expected = deepcopy(seed)
        for group, names in _GROUPS.items():
            expected[group] = [name for name in seed[group] if name not in names]

        rows = self.switch.read()
        self.assertEqual(len(rows), 26, "旧布尔字段不能产生重复行或额外入口")
        self.assertTrue(all(row["enabled"] for row in rows if row["name"] in states))
        self.assertEqual(self.switch.write(states), len(states))
        self.assertEqual(self.load(), expected)
        after = self.snapshot()
        self.assertEqual(
            {name: data for name, data in after.items() if name != "DailyTask.json"},
            {name: data for name, data in before.items() if name != "DailyTask.json"},
        )
        self.assertFalse(
            any(row["enabled"] for row in self.switch.read() if row["name"] in states)
        )
        self.assertEqual(self.switch.write(states), 0)
        self.assertEqual(self.snapshot(), after)

        self.assertEqual(self.switch.write(dict.fromkeys(states, True)), len(states))
        for group, names in _GROUPS.items():
            expected[group].extend(names)
        self.assertEqual(self.load(), expected)
        self.assertTrue(
            all(row["enabled"] for row in self.switch.read() if row["name"] in states)
        )

    def test_parent_and_child_switches_write_independent_files(self):
        parents = {"地区建设": False, "帝江号收菜": False, "活动奖励": False}
        self.assertEqual(self.switch.write(parents), 3)
        for name, config in _SUBTASKS.items():
            self.assertEqual(self.load(name), config)
        daily = self.load()
        self.assertEqual(
            self.switch.write(
                {"据点兑换": False, "收集线索": False, "理智补给": False}
            ),
            3,
        )
        self.assertEqual(self.load(), daily)
        expected = {
            "RegionalBuildTask.json": {"⭐地区建设": ["买物资", "买卖货"]},
            "BoatHarvestTask.json": {"⭐帝江号收菜": ["使用制造舱助力"]},
            "ActivityRewardTask.json": {"⭐活动奖励": ["周常奖励", "刮刮乐"]},
        }
        for name, config in expected.items():
            self.assertEqual(self.load(name), config)

    def test_battle_switch_and_daily_card_do_not_overwrite_each_other(self):
        seed = self.load()
        seed["战斗任务"].append("影拓丰碑")
        self.save("DailyTask.json", seed)
        cfg = EndfieldConfig()
        cfg.set_daily_enabled("每日任务", False)
        self.assertEqual(self.load()["战斗任务"], ["演算", "影拓丰碑"])
        self.assertEqual(self.switch.write({"演算": False}), 1)
        self.assertEqual(self.load()["战斗任务"], ["影拓丰碑"])
        cfg.set_daily_task("每日任务", "能量淤积点", "枢纽区")
        self.assertEqual(self.load()["战斗任务"], ["影拓丰碑", "刷体力"])
        self.assertEqual(self.load("DailyBattleTask.json")["体力本"], "枢纽区")
        self.assertEqual(self.switch.write({"演算": True}), 1)
        self.assertEqual(self.load()["战斗任务"], ["影拓丰碑", "刷体力", "演算"])

    def test_new_tasks_require_explicit_selection_and_preserve_other_configuration(
        self,
    ):
        seed = self.load()
        seed["其他任务"].append("未知日常")
        seed["战斗任务"].append("未知战斗")
        seed["⭐清理基质"] = True
        seed["⭐影拓丰碑"] = True
        self.save("DailyTask.json", seed)
        before = self.snapshot()
        rows = {row["name"]: row["enabled"] for row in self.switch.read()}
        self.assertFalse(rows["清理基质"])
        self.assertFalse(rows["影拓丰碑"])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.switch.write({"清理基质": False, "影拓丰碑": False}), 0)
        self.assertEqual(self.snapshot(), before)

        expected = deepcopy(seed)
        expected["其他任务"].append("清理基质")
        self.assertEqual(self.switch.write({"清理基质": True}), 1)
        self.assertEqual(self.load(), expected)
        expected["战斗任务"].append("影拓丰碑")
        self.assertEqual(self.switch.write({"影拓丰碑": True}), 1)
        self.assertEqual(self.load(), expected)
        self.assertEqual(self.switch.write({"清理基质": False, "影拓丰碑": False}), 2)
        self.assertEqual(self.load(), seed)
        self.assertEqual(
            {
                name: data
                for name, data in self.snapshot().items()
                if name != "DailyTask.json"
            },
            {name: data for name, data in before.items() if name != "DailyTask.json"},
        )

    def test_missing_new_task_groups_are_not_created_from_legacy_switches(self):
        seed = self.load()
        del seed["其他任务"]
        del seed["战斗任务"]
        seed["⭐清理基质"] = True
        seed["⭐影拓丰碑"] = True
        self.save("DailyTask.json", seed)
        before = self.snapshot()
        with self.assertLogs("src.config.native_task_switch", level="WARNING"):
            names = [row["name"] for row in self.switch.read()]
            self.assertEqual(self.switch.write({"清理基质": True, "影拓丰碑": True}), 0)
        self.assertNotIn("清理基质", names)
        self.assertNotIn("影拓丰碑", names)
        self.assertEqual(self.snapshot(), before)

    def test_external_command_boolean_still_round_trips(self):
        expected = self.load()
        expected["⭐执行外部命令"] = True
        self.assertEqual(self.switch.write({"执行外部命令": True}), 1)
        self.assertEqual(self.load(), expected)

    def test_missing_group_is_hidden_without_creating_or_writing_legacy_keys(self):
        seed = self.load()
        del seed["帝江号任务"]
        seed["⭐送礼"] = False
        self.save("DailyTask.json", seed)
        before = self.snapshot()
        with self.assertLogs("src.config.native_task_switch", level="WARNING"):
            names = [row["name"] for row in self.switch.read()]
            self.assertEqual(self.switch.write({"送礼": True}), 0)
        self.assertTrue(set(_GROUPS["帝江号任务"]).isdisjoint(names))
        self.assertIn("演算", names)
        self.assertEqual(self.snapshot(), before)

    def test_regional_options_associate_with_parent_and_existing_children(self):
        groups = load_declarations()["ok-ef"]
        regional = next(
            group for group in groups if group["display_name"] == "地区建设"
        )
        self.assertEqual(
            regional["tasks"], ["地区建设", "据点兑换", "买物资", "买卖货"]
        )
