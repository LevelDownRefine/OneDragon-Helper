"""与固定 MAS 版本直接生成的队列比较，并验证 Daily 的框架适配。"""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.config import daily as daily_mod
from src.config import set_config as sc_mod
from src.config.maa_farming import (
    build_activity_fight,
    build_annihilation_fight,
    build_main_fight,
    build_remaining_fight,
    build_runtime_queue,
    find_fight_source,
)
from src.config.set_config import ArknightsConfig, prepare_daily_tasks
from tests.test_arknights_config_safety import load_fixture

MEDICINE_FIELDS = {
    "UseMedicine",
    "MedicineCount",
    "UseStone",
    "StoneCount",
    "UseExpiringMedicine",
    "UseExpireMedicineForActivity",
    "UseStoneAllowSave",
    "MedicineExpireDays",
}


class TestMasReference(unittest.TestCase):
    def test_generated_tasks_and_execution_order_match_mas(self):
        path = Path(__file__).parent / "fixtures/mas_farming_reference.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        for case in data["cases"]:
            with self.subTest(case=case["name"]):
                source = case["source"]
                before = copy.deepcopy(source)
                expected = case["expected"]
                main_source = find_fight_source(source, "理智作战") or {}
                series = main_source.get("Series", 0)
                main = build_main_fight(main_source, "理智作战", "AP-5", series)
                activity = build_activity_fight(
                    find_fight_source(source, "活动关优先") or main,
                    "活动关优先",
                    "ACT-7",
                )
                remaining = build_remaining_fight(
                    find_fight_source(source, "剩余理智") or main,
                    "剩余理智",
                    "1-7",
                    series,
                )
                actual = [activity, main, remaining]
                # 原生非战斗项保持原样；匿名、自定义和重复 Fight 不得额外进入执行。
                other = [t for t in expected if t["TaskType"] != "Fight"]
                annihilation = build_annihilation_fight({}, "剿灭作战", "Annihilation")
                queue = build_runtime_queue(source + other, annihilation, *actual)
                expected = expected[:1] + [annihilation] + expected[1:]
                # 用药已归本项目统一管理，其余字段和任务顺序继续对照 MAS。
                for task, reference in zip(queue, expected, strict=True):
                    self.assertEqual(
                        {k: v for k, v in task.items() if k not in MEDICINE_FIELDS},
                        {
                            k: v
                            for k, v in reference.items()
                            if k not in MEDICINE_FIELDS
                        },
                    )
                self.assertEqual(source, before)

    def test_task_builders_leave_medicine_to_daily(self):
        settings = {
            "UseMedicine": True,
            "MedicineCount": 3,
            "UseStone": True,
            "StoneCount": 2,
            "UseExpiringMedicine": True,
            "UseExpireMedicineForActivity": True,
            "UseStoneAllowSave": True,
            "MedicineExpireDays": 4,
        }
        for source in ({}, settings):
            tasks = (
                build_main_fight(source, "理智作战", "AP-5", 0),
                build_activity_fight(source, "活动关优先", "ACT-7"),
                build_remaining_fight(source, "剩余理智", "1-7", 0),
                build_annihilation_fight(source, "剿灭作战", "Annihilation"),
            )
            for task in tasks:
                with self.subTest(role=task["Name"], existing=bool(source)):
                    self.assertEqual(
                        {k: v for k, v in task.items() if k in MEDICINE_FIELDS},
                        source,
                    )


