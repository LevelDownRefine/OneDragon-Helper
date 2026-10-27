"""测试 src/gui/dialogs.py：SingleScriptConfigDialog。"""

import os
import tempfile
import unittest
from unittest.mock import Mock, patch

# 在导入 PySide6 之前设置 offscreen 平台插件（CI 无显示器环境）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QMessageBox

from gui.dialogs import (
    BG_DIALOG,
    SingleScriptConfigDialog,
    _last_dir,
    pick_file,
    styled_msg_box,
)

# 全局 QApplication 实例（测试共享）
_app = QApplication.instance() or QApplication([])


def _edit_view(script_data=None, *, timeouts=None, switches=None):
    return {
        "script_name": "collect_log",
        "script": {} if script_data is None else script_data,
        "weekly_timeouts": [3600] * 7 if timeouts is None else timeouts,
        "switches": [] if switches is None else switches,
        "task_options": [],
    }


class TestPickFile(unittest.TestCase):
    """pick_file：选中后记忆所在目录，取消不改记忆。"""

    def setUp(self):
        self._saved = _last_dir
        import gui.dialogs as dialogs_mod

        dialogs_mod._last_dir = ""
        self._mod = dialogs_mod

    def tearDown(self):
        self._mod._last_dir = self._saved

    def test_selection_remembers_directory_and_cancel_preserves_it(self):
        for selected, initial, retained in (
            ("", "", ""),
            ("C:/games/run.exe", "", "C:/games"),
            ("", "C:/games", "C:/games"),
            ("D:/apps/tool.py", "C:/games", "D:/apps"),
        ):
            with (
                self.subTest(selected=selected, initial=initial),
                patch(
                    "gui.dialogs.QFileDialog.getOpenFileName",
                    return_value=(selected, ""),
                ) as picker,
            ):
                self.assertEqual(pick_file(None, "t", "*.exe"), selected)
                self.assertEqual(picker.call_args.args[2], initial)
                self.assertEqual(self._mod._last_dir, retained)


class TestSingleScriptConfigDialogLoad(unittest.TestCase):
    def test_weekly_timeout_loads_supplied_values_without_reading_config(self):
        for timeouts in ([3600] * 7, [60] * 7):
            with (
                self.subTest(timeouts=timeouts),
                patch(
                    "src.utils.utils_config.load_config",
                    side_effect=AssertionError("no reads"),
                ),
            ):
                dialog = SingleScriptConfigDialog(
                    "collect_log",
                    "日志分析",
                    "C:/x.py",
                    edit_view=_edit_view(timeouts=timeouts),
                    submit=Mock(),
                )
                self.addCleanup(dialog.close)
                self.assertEqual(
                    [edit.text() for edit in dialog.timeout_inputs],
                    [str(value) for value in timeouts],
                )

    def test_edit_view_and_external_submit_are_required(self):
        with self.assertRaises(TypeError):
            SingleScriptConfigDialog("collect_log", "日志分析", "C:/x.py")
        with self.assertRaises(TypeError):
            SingleScriptConfigDialog(
                "collect_log", "日志分析", "C:/x.py", edit_view=_edit_view()
            )


