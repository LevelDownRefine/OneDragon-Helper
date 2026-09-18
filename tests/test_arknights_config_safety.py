"""MAA 原生配置的编辑、初始化和持久化边界。"""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.config import daily as daily_mod
from src.config import set_config as sc_mod
from src.config.set_config import ArknightsConfig


def load_fixture():
    path = Path(__file__).parent / "fixtures/maa_gui.new.scrubbed.json"
    return json.loads(path.read_text(encoding="utf-8"))


class TestMaaNativeConfig(unittest.TestCase):
    def setUp(self):
        self.data = load_fixture()
        self.saved = []
        self.stages = ["AT-8", "AT-7"]

        def load(*args):
            return copy.deepcopy(self.data)

        def save(script, path, config):
            self.assertEqual(path, "config/gui.new.json")
            self.data = copy.deepcopy(config)
            self.saved.append(path)

        for module in (daily_mod, sc_mod):
            for name, function in (("load_config", load), ("save_config", save)):
                mock = patch.object(module, name, side_effect=function)
                mock.start()
                self.addCleanup(mock.stop)
        mock = patch.object(
            daily_mod, "read_activity_stages", side_effect=lambda *args: self.stages
        )
        mock.start()
        self.addCleanup(mock.stop)
        self.cfg = ArknightsConfig()

    def queue(self):
        return self.data["Configurations"]["Default"]["TaskQueue"]

    def task(self, name):
        return next(task for task in self.queue() if task["Name"] == name)

    def select(self):
        for name, stage in (
            ("活动关卡", "AT-8"),
            ("理智作战", "CE-6"),
            ("剩余理智", "1-7"),
        ):
            self.cfg.set_daily_task(name, stage)

    def test_reading_does_not_initialize_or_save(self):
        before = copy.deepcopy(self.data)
        self.assertEqual(len(self.cfg._read_daily_tasks()), 3)
        self.assertEqual(self.data, before)
        self.assertFalse(self.saved)

    def test_init_creates_disabled_slots_and_always_enabled_annihilation(self):
        self.cfg._init_config()
        fights = [t for t in self.queue() if t["$type"] == "FightTask"]
        self.assertEqual(
            [t["Name"] for t in fights], ["剿灭", "活动关优先", "理智作战", "剩余理智"]
        )
        self.assertTrue(fights[0]["IsEnable"])
        self.assertEqual(fights[0]["StagePlan"], ["Annihilation"])
        for task in fights[1:]:
            self.assertFalse(task["IsEnable"])
            self.assertEqual(task["StagePlan"], [""])
        self.assertEqual(len(self.cfg._dailies), 3)
        self.assertTrue(all(t["UseExpiringMedicine"] for t in fights))

    def test_init_is_idempotent_and_keeps_nonfight_config(self):
        before = copy.deepcopy(self.data)
        self.cfg._init_config()
        original = before["Configurations"]["Default"]["TaskQueue"]
        original[:] = [t for t in original if t["$type"] != "FightTask"]
        after = copy.deepcopy(self.data)
        changed = after["Configurations"]["Default"]["TaskQueue"]
        changed[:] = [t for t in changed if t["$type"] != "FightTask"]
        self.assertEqual(after, before)
        saves = len(self.saved)
        self.cfg._init_config()
        self.assertEqual(len(self.saved), saves)

    def test_selected_stage_and_switch_are_independent_per_entry(self):
        self.cfg._init_config()
        order = [t["Name"] for t in self.queue()]
        self.select()
        self.cfg.set_daily_enabled("理智作战", False)
        self.assertEqual([t["Name"] for t in self.queue()], order)
        self.assertEqual(self.task("理智作战")["StagePlan"], ["CE-6"])
        self.assertFalse(self.task("理智作战")["IsEnable"])
        self.assertTrue(self.task("活动关优先")["IsEnable"])
        self.assertTrue(self.task("剩余理智")["IsEnable"])
        self.assertEqual(self.cfg._dispatch_daily("理智作战").read(), ("CE-6", None))

    def test_new_entry_uses_template_instead_of_another_task(self):
        self.cfg.set_daily_task("理智作战", "AP-5")
        self.task("理智作战").update(
            Series=6, UseMedicine=True, MedicineCount=9, NativeOnly={"nested": [1]}
        )
        before = copy.deepcopy(self.task("理智作战"))
        self.cfg.set_daily_task("剩余理智", "1-7")
        created = self.task("剩余理智")
        self.assertEqual(created["Series"], 0)
        self.assertFalse(created["UseMedicine"])
        self.assertNotIn("NativeOnly", created)
        self.assertEqual(self.task("理智作战"), before)

    def test_existing_entries_keep_their_native_settings(self):
        self.select()
        for index, name in enumerate(("活动关优先", "理智作战", "剩余理智")):
            self.task(name).update(
                Series=index + 1,
                UseMedicine=True,
                MedicineCount=3,
                UseStone=True,
                StoneCount=2,
                UseStoneAllowSave=True,
                NativeOnly={"owner": name},
                EnableTimesLimit=True,
                TimesLimit=7,
                EnableTargetDrop=True,
                DropId="3001",
                UseWeeklySchedule=True,
                WeeklySchedule={"Monday": False},
            )
        self.cfg._init_config()
        for index, name in enumerate(("活动关优先", "理智作战", "剩余理智")):
            task = self.task(name)
            self.assertEqual(task["Series"], index + 1)
            self.assertTrue(task["UseMedicine"])
            self.assertEqual(task["MedicineCount"], 3)
            self.assertTrue(task["UseStone"])
            self.assertEqual(task["StoneCount"], 2)
            self.assertEqual(task["NativeOnly"], {"owner": name})
            self.assertFalse(task["EnableTimesLimit"])
            self.assertEqual(task["TimesLimit"], 7)
            self.assertFalse(task["EnableTargetDrop"])
            self.assertEqual(task["DropId"], "3001")
            self.assertFalse(task["UseWeeklySchedule"])
            self.assertFalse(task["UseOptionalStage"])

    def test_common_medicine_window_is_inherited_and_conflicts_use_saturday(self):
        for common, expected in ((7, 7), (1, 1), (None, 2)):
            with self.subTest(common=common):
                self.data = load_fixture()
                fights = [t for t in self.queue() if t["$type"] == "FightTask"]
                for index, task in enumerate(fights):
                    task["MedicineExpireDays"] = (
                        common if common is not None else index + 1
                    )
                self.cfg.set_daily_task("理智作战", "AP-5")
                self.cfg._init_config()
                for task in self.queue():
                    if task["$type"] == "FightTask":
                        self.assertEqual(task["MedicineExpireDays"], expected)
                        self.assertTrue(task["UseExpiringMedicine"])

    def test_weekly_hook_changes_only_medicine_even_for_disabled_tasks(self):
        self.cfg._init_config()
        before = copy.deepcopy(self.data)
        self.cfg.prepare_weekly_start_day(1)
        expected = before["Configurations"]["Default"]["TaskQueue"]
        for task in expected:
            if task["$type"] == "FightTask":
                task.update(UseExpiringMedicine=True, MedicineExpireDays=7)
        self.assertEqual(self.data, before)

    def test_expired_activity_keeps_code_without_switching_to_new_event(self):
        self.select()
        self.stages = ["NEW-8"]
        self.cfg._init_config()
        task = self.task("活动关优先")
        self.assertEqual(task["StagePlan"], ["AT-8"])
        self.assertFalse(task["IsEnable"])
        self.assertEqual(self.cfg._dispatch_daily("活动关卡").read(), ("AT-8", None))
        self.cfg.set_daily_task("活动关卡", "NEW-8")
        self.assertTrue(self.task("活动关优先")["IsEnable"])

    def test_expired_menu_selection_is_written_without_resource_reload(self):
        self.cfg._init_config()
        self.stages = []
        with patch.object(
            daily_mod,
            "read_activity_stages",
            side_effect=AssertionError("选择时不应重新读取活动资源"),
        ):
            self.cfg.set_daily_task("活动关卡", "AT-7")
        self.assertEqual(self.task("活动关优先")["StagePlan"], ["AT-7"])
        self.assertTrue(self.task("活动关优先")["IsEnable"])

    def test_multi_stage_plan_is_not_adopted_as_one_stage(self):
        self.select()
        self.task("理智作战")["StagePlan"] = ["AP-5", "CE-6"]
        self.assertEqual(self.cfg._dispatch_daily("理智作战").read(), (None, None))
        self.cfg._init_config()
        self.assertFalse(self.task("理智作战")["IsEnable"])
        self.assertEqual(self.task("理智作战")["StagePlan"], [""])

    def test_init_removes_duplicate_fights_but_not_same_name_other_type(self):
        self.select()
        duplicate = copy.deepcopy(self.task("理智作战"))
        duplicate["StagePlan"] = ["AP-5"]
        other = {"$type": "CustomTask", "Name": "理智作战", "IsEnable": True}
        self.queue().extend([duplicate, other])
        self.cfg._init_config()
        matching = [
            t
            for t in self.queue()
            if t["Name"] == "理智作战" and t["$type"] == "FightTask"
        ]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["StagePlan"], ["CE-6"])
        self.assertIn(other, self.queue())

    def test_native_order_places_inventory_before_normal_stages(self):
        self.queue()[:] = [
            {"$type": "StartUpTask", "Name": "唤醒"},
            {"$type": "InfrastTask", "Name": "基建"},
            {"$type": "DepotMaintainTask", "Name": "库存"},
            {"$type": "MallTask", "Name": "信用"},
        ]
        self.cfg._init_config()
        self.assertEqual(
            [t["Name"] for t in self.queue()],
            [
                "唤醒",
                "剿灭作战",
                "活动关优先",
                "基建",
                "库存",
                "理智作战",
                "剩余理智",
                "信用",
            ],
        )

    def test_empty_native_queue_can_be_initialized(self):
        self.queue().clear()
        self.cfg._init_config()
        self.assertEqual(
            [t["Name"] for t in self.queue()],
            ["剿灭作战", "活动关优先", "理智作战", "剩余理智"],
        )
        self.assertEqual(self.task("剿灭作战")["MedicineExpireDays"], 2)

    def test_custom_annihilation_selection_is_preserved(self):
        self.task("剿灭").update(
            UseCustomAnnihilation=True, AnnihilationStage="Chernobog@Annihilation"
        )
        self.cfg._init_config()
        self.assertTrue(self.task("剿灭")["UseCustomAnnihilation"])
        self.assertEqual(
            self.task("剿灭")["AnnihilationStage"], "Chernobog@Annihilation"
        )

    def test_template_copies_do_not_share_state(self):
        daily = self.cfg._dispatch_daily("理智作战")
        with patch.object(
            daily_mod,
            "load_template",
            side_effect=AssertionError("日常构造后不应重读固定模板"),
        ):
            first = daily._new_task("A")
            second = daily._new_task("B")
            first["StagePlan"].append("1-7")
            self.assertEqual(second["StagePlan"], [""])
            self.assertEqual(daily._new_task("C")["StagePlan"], [""])

    def test_named_daily_is_not_reused_as_the_mandatory_annihilation_slot(self):
        self.queue().clear()
        self.cfg.set_daily_task("理智作战", "AP-5")
        self.task("理智作战")["StagePlan"] = ["Annihilation"]
        self.cfg._init_config()
        self.assertEqual(sum(task["Name"] == "理智作战" for task in self.queue()), 1)
        self.assertTrue(self.task("剿灭作战")["IsEnable"])

    def test_gui_three_entries_select_and_disable_through_service(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        from src.config.daily_config import get_daily_map
        from src.config.task_config import get_daily_configs
        from src.gui.controllers.task_card import TaskCardController

        self.cfg._init_config()
        service = MagicMock()
        service.get_daily_map.side_effect = get_daily_map
        service.set_script_daily_task.side_effect = (
            lambda script, task_name, sequence, daily_display_name: (
                self.cfg.set_daily_task(daily_display_name, task_name, sequence)
            )
        )
        service.set_script_daily_enabled.side_effect = lambda script, daily, enabled: (
            self.cfg.set_daily_enabled(daily, enabled)
        )
        game_list = SimpleNamespace(
            current_game={"script_name": "MAA", "display_name": "粥"}
        )
        controller = TaskCardController(game_list, service, MagicMock())
        with (
            patch(
                "src.config.daily_config.load_daily_map",
                return_value={"MAA": get_daily_configs("MAA")},
            ),
            patch.object(
                daily_mod, "read_activity_stages", return_value=self.stages
            ) as reader,
        ):
            controller.build_daily_cache([])
            reader.assert_called_once_with(
                "MAA", "cache/gui/StageActivityV2.json", "config/gui.new.json"
            )
            self.assertEqual(
                [item["name"] for item in controller.daily_items],
                ["活动关卡", "理智作战", "剩余理智"],
            )
            self.assertEqual(len(controller.daily_options("理智作战")), 16)
            reader.reset_mock()
            controller.selectDaily("活动关卡", "AT-7", None)
            controller.selectDaily("理智作战", "AP-5", None)
            controller.selectDaily("剩余理智", "1-7", None)
            controller.setDailyEnabled("理智作战", False)
            controller.daily_options("活动关卡")
            reader.assert_not_called()  # 选择关卡和打开已缓存菜单都不重读资源。
        self.assertEqual(self.task("活动关优先")["StagePlan"], ["AT-7"])
        self.assertFalse(self.task("理智作战")["IsEnable"])
        self.assertTrue(self.task("剩余理智")["IsEnable"])


class TestMaaNativeDisk(unittest.TestCase):
    def test_selections_and_switches_survive_reload_without_sidecar(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config/gui.new.json"
            path.parent.mkdir()
            path.write_text(json.dumps(load_fixture()), encoding="utf-8")
            with patch(
                "src.utils.utils_sub_config.get_script_root_dir", return_value=folder
            ):
                cfg = ArknightsConfig()
                cfg._init_config()
                cfg.set_daily_task("理智作战", "AP-5")
                cfg.set_daily_enabled("理智作战", False)
                daily = ArknightsConfig()._dispatch_daily("理智作战")
                self.assertEqual(daily.read(), ("AP-5", None))
                self.assertFalse(daily.read_enabled())
                self.assertEqual(list(path.parent.iterdir()), [path])
