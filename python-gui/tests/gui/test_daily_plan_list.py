"""计划列表展示和选择操作。"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from gui.daily_plan_dialog import DailyPlanListDialog  # noqa: E402

_APP = QApplication.instance() or QApplication([])


class TestDailyPlanList(unittest.TestCase):
    def test_stopped_plan_with_existing_task_is_inconsistent(self):
        dialog = DailyPlanListDialog()
        self.addCleanup(dialog.deleteLater)
        for task_enabled in (False, True):
            with self.subTest(task_enabled=task_enabled):
                dialog.set_plans(
                    [
                        {
                            "id": "default",
                            "name": "计划",
                            "plan": {"enabled": False, "target_time": "04:10"},
                            "state": {"exists": True, "enabled": task_enabled},
                            "state_error": None,
                        }
                    ]
                )
                self.assertIn("系统任务不一致", dialog.list_widget.item(0).text())

    def test_list_selects_plan_and_displays_system_state(self):
        dialog = DailyPlanListDialog()
        self.addCleanup(dialog.deleteLater)
        dialog.set_plans(
            [
                {
                    "id": "default",
                    "name": "早间",
                    "plan": {"enabled": True, "target_time": "04:10"},
                    "state": {
                        "exists": True,
                        "enabled": True,
                        "target_time": "04:10",
                        "entry_matches": True,
                    },
                    "state_error": None,
                },
                {
                    "id": "second",
                    "name": "晚间",
                    "plan": {"enabled": False, "target_time": "20:00"},
                    "state": {"exists": False},
                    "state_error": None,
                },
            ]
        )
        self.assertIn("系统任务正常", dialog.list_widget.item(0).text())
        self.assertIn("停用", dialog.list_widget.item(1).text())
        selected = []
        dialog.editRequested.connect(selected.append)
        dialog.list_widget.setCurrentRow(1)
        dialog._selected(dialog.editRequested)
        self.assertEqual(selected, ["second"])