class TestNoLogSettings(unittest.TestCase):
    def dialog(self, **fields):
        dialog = SingleScriptConfigDialog(
            "demo",
            "示例",
            "C:/demo.exe",
            edit_view={
                "script": {"script_type": "external", "block": True, **fields},
                "weekly_timeouts": [3600] * 7,
                "switches": [],
            },
            submit=Mock(),
        )
        self.addCleanup(dialog.close)
        return dialog

    def test_load_edit_and_emit_no_log_settings(self):
        dialog = self.dialog(no_log_timeout_seconds=300, no_log_max_retries=1)
        self.assertEqual(dialog.no_log_timeout_input.text(), "300")
        self.assertEqual(dialog.no_log_retries_input.text(), "1")
        dialog.no_log_timeout_input.setText("600")
        dialog.no_log_retries_input.setText("0")
        emitted = []
        dialog.saveRequested.connect(emitted.append)
        dialog.save_data()
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0].config_patch["no_log_timeout_seconds"], 600)
        self.assertEqual(emitted[0].config_patch["no_log_max_retries"], 0)

    def test_disabled_controls_preserve_values_and_follow_run_mode(self):
        dialog = self.dialog(no_log_timeout_seconds=300, no_log_max_retries=1)
        self.assertTrue(dialog.no_log_timeout_input.isEnabled())
        self.assertTrue(dialog.no_log_retries_input.isEnabled())
        dialog.block_cb.setChecked(False)
        self.assertFalse(dialog.no_log_timeout_input.isEnabled())
        self.assertFalse(dialog.no_log_retries_input.isEnabled())
        dialog.block_cb.setChecked(True)
        dialog.type_combo.setCurrentText("python")
        self.assertFalse(dialog.no_log_timeout_input.isEnabled())
        dialog.type_combo.setCurrentText("external")
        self.assertEqual(dialog.no_log_timeout_input.text(), "300")
        self.assertTrue(dialog.no_log_retries_input.isEnabled())
        dialog.no_log_timeout_input.setText("0")
        self.assertTrue(dialog.no_log_timeout_input.isEnabled())
        self.assertFalse(dialog.no_log_retries_input.isEnabled())
        self.assertEqual(dialog.no_log_retries_input.text(), "1")
        dialog.reject()
        self.assertIsNone(dialog.pending_changes)

    def test_invalid_numbers_keep_form_open_without_emitting_save(self):
        for field in ("no_log_timeout_input", "no_log_retries_input"):
            for value in ("", "-1"):
                with self.subTest(field=field, value=value):
                    dialog = self.dialog(no_log_timeout_seconds=300)
                    getattr(dialog, field).setText(value)
                    emitted = []
                    dialog.saveRequested.connect(emitted.append)
                    with patch("gui.dialogs.show_warning") as warning:
                        dialog.save_data()
                    warning.assert_called_once()
                    self.assertEqual(emitted, [])
                    self.assertIsNone(dialog.pending_changes)


class TestSingleScriptConfigDialogBlock(unittest.TestCase):
    def test_block_loads_explicit_value_or_defaults_to_true(self):
        for saved, expected in (
            ({}, True),
            ({"block": True}, True),
            ({"block": False}, False),
        ):
            with self.subTest(saved=saved):
                dialog = SingleScriptConfigDialog(
                    "collect_log",
                    "日志分析",
                    "C:/x.py",
                    edit_view=_edit_view(saved),
                    submit=Mock(),
                )
                self.addCleanup(dialog.close)
                self.assertEqual(dialog.block_cb.isChecked(), expected)

    def test_save_submits_block_and_waits_for_ack(self):
        submit = Mock()
        dialog = SingleScriptConfigDialog(
            "collect_log",
            "日志分析",
            "C:/x.py",
            edit_view=_edit_view(),
            submit=submit,
        )
        self.addCleanup(dialog.close)
        dialog.show()
        dialog.block_cb.setChecked(False)
        dialog.save_data()
        submit.assert_called_once_with(dialog.pending_changes)
        self.assertFalse(dialog.pending_changes.config_patch["block"])
        self.assertEqual(dialog.pending_changes.display_name, "日志分析")
        self.assertTrue(dialog.isVisible())


class TestGameProcessInputAlwaysEnabled(unittest.TestCase):
    """游戏进程输入框应始终可编辑，不受「结束后关闭游戏」复选框门控。

    早期实现默认禁用，需先勾选「结束后关闭游戏」才启用，导致用户误以为无法填写。
    现改为始终可编辑，仅在勾选关闭游戏且留空时才提示必填。
    """

    def _make_dialog(self, script_data):
        dialog = SingleScriptConfigDialog(
            "collect_log",
            "日志分析",
            "C:/x.py",
            edit_view=_edit_view(script_data),
            submit=Mock(),
        )
        self.addCleanup(dialog.close)
        return dialog

    def test_enabled_after_construct(self):
        """构造后游戏进程框即可用"""
        dlg = self._make_dialog({})
        self.assertTrue(dlg.game_process_input.isEnabled())

    def test_enabled_when_kill_game_false(self):
        """未勾选「结束后关闭游戏」时仍可用"""
        dlg = self._make_dialog({"kill_game_after_done": False})
        self.assertTrue(dlg.game_process_input.isEnabled())

    def test_enabled_when_kill_game_true(self):
        """勾选「结束后关闭游戏」后仍可用，且正确回填进程名"""
        dlg = self._make_dialog(
            {"kill_game_after_done": True, "game_process_name": "YuanShen.exe"}
        )
        self.assertTrue(dlg.game_process_input.isEnabled())
        self.assertEqual(dlg.game_process_input.text(), "YuanShen.exe")