class TestMaaFarmingRuntime(unittest.TestCase):
    def setUp(self):
        # 使用原始夹具，不预先将旧任务重命名成代码期待的名字。
        self.store = {"config/gui.new.json": load_fixture()}
        self.saves = []
        self.stages = ["ACT-8", "ACT-7", "ACT-6"]
        weekly = patch.object(daily_mod, "get_weekly_start", return_value=None)
        self.weekly_start = weekly.start()
        self.addCleanup(weekly.stop)

        def load(script, path):
            assert path in self.store, f"missing: {path}"
            return copy.deepcopy(self.store[path])

        def save(script, path, data):
            self.store[path] = copy.deepcopy(data)
            self.saves.append(path)

        for module in (daily_mod, sc_mod):
            for method, callback in (("load_config", load), ("save_config", save)):
                patcher = patch.object(module, method, side_effect=callback)
                patcher.start()
                self.addCleanup(patcher.stop)
        for method, callback in (
            ("load_activity_stages", lambda *args: self.stages),
            ("load_normal_stages", lambda *args: ["AP-5", "1-7", "CE-6"]),
        ):
            patcher = patch.object(daily_mod, method, side_effect=callback)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.cfg = ArknightsConfig()
        self.activity = self.cfg._dispatch_daily("活动关卡")

    def queue(self):
        return self.store["config/gui.new.json"]["Configurations"]["Default"][
            "TaskQueue"
        ]

    def roles(self):
        return {t["Name"]: t for t in self.queue() if t["TaskType"] == "Fight"}

    def select_all(self):
        for name, stage in (
            ("活动关卡", "ACT-7"),
            ("理智作战", "AP-5"),
            ("剩余理智", "1-7"),
        ):
            self.cfg.set_daily_task(name, stage)

    def test_raw_native_queue_is_replaced_without_losing_non_fights(self):
        self.queue().append(
            {
                "$type": "FightTask",
                "Name": "",
                "TaskType": "Fight",
                "IsEnable": True,
                "StagePlan": ["1-7"],
            }
        )
        before = [copy.deepcopy(t) for t in self.queue() if t["TaskType"] != "Fight"]
        self.select_all()
        prepare_daily_tasks("MAA")
        self.assertEqual(
            list(self.roles()), ["剿灭", "活动关优先", "理智作战", "剩余理智"]
        )
        self.assertEqual([t for t in self.queue() if t["TaskType"] != "Fight"], before)
        self.assertEqual(self.roles()["剿灭"]["StagePlan"], ["Annihilation"])
        self.assertTrue(self.roles()["剿灭"]["IsEnable"])
        saved = copy.deepcopy(self.store)
        count = len(self.saves)
        prepare_daily_tasks("MAA")
        self.assertEqual(self.store, saved)
        self.assertEqual(len(self.saves), count)

    def test_expired_activity_keeps_fixed_stage_until_user_selects_again(self):
        self.select_all()
        self.stages = []
        prepare_daily_tasks("MAA")
        self.assertFalse(self.roles()["活动关优先"]["IsEnable"])
        self.assertFalse(self.activity.read_enabled())
        self.assertEqual(self.activity.read(), ("ACT-7", None))
        self.stages = ["NEW-8", "NEW-7"]
        prepare_daily_tasks("MAA")
        self.assertEqual(self.roles()["活动关优先"]["StagePlan"], ["ACT-7"])
        self.assertFalse(self.roles()["活动关优先"]["IsEnable"])
        self.cfg.set_daily_task("活动关卡", "NEW-7")
        self.assertTrue(self.roles()["活动关优先"]["IsEnable"])
        self.assertEqual(self.activity.read(), ("NEW-7", None))
        self.assertEqual(set(self.saves), {"config/gui.new.json"})
        self.assertEqual(set(self.store), {"config/gui.new.json"})

    def test_disabled_activity_does_not_reenable_on_new_event(self):
        self.select_all()
        self.cfg.set_daily_enabled("活动关卡", False)
        self.stages = ["NEW-8", "NEW-7"]
        prepare_daily_tasks("MAA")
        self.assertFalse(self.roles()["活动关优先"]["IsEnable"])
        self.assertFalse(self.activity.read_enabled())

    def test_activity_selection_survives_resource_reordering(self):
        self.stages = ["ACT-8", "ACT-7", "ACT-8", "ACT-6"]
        self.cfg.set_daily_task("活动关卡", "ACT-6")
        self.stages = ["ACT-6", "ACT-8", "ACT-7"]
        prepare_daily_tasks("MAA")
        self.assertEqual(self.roles()["活动关优先"]["StagePlan"], ["ACT-6"])
        self.assertTrue(self.activity.read_enabled())
        self.assertEqual(self.activity.read(), ("ACT-6", None))

    def test_existing_limits_are_reset_each_run_and_medicine_is_preserved(self):
        self.select_all()
        for task in self.roles().values():
            task.update(
                EnableTimesLimit=True,
                TimesLimit=1,
                EnableTargetDrop=True,
                DropId="2004",
                DropCount=1,
                IsInventoryTarget=True,
                UseMedicine=True,
                MedicineCount=3,
                UseStone=True,
                StoneCount=2,
                UseExpiringMedicine=False,
                MedicineExpireDays=4,
            )
        prepare_daily_tasks("MAA")
        for name, task in self.roles().items():
            self.assertFalse(task["EnableTimesLimit"], name)
            self.assertFalse(task["EnableTargetDrop"], name)
            if name != "理智作战":
                self.assertFalse(task["IsInventoryTarget"], name)
                self.assertEqual(task["DropId"], "", name)
            self.assertTrue(task["UseMedicine"], name)
            self.assertEqual(task["MedicineCount"], 3, name)
            self.assertTrue(task["UseStone"], name)
            self.assertEqual(task["StoneCount"], 2, name)
            self.assertTrue(task["UseExpiringMedicine"], name)
            self.assertEqual(task["MedicineExpireDays"], 4, name)

    def test_main_and_remaining_can_be_disabled_independently(self):
        self.select_all()
        self.cfg.set_daily_enabled("理智作战", False)
        prepare_daily_tasks("MAA")
        self.assertFalse(self.roles()["理智作战"]["IsEnable"])
        self.assertTrue(self.roles()["剩余理智"]["IsEnable"])
        self.assertTrue(self.roles()["活动关优先"]["IsEnable"])

    def test_daily_medicine_is_enabled_without_weekly_hook(self):
        self.select_all()
        for name, task in self.roles().items():
            if name in {"活动关优先", "理智作战", "剩余理智"}:
                self.assertTrue(task["UseExpiringMedicine"], name)
        self.cfg.set_daily_enabled("理智作战", False)
        self.stages = []
        prepare_daily_tasks("MAA")
        self.assertFalse(self.roles()["理智作战"]["IsEnable"])
        self.assertFalse(self.roles()["活动关优先"]["IsEnable"])
        for name, task in self.roles().items():
            self.assertTrue(task["UseExpiringMedicine"], name)

    def test_farming_roles_share_weekly_medicine_window(self):
        self.select_all()
        for start_day, expire_days in ((1, 7), (6, 2), (7, 1)):
            with self.subTest(start_day=start_day):
                prepare_daily_tasks("MAA")
                self.cfg.prepare_weekly_start_day(start_day)
                for task in self.roles().values():
                    self.assertTrue(task["UseExpiringMedicine"])
                    self.assertEqual(task["MedicineExpireDays"], expire_days)

    def test_new_tasks_take_current_weekly_window_on_creation(self):
        for start_day, expire_days in ((1, 7), (6, 2), (7, 1), (None, 2)):
            with self.subTest(start_day=start_day):
                self.weekly_start.return_value = start_day
                self.queue()[:] = [
                    task for task in self.queue() if task["TaskType"] != "Fight"
                ]
                self.select_all()
                for task in self.roles().values():
                    self.assertEqual(task["MedicineExpireDays"], expire_days)
                prepare_daily_tasks("MAA")
                for task in self.roles().values():
                    self.assertEqual(task["MedicineExpireDays"], expire_days)

    def test_later_task_uses_updated_weekly_window(self):
        self.weekly_start.return_value = 5
        self.cfg.set_daily_task("理智作战", "AP-5")
        self.assertEqual(self.roles()["理智作战"]["MedicineExpireDays"], 3)
        self.weekly_start.return_value = 1
        self.cfg.set_weekly_start_day(1)
        self.cfg.set_daily_task("活动关卡", "ACT-7")
        self.assertEqual(self.roles()["理智作战"]["MedicineExpireDays"], 7)
        self.assertEqual(self.roles()["活动关优先"]["MedicineExpireDays"], 7)

    def test_duplicate_role_names_use_first_native_source_once(self):
        self.select_all()
        duplicate = copy.deepcopy(self.roles()["理智作战"])
        duplicate["Series"] = 99
        self.queue().append(duplicate)
        prepare_daily_tasks("MAA")
        self.assertEqual(sum(t["Name"] == "理智作战" for t in self.queue()), 1)
        self.assertNotEqual(self.roles()["理智作战"]["Series"], 99)

    def test_missing_annihilation_is_created_without_a_new_gui_entry(self):
        self.queue()[:] = [t for t in self.queue() if t["TaskType"] != "Fight"]
        prepare_daily_tasks("MAA")
        self.assertEqual(list(self.roles()), ["剿灭作战"])
        self.assertTrue(self.roles()["剿灭作战"]["IsEnable"])
        self.cfg.prepare_weekly_start_day(1)
        self.assertTrue(self.roles()["剿灭作战"]["UseExpiringMedicine"])
        self.assertEqual(len(self.cfg._build_dailies()), 3)

    def test_stale_menu_choice_is_rejected_without_writing(self):
        with self.assertRaises(ValueError):
            self.cfg.set_daily_task("活动关卡", "OLD-7")
        self.assertEqual(self.saves, [])


