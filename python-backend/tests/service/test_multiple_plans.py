import unittest
from unittest.mock import Mock, patch

from src.service.daily_plan import (
    DailyPlanOptions,
    DailyTaskState,
    plans_delete,
    plans_list,
    plans_save,
)


class MultiplePlansTest(unittest.TestCase):
    def setUp(self):
        self.data = {"daily_run": {"enabled": True, "target_time": "04:10"}}
        self.tasks = {}
        config = patch(
            "src.service.daily_plan.load_config", return_value={"script_list": []}
        )
        config.start()
        self.addCleanup(config.stop)

    def task(self, plan_id):
        if plan_id not in self.tasks:
            task = Mock()
            task.read.return_value = DailyTaskState()
            self.tasks[plan_id] = task
        return self.tasks[plan_id]

    @patch("src.service.daily_plan.save_schedule")
    def test_add_list_delete_preserves_old_plan(self, save):
        with patch("src.service.daily_plan.load_schedule", return_value=self.data):
            plan_id = plans_save("", "晚间", DailyPlanOptions(True, "20:00"), self.task)
            entries = plans_list(self.task)["plans"]
            self.assertEqual(
                [(x["id"], x["name"]) for x in entries],
                [("default", "默认计划"), (plan_id, "晚间")],
            )
            self.assertEqual(entries[0]["plan"]["target_time"], "04:10")
            self.assertEqual(entries[1]["plan"]["target_time"], "20:00")
            plans_delete(plan_id, self.task)
            self.assertEqual(len(plans_list(self.task)["plans"]), 1)
            self.assertTrue(self.data["daily_run"]["enabled"])
            self.assertEqual(save.call_count, 2)

    @patch("src.service.daily_plan.save_schedule", side_effect=OSError("disk full"))
    def test_failed_save_restores_windows_task(self, save):
        with (
            patch("src.service.daily_plan.load_schedule", return_value=self.data),
            patch("src.service.daily_plan.uuid.uuid4") as ident,
            self.assertRaises(OSError),
        ):
            ident.return_value.hex = "a" * 32
            plans_save("", "晚间", DailyPlanOptions(True, "20:00"), self.task)
        self.task("a" * 32).restore.assert_called_once()

    @patch("src.service.daily_plan.save_schedule")
    def test_delete_default_hides_and_disables_legacy_plan(self, save):
        with patch("src.service.daily_plan.load_schedule", return_value=self.data):
            plans_delete("default", self.task)
            self.assertEqual(plans_list(self.task)["plans"], [])
            self.assertFalse(self.data["daily_run"]["enabled"])

    def test_invalid_default_and_unknown_plan(self):
        self.data["daily_run"] = "bad"
        with patch("src.service.daily_plan.load_schedule", return_value=self.data):
            self.assertFalse(plans_list(self.task)["plans"][0]["plan"]["enabled"])
            with self.assertRaises(ValueError):
                plans_save("a" * 32, "missing", DailyPlanOptions(), self.task)

    def test_overlap_skips_execution(self):
        from updater.utils import UpdateBusyError

        from src.service.daily_plan import run_daily_plan

        with (
            patch(
                "src.service.daily_plan.load_daily_plan",
                return_value=DailyPlanOptions(True),
            ),
            patch(
                "src.service.daily_plan.load_config",
                return_value={
                    "script_list": [{"display_name": "A", "script_path": "a.py"}]
                },
            ),
            patch("updater.utils.FileLease", side_effect=UpdateBusyError("busy")),
            patch("src.service.daily_plan.chain_service.schedule_run") as run,
        ):
            run_daily_plan()
            run.assert_not_called()

    def test_selection_and_legacy_names(self):
        from src.service.daily_plan import load_daily_plan, run_daily_plan

        config = {
            "script_list": [
                {"display_name": "A", "script_path": "a.py"},
                {"display_name": "B", "script_path": "b.py"},
            ]
        }
        # 旧字段从未生效，不能在升级时改变运行范围。
        legacy = {"daily_run": {"enabled": True, "script_names": ["missing"]}}
        self.assertIsNone(load_daily_plan(legacy).selected_scripts)
        with (
            patch("src.service.daily_plan.load_schedule", return_value=legacy),
            patch("src.service.daily_plan.load_config", return_value=config),
            patch("src.service.daily_plan._run_plan_chain") as run,
        ):
            run_daily_plan()
            all_scripts = run.call_args.args[0]
            self.assertEqual(len(all_scripts), 2)
            first = next(iter(all_scripts))
            legacy["daily_run"]["selected_scripts"] = [first, "missing"]
            run_daily_plan()
            self.assertEqual(run.call_args.args[0], {first})
            legacy["daily_run"]["selected_scripts"] = []
            run.reset_mock()
            run_daily_plan()
            run.assert_not_called()

    @patch("src.service.daily_plan.save_schedule")
    def test_plan_selection_saved_and_loaded(self, save):
        with patch("src.service.daily_plan.load_schedule", return_value=self.data):
            plan_id = plans_save(
                "", "晚间", DailyPlanOptions(selected_scripts=["a"]), self.task
            )
            items = plans_list(self.task)["plans"]
            self.assertEqual(items[1]["id"], plan_id)
            self.assertEqual(items[1]["plan"]["selected_scripts"], ["a"])
            plans_save(
                "default", "默认", DailyPlanOptions(selected_scripts=[]), self.task
            )
            self.assertEqual(
                plans_list(self.task)["plans"][0]["plan"]["selected_scripts"], []
            )

    def test_invalid_selection_does_not_expand_to_all(self):
        from src.service.daily_plan import load_daily_plan

        plan = load_daily_plan(
            {"daily_run": {"enabled": True, "selected_scripts": "bad"}}
        )
        self.assertEqual(plan.selected_scripts, [])

    def test_scripts_list_uses_instance_identifier(self):
        config = {
            "script_list": [
                {"display_name": "同名", "script_path": "a.py", "script_id": "first"},
                {"display_name": "同名", "script_path": "a.py", "script_id": "second"},
                {"display_name": "独立", "script_path": "b.py", "script_id": "third"},
            ]
        }
        with (
            patch("src.service.daily_plan.load_schedule", return_value=self.data),
            patch("src.service.daily_plan.load_config", return_value=config),
        ):
            self.assertEqual(
                plans_list(self.task)["scripts"],
                [
                    {"id": "first", "display_name": "同名 (first)"},
                    {"id": "second", "display_name": "同名 (second)"},
                    {"id": "third", "display_name": "独立"},
                ],
            )