class TestGamePathInput(unittest.TestCase):
    """测试配置弹窗的「游戏路径」行：读写条目的 game_path。

    非空时 runner 会在启动本脚本前先打开该游戏；留空表示由脚本 / 启动器自行负责。
    目前只有 MaaEnd 这类不会自启游戏的脚本需要。
    """

    def _make_dialog(self, script_data):
        dialog = SingleScriptConfigDialog(
            "collect_log",
            "日志分析",
            "C:/x.py",
            edit_view=_edit_view(script_data),
            submit=Mock(),
        )
        self.addCleanup(dialog.close)
        return dialog

    def test_load_restores_game_path(self):
        """打开弹窗时回填条目里已存的 game_path。"""
        dlg = self._make_dialog(
            {
                "game_path": "C:/games/Endfield.exe",
                "game_arguments": '--profile "中文 空格"',
            }
        )
        self.assertEqual(dlg.game_args_input.text(), '--profile "中文 空格"')
        self.assertEqual(dlg.game_path_input.text(), "C:/games/Endfield.exe")

    def test_load_defaults_empty(self):
        """条目无 game_path 时留空（多数脚本不需要）。"""
        dlg = self._make_dialog({})
        self.assertEqual(dlg.game_path_input.text(), "")

    def test_save_stores_game_path(self):
        """路径存在时正常存入 pending_changes 的 config_patch。"""
        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as tf:
            path = tf.name
        try:
            dlg = self._make_dialog({})
            dlg.game_path_input.setText(path)
            dlg.game_args_input.setText('--profile "中文 空格"')
            with (
                patch("gui.dialogs.styled_msg_box") as warn,
                patch.object(SingleScriptConfigDialog, "accept"),
            ):
                dlg.save_data()
        finally:
            os.unlink(path)
        warn.assert_not_called()
        self.assertEqual(dlg.pending_changes.config_patch["game_path"], path)
        self.assertEqual(
            dlg.pending_changes.config_patch["game_arguments"], '--profile "中文 空格"'
        )

    def test_missing_path_is_submitted_for_server_validation(self):
        dialog = self._make_dialog({})
        dialog.game_path_input.setText("D:/not/exist/Endfield.exe")
        submitted = Mock()
        dialog.saveRequested.connect(submitted)
        with patch.object(dialog, "accept") as accept:
            dialog.save_data()
        submitted.assert_called_once_with(dialog.pending_changes)
        self.assertEqual(
            dialog.pending_changes.config_patch["game_path"],
            "D:/not/exist/Endfield.exe",
        )
        accept.assert_not_called()

    def test_empty_skips_existence_check(self):
        """留空是合法值，不触发存在性校验。"""
        dlg = self._make_dialog({})
        with (
            patch("gui.dialogs.styled_msg_box") as warn,
            patch.object(SingleScriptConfigDialog, "accept"),
        ):
            dlg.save_data()
        self.assertEqual(dlg.pending_changes.config_patch["game_path"], "")
        warn.assert_not_called()

    def test_invalid_form_stays_open_without_pending_write(self):
        for field, value in (
            ("timeout", "86401"),
            ("timeout", "1.5"),
        ):
            with self.subTest(field=field, value=value):
                dlg = self._make_dialog({})
                self.addCleanup(dlg.close)
                edit = (
                    dlg.timeout_inputs[0] if field == "timeout" else getattr(dlg, field)
                )
                edit.setText(value)
                with (
                    patch("gui.dialogs.show_warning") as warn,
                    patch.object(dlg, "accept") as accept,
                ):
                    dlg.save_data()
                warn.assert_called_once()
                accept.assert_not_called()
                self.assertIsNone(dlg.pending_changes)


