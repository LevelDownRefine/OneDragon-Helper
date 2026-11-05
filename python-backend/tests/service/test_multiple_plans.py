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
