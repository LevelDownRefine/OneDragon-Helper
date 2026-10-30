"""ok-ef v2.0.6 子任务参数：仅修改日常任务实际使用的独立配置。"""

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from src.config.task.task_options import task_options_of


class TestEndfieldTaskOptions(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.config_dir = root / "data/apps/ok-ef/working/configs"
        self.config_dir.mkdir(parents=True)
        for target in (
            "src.config.task.task_options.get_script_root_dir",
            "src.utils.utils_sub_config.get_script_root_dir",
        ):
            self.enterContext(patch(target, return_value=str(root)))
        self.seeds = {
            "RegionalBuildTask.json": {
                "⭐地区建设": ["据点兑换", "买物资"],
                "据点兑换仅购买优先商品": False,
                "交易货品优先序列": ["保留商品"],
                "只买不卖": True,
            },
            "DailyDeliveryTask.json": {
                "到达方式": "仅滑索",
                "地区切换": "武陵",
                "目标券数": [163000],
            },
            "DailyYingTuoTask.json": {
                "⭐领取影拓丰碑奖励": True,
                "保留字段": {"自定义": 1},
            },
            "DeliveryTask.json": {"到达方式": "仅滑索", "运行模式": "仅送货"},
            "YingTuoTask.json": {"⭐领取影拓丰碑奖励": True},
            "DailyTask.json": {"战斗任务": ["刷体力", "影拓丰碑"]},
        }
        for name, value in self.seeds.items():
            self.save(name, value)
        source = root / "data/apps/ok-ef/working/assets/data/delivery_area.json"
        source.parent.mkdir(parents=True)
        source.write_text(
            json.dumps({"delivery_area_config": {"武陵": {}}}, ensure_ascii=False),
            encoding="utf-8",
        )
        self.options = task_options_of("ok-ef")

    def save(self, name, value):
        """写入隔离原生配置。"""
        (self.config_dir / name).write_text(
            json.dumps(value, ensure_ascii=False), encoding="utf-8"
        )

    def snapshot(self):
        """记录字节，捕获未提交字段或独立任务被误写。"""
        return {path.name: path.read_bytes() for path in self.config_dir.iterdir()}

    def test_reads_new_options_from_native_daily_files_without_writing(self):
        before = self.snapshot()
        rows = {row["id"]: row for row in self.options.read()}
        regional = rows["regional_priority_only"]
        self.assertIs(regional["value"], False)
        self.assertIn("据点兑换", regional["tasks"])
        delivery = rows["delivery_arrival_mode"]
        self.assertEqual(delivery["value"], "仅滑索")
        self.assertEqual(delivery["tasks"], ["自动送货"])
        self.assertEqual(
            [choice["physical_name"] for choice in delivery["choices"]],
            ["仅滑索", "网格导航"],
        )
        yingtuo = rows["yingtuo_claim_reward"]
        self.assertIs(yingtuo["value"], True)
        self.assertEqual(yingtuo["tasks"], ["影拓丰碑"])
        self.assertEqual(self.snapshot(), before)

    def test_each_option_changes_only_its_daily_file_and_preserves_other_fields(self):
        cases = (
            (
                "regional_priority_only",
                True,
                "RegionalBuildTask.json",
                "据点兑换仅购买优先商品",
            ),
            (
                "delivery_arrival_mode",
                "网格导航",
                "DailyDeliveryTask.json",
                "到达方式",
            ),
            (
                "yingtuo_claim_reward",
                False,
                "DailyYingTuoTask.json",
                "⭐领取影拓丰碑奖励",
            ),
        )
        for ident, value, name, key in cases:
            with self.subTest(option=ident):
                before = self.snapshot()
                expected = deepcopy(self.seeds[name])
                expected[key] = value
                self.options.write_prepared(self.options.prepare({ident: value}))
                after = self.snapshot()
                self.assertEqual(json.loads(after[name]), expected)
                self.assertEqual(
                    {path: data for path, data in after.items() if path != name},
                    {path: data for path, data in before.items() if path != name},
                )
                row = next(row for row in self.options.read() if row["id"] == ident)
                self.assertEqual(row["value"], value)

    def test_missing_native_fields_or_files_hide_options_and_reject_writes(self):
        cases = (
            (
                "regional_priority_only",
                "RegionalBuildTask.json",
                "据点兑换仅购买优先商品",
            ),
            ("delivery_arrival_mode", "DailyDeliveryTask.json", "到达方式"),
            ("yingtuo_claim_reward", "DailyYingTuoTask.json", "⭐领取影拓丰碑奖励"),
        )
        for _, name, key in cases:
            config = deepcopy(self.seeds[name])
            del config[key]
            self.save(name, config)
        for missing in ("field", "file"):
            with self.subTest(missing=missing):
                if missing == "file":
                    for _, name, _ in cases:
                        (self.config_dir / name).unlink()
                before = self.snapshot()
                rows = {row["id"] for row in self.options.read()}
                self.assertTrue({ident for ident, _, _ in cases}.isdisjoint(rows))
                for ident, _, _ in cases:
                    with self.assertRaises(ValueError):
                        self.options.prepare({ident: True})
                self.assertEqual(self.snapshot(), before)
