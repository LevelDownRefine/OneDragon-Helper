"""附带任务选项的回显、修改与协议校验。"""

import os
import unittest
from copy import deepcopy

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QLabel, QPushButton

from gui.controllers.cli_game_list import valid_task_options
from gui.dialogs import SingleScriptConfigDialog, task_groups
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

    def test_single_standalone_option_has_one_label_without_indentation(self):
        view = deepcopy(self.dialog()._edit_view)
        row = option_rows()[1]
        row.update(group="完成后操作", display_name="完成后操作", tasks=[])
        view["task_options"] = [row]
        dialog = SingleScriptConfigDialog("demo", "示例", "demo.exe", edit_view=view)
        self.addCleanup(dialog.close)
        labels = [
            label
            for label in dialog.findChildren(QLabel)
            if label.text() == "完成后操作"
        ]
        self.assertEqual(len(labels), 1)
        dialog.show()
        self.app.processEvents()
        label = labels[0]
        task_label = next(
            item for item in dialog.findChildren(QLabel) if item.text() == "任务:"
        )
        self.assertLess(
            abs(
                label.mapTo(dialog, label.rect().topLeft()).y()
                - task_label.mapTo(dialog, task_label.rect().topLeft()).y()
            ),
            label.height() / 2,
        )

    def test_option_labels_stay_with_controls_and_background_is_opaque(self):
        dialog = self.dialog()
        dialog.show()
        self.app.processEvents()
        checkbox = dialog.option_controls["claim"]
        self.assertEqual(checkbox.text(), "邮件")
        self.assertLess(checkbox.width(), 150)
        self.assertEqual(dialog.grab().toImage().pixelColor(5, 100).alpha(), 255)

    def test_tasks_attach_children_and_keep_unrelated_switches(self):
        rows = option_rows()
        rows[0]["tasks"] = ["领取奖励"]
        switches = [
            {"name": "领取奖励", "enabled": False},
            {"name": "一咖舍", "enabled": True},
        ]
        groups = task_groups(switches, rows)
        self.assertEqual(groups[0]["switches"], [switches[0]])
        self.assertEqual(groups[0]["options"], [rows[0]])
        self.assertEqual(groups[1]["switches"], [switches[1]])
        self.assertEqual(groups[1]["options"], [])
        self.assertEqual(len(groups), 4)

    def test_child_options_do_not_widen_the_original_form(self):
        dialog = self.dialog()
        view = deepcopy(dialog._edit_view)
        view["task_options"] = []
        original = SingleScriptConfigDialog("demo", "示例", "demo.exe", edit_view=view)
        self.addCleanup(original.close)
        original.show()
        dialog.show()
        self.app.processEvents()
        self.assertLessEqual(dialog.width(), original.width() + 12)
        self.assertLess(
            dialog.option_controls["mode"].width(), dialog.args_input.width()
        )
        self.assertEqual(dialog.minimumWidth(), dialog.maximumWidth())

    def test_task_section_nests_options_under_main_switch(self):
        dialog = self.dialog()
        dialog.close()
        view = deepcopy(dialog._edit_view)
        view["switches"] = [{"name": "领奖", "enabled": False}]
        dialog = SingleScriptConfigDialog("demo", "示例", "demo.exe", edit_view=view)
        self.addCleanup(dialog.close)
        dialog.show()
        self.app.processEvents()
        parent = dialog.switch_checks["领奖"]
        child = dialog.option_controls["claim"]
        self.assertGreater(
            child.mapTo(dialog, child.rect().topLeft()).x(),
            parent.mapTo(dialog, parent.rect().topLeft()).x(),
        )
        self.assertGreater(
            child.mapTo(dialog, child.rect().topLeft()).y(),
            parent.mapTo(dialog, parent.rect().topLeft()).y(),
        )
        labels = [label.text() for label in dialog.findChildren(QLabel)]
        self.assertIn("任务:", labels)
        self.assertNotIn("任务开关:", labels)
        self.assertNotIn("任务选项:", labels)
        self.assertTrue(child.isChecked())

    def test_inline_options_and_task_switches_have_equal_height(self):
        dialog = self.dialog()
        dialog.show()
        self.app.processEvents()
        controls = [
            dialog.option_controls["claim"],
            dialog.option_controls["mode"],
            *dialog.option_controls["targets"].values(),
        ]
        self.assertTrue(all(control.isVisible() for control in controls))
        self.assertEqual(len({control.height() for control in controls}), 1)
        self.assertEqual(controls[0].height(), controls[0].sizeHint().height())
        self.assertLess(
            dialog.option_controls["mode"].height(), dialog.args_input.height()
        )
        self.assertFalse(
            any(
                button.text() in ("设置", "收起")
                for button in dialog.findChildren(QPushButton)
            )
        )

    def test_invalid_protocol_values_are_rejected(self):
        self.assertTrue(valid_task_options(option_rows()))
        for patch in [
            {"type": "int"},
            {"value": 1},
            {"choices": None},
            {"id": ""},
            {"tasks": "任务"},
        ]:
            with self.subTest(patch=patch):
                rows = deepcopy(option_rows())
                rows[0].update(patch)
                self.assertFalse(valid_task_options(rows))

    def test_task_choice_width_follows_current_text_with_a_limit(self):
        dialog = self.dialog()
        combo = dialog.option_controls["mode"]
        self.assertEqual(combo.width(), 64)
        combo.addItem("非常长的候选名称" * 10, "long")
        combo.setCurrentIndex(combo.count() - 1)
        self.assertEqual(combo.width(), 128)
        combo.setCurrentIndex(0)
        self.assertEqual(combo.width(), 64)
