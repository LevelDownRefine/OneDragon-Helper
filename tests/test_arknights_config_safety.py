"""明日方舟（MAA / 粥）config 安全性测试。

用一份「脱敏后的真实 gui.new.json」当夹具（tests/fixtures/maa_gui.new.scrubbed.json），
跑 init_config / set_daily_task / prepare_weekly_start_day，对每次落盘做全量字段 diff，
断言「只动了该动的字段，其余（含注入的金丝雀字段）原封不动」。

验证各刷图角色独立启停，从原生单战斗任务补齐角色时保留其它原生配置。
"""

import copy
import json
import os
import unittest
from unittest.mock import patch

from src.config import daily as daily_mod
from src.config import set_config as sc_mod
from src.config.set_config import ArknightsConfig
from tests.config_diff import diff_paths

FIXTURE = os.path.join(
    os.path.dirname(__file__), "fixtures", "maa_gui.new.scrubbed.json"
)

# TaskQueue 中 6 个 FightTask 的索引
FIGHT_IDX = (1, 2, 3, 4, 5, 6)  # 剿灭, 红票, 经验, 龙门币, 活动土, 土

# prepare_weekly_start_day 只允许改动的字段路径集合
ALLOWED_WEEKLY = {
    f"Configurations.Default.TaskQueue[{i}].UseExpiringMedicine" for i in FIGHT_IDX
} | {f"Configurations.Default.TaskQueue[{i}].MedicineExpireDays" for i in FIGHT_IDX}


def load_fixture() -> dict:
    with open(FIXTURE, encoding="utf-8") as f:
        return json.load(f)


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
            t["UseMedicine"] = (
                True  # 药配置相关但绝不该被 set_daily_task/prepare_weekly_start_day 动
            )
            t["CANARY_TASK"] = "X"