class TestSingleScriptConfigDialogSwitches(unittest.TestCase):
    """任务开关区：按服务给出的清单建行、回显勾选态、随保存回传。"""

    def _make_dialog(self, switches):
        dialog = SingleScriptConfigDialog(
            "BetterGI",
            "原神",
            "C:/BetterGI.exe",
            edit_view=_edit_view(timeouts=[60] * 7, switches=switches),
            submit=Mock(),
        )
        self.addCleanup(dialog.close)
        return dialog

    def test_rows_render_with_checked_state(self):
        """逐行一个复选框，行名取任务名、勾选态取当前开关。"""
        dlg = self._make_dialog(
            [
                {"name": "领取邮件", "enabled": True},
                {"name": "周常", "enabled": False},
            ]
        )
        self.assertEqual(list(dlg.switch_checks), ["领取邮件", "周常"])
        self.assertEqual(
            [cb.isChecked() for cb in dlg.switch_checks.values()], [True, False]
        )

    def test_save_returns_target_states(self):
        dlg = self._make_dialog(
            [
                {"name": "领取邮件", "enabled": True},
                {"name": "周常", "enabled": False},
            ]
        )
        dlg.switch_checks["周常"].setChecked(True)
        dlg.save_data()
        assert dlg.pending_changes is not None
        self.assertEqual(dlg.pending_changes.switches, {"领取邮件": True, "周常": True})

    def test_no_section_when_script_has_no_switches(self):
        dialog = self._make_dialog([])
        dialog.save_data()
        self.assertEqual(dialog.switch_checks, {})
        self.assertEqual(dialog.pending_changes.switches, {})


class TestFramelessDialogs(unittest.TestCase):
    """弹窗去系统标题栏、透明圆角（无边框深色，四角透出桌面）；空白处可拖动。"""

    def _assert_round(self, dlg, alpha=235):
        """无边框 + 透明背景 + 圆角深底样式三件套。"""
        self.assertTrue(dlg.windowFlags() & Qt.FramelessWindowHint)
        self.assertTrue(dlg.testAttribute(Qt.WA_TranslucentBackground))
        self.assertIn("border-radius", dlg.styleSheet())
        self.assertIn(BG_DIALOG, dlg.styleSheet())
        dlg.show()
        _app.processEvents()
        # 验证实际背景透明度与透明圆角。
        image = dlg.grab().toImage()
        self.assertEqual(image.pixelColor(image.width() // 2, 3).alpha(), alpha)
        self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
        self.assertEqual(dlg.windowOpacity(), 1.0)
        self.assertEqual(QColor(BG_DIALOG).alpha(), 235)

    def _single_script_dialog(self):
        dialog = SingleScriptConfigDialog(
            "collect_log",
            "日志分析",
            "C:/x.py",
            edit_view=_edit_view(),
            submit=Mock(),
        )
        self.addCleanup(dialog.close)
        return dialog

    def test_single_script_dialog_frameless(self):
        self._assert_round(self._single_script_dialog(), alpha=255)

    def test_run_confirm_dialog_frameless(self):
        from gui.run_confirm_dialog import RunConfirmDialog
        from src.service.schedule import RunOptions

        dlg = RunConfirmDialog(1, RunOptions())
        self.addCleanup(dlg.close)
        self._assert_round(dlg)

    def test_countdown_dialog_frameless(self):
        from gui.shutdown_dialog import ShutdownConfirmDialog

        dlg = ShutdownConfirmDialog(10)
        self.addCleanup(dlg.close)
        self._assert_round(dlg)

    def test_startup_dialog_translucent(self):
        from gui.startup_dialog import StartupConfirmDialog

        dlg = StartupConfirmDialog(60)
        self.addCleanup(dlg.close)
        self._assert_round(dlg)

    def test_config_dialog_translucent(self):
        from gui.config_dialog import ConfigDialog

        dlg = ConfigDialog()
        self.addCleanup(dlg.close)
        self._assert_round(dlg)

    def test_styled_msg_box_frameless_and_styled(self):
        box = styled_msg_box(None, QMessageBox.Warning, "标题", "内容")
        self.addCleanup(box.close)
        self._assert_round(box)


if __name__ == "__main__":
    unittest.main()