class TestMaaNativePersistence(unittest.TestCase):
    def test_activity_selection_and_switch_use_only_native_config(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            native = root / "config/gui.new.json"
            native.parent.mkdir()
            native.write_text(json.dumps(load_fixture()), encoding="utf-8")
            with (
                patch.object(daily_mod, "get_weekly_start", return_value=5),
                patch(
                    "src.utils.utils_sub_config.get_script_root_dir",
                    return_value=folder,
                ),
                patch.object(
                    daily_mod, "load_activity_stages", return_value=["ACT-8", "ACT-7"]
                ) as stages,
            ):
                ArknightsConfig().set_daily_task("活动关卡", "ACT-7")
                reloaded = ArknightsConfig()._dispatch_daily("活动关卡")
                self.assertEqual(reloaded.read(), ("ACT-7", None))
                self.assertTrue(reloaded.read_enabled())

                # 在 MAA 原生配置中改关卡和开关，新实例直接反读。
                written = json.loads(native.read_text(encoding="utf-8"))
                activity = next(
                    t
                    for t in written["Configurations"]["Default"]["TaskQueue"]
                    if t["Name"] == "活动关优先"
                )
                activity.update(StagePlan=["ACT-8"], IsEnable=False)
                native.write_text(json.dumps(written), encoding="utf-8")
                reloaded = ArknightsConfig()._dispatch_daily("活动关卡")
                self.assertEqual(reloaded.read(), ("ACT-8", None))
                self.assertFalse(reloaded.read_enabled())
                reloaded.set_enabled(True)
                self.assertTrue(
                    ArknightsConfig()._dispatch_daily("活动关卡").read_enabled()
                )

                stages.return_value = ["NEW-8", "NEW-7"]
                prepare_daily_tasks("MAA")
                written = json.loads(native.read_text(encoding="utf-8"))
                activity = next(
                    t
                    for t in written["Configurations"]["Default"]["TaskQueue"]
                    if t["Name"] == "活动关优先"
                )
                self.assertEqual(activity["StagePlan"], ["ACT-8"])
                self.assertFalse(activity["IsEnable"])
                self.assertNotIn("index", activity)
                ArknightsConfig().set_daily_task("活动关卡", "NEW-7")
                reloaded = ArknightsConfig()._dispatch_daily("活动关卡")
                self.assertEqual(reloaded.read(), ("NEW-7", None))
                self.assertTrue(reloaded.read_enabled())
                self.assertEqual(set(native.parent.iterdir()), {native})
