"""附带任务选项的回显、修改与协议校验。"""

import os
import unittest
from copy import deepcopy

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from gui.controllers.cli_game_list import valid_task_options
from gui.dialogs import SingleScriptConfigDialog
from tests.gui.helpers import get_app


def option_rows():
    return [
        {
            "id": "claim",
            "group": "领奖",
            "display_name": "邮件",
            "type": "bool",
            "value": True,
            "choices": [],
        },
        {
            "id": "mode",
            "group": "喷泉",
            "display_name": "方式",
            "type": "choice",
            "value": "coin",
            "choices": [
                {"display_name": "签到", "physical_name": "sign"},
                {"display_name": "捞币", "physical_name": "coin"},
            ],
        },
        {
            "id": "targets",
            "group": "梦魇",
            "display_name": "目标",
            "type": "multi",
            "value": ["b", "a"],
            "choices": [
                {"display_name": "甲", "physical_name": "a"},
                {"display_name": "乙", "physical_name": "b"},
            ],
        },
    ]


class TestTaskOptionsDialog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = get_app()

    def dialog(self):
        dialog = SingleScriptConfigDialog(
            "demo",
            "示例",
            "demo.exe",
            edit_view={
                "script_name": "demo",
                "script": {"display_name": "示例", "script_path": "demo.exe"},
                "weekly_timeouts": [60] * 7,
                "switches": [],
                "task_options": option_rows(),
            },
        )
        self.addCleanup(dialog.close)
        return dialog

    def test_unchanged_values_and_multi_order_are_not_submitted(self):
        dialog = self.dialog()
        self.assertTrue(dialog.option_controls["claim"].isChecked())
        self.assertEqual(dialog.option_controls["mode"].currentText(), "捞币")
        self.assertEqual(dialog._collect_task_options(), {})
        dialog.save_data()
        self.assertEqual(dialog.pending_changes.task_options, {})

    def test_save_collects_only_changes_with_physical_values(self):
        dialog = self.dialog()
        dialog.option_controls["claim"].setChecked(False)
        dialog.option_controls["mode"].setCurrentIndex(0)
        dialog.option_controls["targets"]["b"].setChecked(False)
        dialog.save_data()
        self.assertEqual(
            dialog.pending_changes.task_options,
            {"claim": False, "mode": "sign", "targets": ["a"]},
        )

    def test_cancel_does_not_submit(self):
        dialog = self.dialog()
        dialog.option_controls["claim"].setChecked(False)
        dialog.reject()
        self.assertIsNone(dialog.pending_changes)

    def test_option_labels_stay_with_controls_and_background_is_opaque(self):
        dialog = self.dialog()
        dialog.show()
        self.app.processEvents()
        checkbox = dialog.option_controls["claim"]
        self.assertEqual(checkbox.text(), "邮件")
        self.assertLess(checkbox.width(), 150)
        self.assertEqual(dialog.grab().toImage().pixelColor(5, 100).alpha(), 255)

    def test_invalid_protocol_values_are_rejected(self):
        self.assertTrue(valid_task_options(option_rows()))
        for patch in [{"type": "int"}, {"value": 1}, {"choices": None}, {"id": ""}]:
            with self.subTest(patch=patch):
                rows = deepcopy(option_rows())
                rows[0].update(patch)
                self.assertFalse(valid_task_options(rows))