class TestArknightsConfigSafety(unittest.TestCase):
    def setUp(self):
        self.seed = load_fixture()
        for task in self.seed["Configurations"]["Default"]["TaskQueue"]:
            if task["Name"] == "红票":
                task["Name"] = "理智作战"
            elif task["Name"] == "活动土":
                task["Name"] = "活动关优先"
            elif task["Name"] == "土":
                task["Name"] = "剩余理智"
        inject_canaries(self.seed)
        self.store = {"config/gui.new.json": copy.deepcopy(self.seed)}
        self.saves: list[tuple[str, dict]] = []

        def fake_load(script_name, rel_path=None):
            assert rel_path in self.store, f"missing: {rel_path}"
            return copy.deepcopy(self.store[rel_path])

        def fake_save(script_name, rel_path, data):
            self.store[rel_path] = copy.deepcopy(data)
            self.saves.append((rel_path, copy.deepcopy(data)))

        self._lp = patch.object(sc_mod, "load_config", fake_load)
        self._sp = patch.object(sc_mod, "save_config", fake_save)
        # Daily 自持 I/O 直调 daily 模块原语，同 fake 双注册
        self._ldp = patch.object(daily_mod, "load_config", fake_load)
        self._dsp = patch.object(daily_mod, "save_config", fake_save)
        self._stages = patch.object(
            daily_mod, "load_activity_stages", return_value=["SR-8", "SR-7"]
        )
        self._stages.start()
        self.addCleanup(self._stages.stop)
        self._lp.start()
        self._sp.start()
        self._ldp.start()
        self._dsp.start()

    def tearDown(self):
        # 只停 setUp 自身 start 的两个 patch，不用全局 stopall（避免误停他方活跃 patch）。
        self._lp.stop()
        self._sp.stop()
        self._ldp.stop()
        self._dsp.stop()

    # ---- 实例化：绝不该改任何东西（反读/只读入口依赖此不变量）----
    def test_instantiation_touches_nothing(self):
        """ArknightsConfig() 实例化不得触碰 config（反读路径依赖此不变量）。"""
        ArknightsConfig()
        diff = diff_paths(self.seed, self.store["config/gui.new.json"])
        self.assertEqual(diff, [], f"实例化意外改动: {diff}")

    def test_select_main_stage_preserves_other_roles(self):
        cfg = ArknightsConfig()
        queue = self.store["config/gui.new.json"]["Configurations"]["Default"][
            "TaskQueue"
        ]
        for task in queue:
            if task["$type"] == "FightTask":
                task["IsEnable"] = False
        before = copy.deepcopy(self.store["config/gui.new.json"])
        cfg.set_daily_task("理智作战", "1-7")
        after = self.store["config/gui.new.json"]
        expected = copy.deepcopy(before)
        original = expected["Configurations"]["Default"]["TaskQueue"]
        main = original[2]
        main.update(
            StagePlan=["1-7"],
            IsEnable=True,
            IsStageManually=True,
            UseOptionalStage=True,
            UseCustomAnnihilation=False,
            UseExpiringMedicine=True,
        )
        self.assertEqual(after, expected)

    # ---- prepare_weekly_start_day：只允许改 6 个 FightTask 的 UseExpiringMedicine / MedicineExpireDays ----
    def test_set_weekly_only_touches_medicine_fields(self):
        cfg = ArknightsConfig()
        cfg.set_daily_task("理智作战", "1-7")  # 先把 IsEnable 设到日常态

        # 制造差异：把药配置先拨到错误值，逼 prepare_weekly_start_day 真正落盘
        pre = copy.deepcopy(self.store["config/gui.new.json"])
        for t in pre["Configurations"]["Default"]["TaskQueue"]:
            if t.get("$type") == "FightTask":
                t["UseExpiringMedicine"] = False
                t["MedicineExpireDays"] = 1
        self.store["config/gui.new.json"] = pre
        snapshot = copy.deepcopy(pre)

        cfg.prepare_weekly_start_day(1)  # 周几起=1 ⇒ MedicineExpireDays=7

        post = self.store["config/gui.new.json"]
        diff = diff_paths(snapshot, post)
        paths = {p for p, _, _ in diff}
        self.assertLessEqual(
            paths,
            ALLOWED_WEEKLY,
            f"prepare_weekly_start_day 改到了不该改的字段: {paths - ALLOWED_WEEKLY}",
        )
        # 正向校验：所有战斗任务共用临期用药，窗口=7。
        tq = post["Configurations"]["Default"]["TaskQueue"]
        by_name = {t["Name"]: t for t in tq if t.get("$type") == "FightTask"}
        self.assertTrue(by_name["剿灭"]["UseExpiringMedicine"])
        self.assertTrue(by_name["剩余理智"]["UseExpiringMedicine"])
        self.assertTrue(by_name["活动关优先"]["UseExpiringMedicine"])
        self.assertTrue(by_name["理智作战"]["UseExpiringMedicine"])
        self.assertEqual(by_name["剩余理智"]["MedicineExpireDays"], 7)
        self.assertEqual(by_name["剿灭"]["MedicineExpireDays"], 7)

    # ---- 金丝雀：无关字段全程不被触碰 ----
    def test_canaries_untouched_through_full_flow(self):
        cfg = ArknightsConfig()
        cfg.set_daily_task("理智作战", "1-7")
        cfg.prepare_weekly_start_day(1)

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

    def test_missing_main_role_does_not_adopt_another_fight_task(self):
        queue = self.store["config/gui.new.json"]["Configurations"]["Default"][
            "TaskQueue"
        ]
        queue[:] = [task for task in queue if task["Name"] != "理智作战"]
        before = copy.deepcopy(queue)
        self.assertEqual(
            ArknightsConfig()._dispatch_daily("理智作战").read(), (None, None)
        )
        ArknightsConfig().set_daily_task("理智作战", "AP-5")
        queue = self.store["config/gui.new.json"]["Configurations"]["Default"][
            "TaskQueue"
        ]
        main = next(task for task in queue if task["Name"] == "理智作战")
        self.assertEqual(main["StagePlan"], ["AP-5"])
        self.assertTrue(main["IsEnable"])
        self.assertFalse(main["UseMedicine"])
        self.assertNotIn("CANARY_TASK", main)
        for old in before:
            self.assertEqual(
                next(task for task in queue if task["Name"] == old["Name"]), old
            )
        ArknightsConfig()._init_config()
        queue = self.store["config/gui.new.json"]["Configurations"]["Default"][
            "TaskQueue"
        ]
        self.assertEqual(
            [
                task["Name"]
                for task in queue
                if task["Name"] in {"活动关优先", "理智作战", "剩余理智"}
            ],
            ["活动关优先", "理智作战", "剩余理智"],
        )

    def test_each_role_can_be_selected_and_disabled_independently(self):
        cfg = ArknightsConfig()
        cfg.set_daily_task("理智作战", "AP-5")
        for daily_name, stage in (("活动关卡", "SR-8"), ("剩余理智", "1-7")):
            with self.subTest(daily=daily_name):
                before = copy.deepcopy(self.store["config/gui.new.json"])
                cfg.set_daily_task(daily_name, stage)
                cfg.set_daily_enabled(daily_name, False)
                daily = cfg._dispatch_daily(daily_name)
                self.assertFalse(daily.read_enabled())
                self.assertEqual(daily.read(), (stage, None))
                self.assertEqual(cfg._dispatch_daily("理智作战").read(), ("AP-5", None))
                cfg.set_daily_task("理智作战", "LS-6")
                self.assertFalse(daily.read_enabled())
                cfg.set_daily_task("理智作战", "AP-5")
                before_queue = before["Configurations"]["Default"]["TaskQueue"]
                after_queue = self.store["config/gui.new.json"]["Configurations"][
                    "Default"
                ]["TaskQueue"]
                for old, new in zip(before_queue, after_queue, strict=True):
                    if old["$type"] != "FightTask":
                        self.assertEqual(old, new)

    def test_main_roundtrip_keeps_remaining_slot_and_advanced_fields(self):
        cfg = ArknightsConfig()
        before = copy.deepcopy(self.store["config/gui.new.json"])
        for stage in ("AP-5", "1-7", "LS-6", "1-7"):
            cfg.set_daily_task("理智作战", stage)
            self.assertEqual(cfg._dispatch_daily("理智作战").read(), (stage, None))
        queue = self.store["config/gui.new.json"]["Configurations"]["Default"][
            "TaskQueue"
        ]
        old = before["Configurations"]["Default"]["TaskQueue"]
        self.assertEqual(queue[6], old[6])
        managed = {
            "Name",
            "StagePlan",
            "IsEnable",
            "IsStageManually",
            "UseOptionalStage",
            "UseWeeklySchedule",
            "UseCustomAnnihilation",
            "UseExpiringMedicine",
        }
        for key in old[2]:
            if key not in managed:
                self.assertEqual(
                    next(task for task in queue if task["Name"] == "理智作战")[key],
                    old[2][key],
                    key,
                )
        saves = len(self.saves)
        cfg.set_daily_task("理智作战", "1-7")
        self.assertEqual(len(self.saves), saves)

    def test_empty_queue_creates_roles_in_farming_order(self):
        queue = self.store["config/gui.new.json"]["Configurations"]["Default"][
            "TaskQueue"
        ]
        queue[:] = [task for task in queue if task["$type"] != "FightTask"]
        other_tasks = copy.deepcopy(queue)
        cfg = ArknightsConfig()
        cfg._init_config()
        for daily_name, stage in (
            ("剩余理智", "1-7"),
            ("理智作战", "AP-5"),
            ("活动关卡", "SR-8"),
        ):
            cfg.set_daily_enabled(daily_name, False)
            cfg.set_daily_task(daily_name, stage)
        queue = self.store["config/gui.new.json"]["Configurations"]["Default"][
            "TaskQueue"
        ]
        self.assertEqual(
            [task["Name"] for task in queue[:5]],
            ["开始唤醒", "剿灭作战", "活动关优先", "理智作战", "剩余理智"],
        )
        self.assertEqual(
            [task for task in queue if task["$type"] != "FightTask"], other_tasks
        )
        for task in queue[1:5]:
            self.assertFalse(task["UseMedicine"])
            self.assertFalse(task["UseStone"])
            self.assertTrue(task["UseExpiringMedicine"])
            self.assertEqual(task["MedicineExpireDays"], 2)

    def test_remaining_does_not_adopt_main_task_when_both_farm_1_7(self):
        cfg = ArknightsConfig()
        cfg.set_daily_task("理智作战", "1-7")
        queue = self.store["config/gui.new.json"]["Configurations"]["Default"][
            "TaskQueue"
        ]
        queue[:] = [task for task in queue if task["Name"] != "剩余理智"]
        main = copy.deepcopy(next(task for task in queue if task["Name"] == "理智作战"))
        self.assertFalse(cfg._dispatch_daily("剩余理智").read_enabled())
        cfg.set_daily_task("剩余理智", "1-7")
        queue = self.store["config/gui.new.json"]["Configurations"]["Default"][
            "TaskQueue"
        ]
        self.assertEqual(
            next(task for task in queue if task["Name"] == "理智作战"), main
        )
        self.assertEqual(
            sum(
                task["StagePlan"] == ["1-7"]
                for task in queue
                if task["$type"] == "FightTask"
            ),
            2,
        )

    def test_edit_keeps_unmanaged_fights_until_runtime(self):
        queue = self.store["config/gui.new.json"]["Configurations"]["Default"][
            "TaskQueue"
        ]
        queue.extend(
            [
                {
                    "$type": "FightTask",
                    "TaskType": "Fight",
                    "Name": "自定义",
                    "IsEnable": True,
                    "StagePlan": ["unknown"],
                },
                {
                    "$type": "FightTask",
                    "TaskType": "Fight",
                    "Name": "备选",
                    "IsEnable": True,
                    "StagePlan": ["AP-5", "CE-6"],
                },
            ]
        )
        before = copy.deepcopy(queue[-2:])
        ArknightsConfig().set_daily_task("理智作战", "LS-6")
        queue = self.store["config/gui.new.json"]["Configurations"]["Default"][
            "TaskQueue"
        ]
        self.assertEqual(queue[-2:], before)

    def test_readback_does_not_write_or_create_missing_tasks(self):
        self.store["config/gui.new.json"]["Configurations"]["Default"]["TaskQueue"] = []
        for daily in ArknightsConfig()._build_dailies():
            self.assertEqual(daily.read(), (None, None))
            self.assertFalse(daily.read_enabled())
        self.assertEqual(self.saves, [])

    def test_init_disables_expired_activity_and_keeps_main_enabled(self):
        cfg = ArknightsConfig()
        cfg.set_daily_task("活动关卡", "SR-8")
        cfg.set_daily_task("理智作战", "AP-5")
        with patch.object(daily_mod, "load_activity_stages", return_value=[]):
            cfg._init_config()
        after = self.store["config/gui.new.json"]
        activity = next(
            task
            for task in after["Configurations"]["Default"]["TaskQueue"]
            if task["Name"] == "活动关优先"
        )
        self.assertFalse(activity["IsEnable"])
        self.assertFalse(cfg._dispatch_daily("活动关卡").read_enabled())
        self.assertTrue(cfg._dispatch_daily("理智作战").read_enabled())
        self.assertEqual(cfg._dispatch_daily("活动关卡").read(), ("SR-8", None))

    def test_init_does_not_reenable_disabled_activity(self):
        cfg = ArknightsConfig()
        cfg.set_daily_task("活动关卡", "SR-7")
        cfg.set_daily_enabled("活动关卡", False)
        cfg._init_config()
        before = copy.deepcopy(self.store["config/gui.new.json"])
        cfg._init_config()
        self.assertEqual(self.store["config/gui.new.json"], before)

    def test_activity_choice_must_still_be_available(self):
        with self.assertRaises(ValueError):
            ArknightsConfig().set_daily_task("活动关卡", "EXPIRED-8")
        self.assertFalse(self.saves)

    def test_normal_roles_use_declared_stages_without_reading_resources(self):
        cfg = ArknightsConfig()
        with patch("src.config.maa_stages.load_game_config") as resource:
            for name in ("理智作战", "剩余理智"):
                cfg.set_daily_task(name, "PR-A-2")
                self.assertEqual(cfg._dispatch_daily(name).read(), ("PR-A-2", None))
        resource.assert_not_called()
        before = copy.deepcopy(self.store)
        for name in ("理智作战", "剩余理智"):
            with self.assertRaises(AssertionError):
                cfg.set_daily_task(name, "未声明的关卡")
        self.assertEqual(self.store, before)
        self.assertEqual(cfg._dispatch_daily("剩余理智").read(), ("PR-A-2", None))

    def test_expired_activity_keeps_medicine_enabled_without_running(self):
        from src.service.run_actions import apply_subscript_config

        cfg = ArknightsConfig()
        cfg.set_daily_task("活动关卡", "SR-8")
        cfg.set_daily_task("理智作战", "AP-5")
        with patch.object(daily_mod, "load_activity_stages", return_value=[]):
            cfg._init_config()
            apply_subscript_config({"MAA"}, {"MAA": 1})
        queue = self.store["config/gui.new.json"]["Configurations"]["Default"][
            "TaskQueue"
        ]
        activity = next(task for task in queue if task["Name"] == "活动关优先")
        backup = next(task for task in queue if task["Name"] == "理智作战")
        self.assertFalse(activity["IsEnable"])
        self.assertTrue(activity["UseExpiringMedicine"])
        self.assertTrue(backup["IsEnable"])
        self.assertTrue(backup["UseExpiringMedicine"])

    def test_native_custom_stage_is_read_without_overwriting_it(self):
        queue = self.store["config/gui.new.json"]["Configurations"]["Default"][
            "TaskQueue"
        ]
        queue[2]["Name"] = "理智作战"
        queue[2]["StagePlan"] = ["12-17"]
        daily = ArknightsConfig()._dispatch_daily("理智作战")
        self.assertEqual(daily.read(), ("12-17", None))
        self.assertFalse(self.saves)

    def test_new_roles_do_not_inherit_main_user_settings(self):
        queue = self.store["config/gui.new.json"]["Configurations"]["Default"][
            "TaskQueue"
        ]
        queue[:] = [
            task
            for task in queue
            if task["TaskType"] != "Fight" or task["Name"] == "理智作战"
        ]
        main = next(task for task in queue if task["Name"] == "理智作战")
        main.update(
            StagePlan=[],
            Series=6,
            HideUnavailableStage=False,
            EnableTargetDrop=True,
            DropId="4001",
            DropCount=100,
            EnableTimesLimit=True,
            NativeOptions={"nested": [1, 2]},
            IsDrGrandet=True,
            MedicineCount=3,
        )
        original = copy.deepcopy(main)
        others = copy.deepcopy([task for task in queue if task is not main])
        cfg = ArknightsConfig()
        self.assertEqual(cfg._dispatch_daily("理智作战").read(), (None, None))
        for name in ("活动关卡", "剩余理智"):
            self.assertFalse(cfg._dispatch_daily(name).read_enabled())
        self.assertFalse(self.saves)

        # 即使先选剩余、再选活动，也只补角色，不依赖预先建好多个 FightTask。
        cfg.set_daily_task("剩余理智", "1-7")
        cfg.set_daily_task("活动关卡", "SR-8")
        queue = self.store["config/gui.new.json"]["Configurations"]["Default"][
            "TaskQueue"
        ]
        by_name = {task["Name"]: task for task in queue if task["TaskType"] == "Fight"}
        self.assertEqual(set(by_name), {"活动关优先", "理智作战", "剩余理智"})
        fights = [by_name[name] for name in ("活动关优先", "理智作战", "剩余理智")]
        self.assertEqual(fights[1], original)
        self.assertEqual(
            [task for task in queue if task["TaskType"] != "Fight"], others
        )
        self.assertEqual(
            [task["StagePlan"] for task in fights], [["SR-8"], [], ["1-7"]]
        )
        for task in (fights[0], fights[2]):
            for key in ("HideUnavailableStage", "NativeOptions", "IsDrGrandet"):
                self.assertNotIn(key, task)
            self.assertFalse(task["UseMedicine"])
            self.assertEqual(task["MedicineCount"], 0)
            self.assertFalse(task["EnableTargetDrop"])
            self.assertFalse(task["EnableTimesLimit"])
            self.assertTrue(task["IsStageManually"])
            self.assertFalse(task["UseWeeklySchedule"])
        self.assertNotIn("Series", fights[0])
        self.assertEqual(fights[2]["Series"], 0)
        self.assertNotIn("DropId", fights[2])

        cfg.set_daily_task("理智作战", "AP-5")
        cfg.set_daily_task("活动关卡", "SR-7")
        cfg.set_daily_task("剩余理智", "1-7")
        queue = self.store["config/gui.new.json"]["Configurations"]["Default"][
            "TaskQueue"
        ]
        self.assertEqual(sum(task["TaskType"] == "Fight" for task in queue), 3)
        main = next(task for task in queue if task["Name"] == "理智作战")
        self.assertTrue(main["UseOptionalStage"])
        self.assertTrue(main["UseMedicine"])
        self.assertEqual(main["MedicineCount"], 3)

    def test_existing_roles_keep_their_own_native_options(self):
        queue = self.store["config/gui.new.json"]["Configurations"]["Default"][
            "TaskQueue"
        ]
        roles = ("活动关优先", "理智作战", "剩余理智")
        for index, name in enumerate(roles):
            task = next(task for task in queue if task["Name"] == name)
            task["Series"] = index + 1
            task["MedicineCount"] = index + 2
            task["NativeOptions"] = {"owner": name}
        cfg = ArknightsConfig()
        for name, stage in (
            ("活动关卡", "SR-8"),
            ("理智作战", "LS-6"),
            ("剩余理智", "1-7"),
        ):
            cfg.set_daily_task(name, stage)
        queue = self.store["config/gui.new.json"]["Configurations"]["Default"][
            "TaskQueue"
        ]
        for index, name in enumerate(roles):
            task = next(task for task in queue if task["Name"] == name)
            self.assertEqual(task["Series"], index + 1)
            self.assertEqual(task["MedicineCount"], index + 2)
            self.assertTrue(task["UseMedicine"])
            self.assertEqual(task["NativeOptions"], {"owner": name})

    def test_custom_same_stage_and_same_name_other_type_are_not_adopted(self):
        queue = self.store["config/gui.new.json"]["Configurations"]["Default"][
            "TaskQueue"
        ]
        queue[:] = [task for task in queue if task["TaskType"] != "Fight"]
        custom = [
            {
                "$type": "FightTask",
                "TaskType": "Fight",
                "Name": "自建",
                "IsEnable": True,
                "StagePlan": ["1-7"],
            },
            {
                "$type": "CustomTask",
                "TaskType": "Custom",
                "Name": "剩余理智",
                "IsEnable": True,
            },
        ]
        queue.extend(copy.deepcopy(custom))
        cfg = ArknightsConfig()
        self.assertEqual(cfg._dispatch_daily("剩余理智").read(), (None, None))
        cfg.set_daily_task("剩余理智", "1-7")
        queue = self.store["config/gui.new.json"]["Configurations"]["Default"][
            "TaskQueue"
        ]
        for task in custom:
            self.assertIn(task, queue)
        self.assertEqual(cfg._dispatch_daily("剩余理智").read(), ("1-7", None))


if __name__ == "__main__":
    unittest.main(verbosity=2)
