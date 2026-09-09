"""测试 src/gui/dialogs.py：SingleScriptConfigDialog。"""

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from src.utils.utils_yaml import dump_yaml_file

# 在导入 PySide6 之前设置 offscreen 平台插件（CI 无显示器环境）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QMessageBox

from src.gui.dialogs import (
    BG_DIALOG,
    SingleScriptConfigDialog,
    _last_dir,
    pick_file,
    styled_msg_box,
)

# 全局 QApplication 实例（测试共享）
_app = QApplication.instance() or QApplication([])


class TestPickFile(unittest.TestCase):
    """pick_file：选中后记忆所在目录，取消不改记忆。"""

    def setUp(self):
        self._saved = _last_dir
        import src.gui.dialogs as dialogs_mod

        dialogs_mod._last_dir = ""
        self._mod = dialogs_mod

    def tearDown(self):
        self._mod._last_dir = self._saved

    def test_remembers_directory_on_success(self):
        first = [("C:/games/run.exe", "")]
        second = [("D:/apps/tool.py", "")]

        def success(*a, **k):
            return first.pop(0)

        def cancel(*a, **k):
            return second.pop(0)

        with (
            patch("src.gui.dialogs.QFileDialog.getOpenFileName", side_effect=success),
        ):
            self.assertEqual(pick_file(None, "t", "*.exe"), "C:/games/run.exe")
        self.assertEqual(self._mod._last_dir, "C:/games")
        with (
            patch(
                "src.gui.dialogs.QFileDialog.getOpenFileName",
                side_effect=cancel,
            ),
        ):
            self.assertEqual(pick_file(None, "t", "*.exe"), "D:/apps/tool.py")
        self.assertEqual(self._mod._last_dir, "D:/apps")

    def test_cancel_keeps_last_dir(self):
        with patch(
            "src.gui.dialogs.QFileDialog.getOpenFileName", return_value=("", "")
        ):
            self.assertEqual(pick_file(None, "t", "*.exe"), "")
        self.assertEqual(self._mod._last_dir, "")

    def test_next_dialog_starts_from_last_dir(self):
        with patch(
            "src.gui.dialogs.QFileDialog.getOpenFileName",
            return_value=("C:/a/b.exe", ""),
        ):
            pick_file(None, "t", "*.exe")
        with patch(
            "src.gui.dialogs.QFileDialog.getOpenFileName", return_value=("", "")
        ) as mock_dialog:
            pick_file(None, "t", "*.exe")
        self.assertEqual(mock_dialog.call_args[0][2], "C:/a")


class TestSingleScriptConfigDialogLoad(unittest.TestCase):
    """测试 SingleScriptConfigDialog.load_data 默认值行为。"""

    def _make_weekly_file(self, weekly_map):
        d = tempfile.mkdtemp()
        wt = os.path.join(d, "weekly.yml")
        dump_yaml_file(wt, {"weekly_start": {}, "weekly_timeouts": weekly_map})
        return wt

    def _make_config_file(self):
        """构造一个最小、存在的 config.yml 供对话框读取（对话框依赖 config.yml 已存在）。"""
        d = tempfile.mkdtemp()
        cfg = os.path.join(d, "config.yml")
        dump_yaml_file(cfg, {"script_list": []})
        return cfg

    def test_load_seeds_from_default_when_no_weekly_entry(self):
        """weekly.yml 的 weekly_timeouts 无该脚本条目时，7 格应显示 DEFAULT_RUN_TIMEOUT（3600）"""
        wt = self._make_weekly_file({})
        cfg = self._make_config_file()
        with (
            patch(
                "src.utils.utils_config.require_config_yml_path",
                return_value=cfg,
            ),
            patch(
                "src.utils.utils_weekly.get_weekly_yml_path_under_root",
                return_value=wt,
            ),
        ):
            dlg = SingleScriptConfigDialog("collect_log", "日志分析", "C:/x.py")
            values = [le.text() for le in dlg.timeout_inputs]
        self.assertEqual(values, ["3600"] * 7)

    def test_load_uses_existing_weekly_entry(self):
        """weekly.yml 的 weekly_timeouts 已有条目时使用已有值"""
        wt = self._make_weekly_file({"collect_log": [60, 60, 60, 60, 60, 60, 60]})
        cfg = self._make_config_file()
        with (
            patch(
                "src.utils.utils_config.require_config_yml_path",
                return_value=cfg,
            ),
            patch(
                "src.utils.utils_weekly.get_weekly_yml_path_under_root",
                return_value=wt,
            ),
        ):
            dlg = SingleScriptConfigDialog("collect_log", "日志分析", "C:/x.py")
            values = [le.text() for le in dlg.timeout_inputs]
        self.assertEqual(values, ["60"] * 7)

    def test_init_asserts_when_config_yml_missing(self):
        """config.yml 缺失属内部错误：构造对话框必须 assert，而非静默返回空数据"""
        with (
            patch(
                "src.utils.utils_config.require_config_yml_path",
                side_effect=AssertionError("config.yml 缺失"),
            ),
            self.assertRaises(AssertionError),
        ):
            SingleScriptConfigDialog("collect_log", "日志分析", "C:/x.py")


class TestSingleScriptConfigDialogBlock(unittest.TestCase):
    """测试 block 字段在配置弹窗的加载与保存。"""

    def _make_config_file(self, script_list):
        d = tempfile.mkdtemp()
        cfg = os.path.join(d, "config.yml")
        dump_yaml_file(cfg, {"script_list": script_list})
        return cfg

    def test_load_sets_block_from_config(self):
        """config 中 block=True 时复选框应被勾选（阻塞）"""
        cfg = self._make_config_file(
            [
                {
                    "display_name": "日志分析",
                    "script_type": "python",
                    "script_path": "C:/x.py",
                    "block": True,
                },
            ]
        )
        with patch(
            "src.utils.utils_config.require_config_yml_path",
            return_value=cfg,
        ):
            dlg = SingleScriptConfigDialog("collect_log", "日志分析", "C:/x.py")
        self.assertTrue(dlg.block_cb.isChecked())

    def test_load_defaults_block_true_when_missing(self):
        """缺 block 字段时默认勾选（阻塞）"""
        cfg = self._make_config_file(
            [
                {
                    "display_name": "日志分析",
                    "script_type": "python",
                    "script_path": "C:/x.py",
                },
            ]
        )
        with patch(
            "src.utils.utils_config.require_config_yml_path",
            return_value=cfg,
        ):
            dlg = SingleScriptConfigDialog("collect_log", "日志分析", "C:/x.py")
        self.assertTrue(dlg.block_cb.isChecked())

    def test_save_stores_block_in_pending_changes(self):
        """保存时把复选框状态存到 pending_changes['config_patch']['block']（不再直接写盘）。"""
        cfg = self._make_config_file(
            [
                {
                    "display_name": "日志分析",
                    "script_type": "python",
                    "script_path": "C:/y.py",
                },
            ]
        )
        with (
            patch(
                "src.utils.utils_config.require_config_yml_path",
                return_value=cfg,
            ),
            patch("src.gui.dialogs.styled_msg_box"),
            patch.object(SingleScriptConfigDialog, "accept"),
        ):
            dlg = SingleScriptConfigDialog("日志分析", "日志分析", "C:/y.py")
            dlg.block_cb.setChecked(False)
            dlg.save_data()
        self.assertFalse(dlg.pending_changes["config_patch"]["block"])
        self.assertEqual(dlg.pending_changes["new_display_name"], "日志分析")


class _FakeService:
    """极简 AppService 替身：供弹窗构造时读取脚本数据，避免依赖真实 config。"""

    def __init__(
        self, script_type, script_path, display_name="日志分析", weekly_start=None
    ):
        self._data = {
            "script_type": script_type,
            "script_path": script_path,
            "display_name": display_name,
        }
        self._weekly_start = weekly_start

    def get_script(self, name):
        return self._data

    def weekly_inputs(self, name):
        return [3600] * 7

    def get_weekly_start(self, script_name):
        return self._weekly_start


class TestSingleScriptConfigDialogWeeklyStart(unittest.TestCase):
    """测试配置弹窗的「周几起」行：仅支持周常脚本显示，读写 weekly.yml 的 weekly_start 段。"""

    def _make_dialog(self, script_name, display_name, weekly_start, supported):
        with patch("src.gui.dialogs.supports_weekly", return_value=supported):
            return SingleScriptConfigDialog(
                script_name,
                display_name,
                "C:/games/run.exe",
                app_service=_FakeService(
                    "external", "C:/games/run.exe", display_name, weekly_start
                ),
            )

    def test_hidden_when_weekly_unsupported(self):
        """不支持周常的脚本周几起行应隐藏。

        combo 以 dialog 为父控件，仅「不进布局」不够——未布局的子控件会按默认
        位置 (0,0) 绘制并盖住左上角字段。必须 isHidden() 为真（未 show 的 dialog
        上 isVisible() 恒为 False，断不出这个 bug）。
        """
        dlg = self._make_dialog("collect_log", "日志分析", None, supported=False)
        self.assertFalse(dlg._weekly_start_supported)
        self.assertTrue(dlg.weekly_start_combo.isHidden())

    def test_visible_and_loaded_when_weekly_supported(self):
        """支持周常的脚本周几起行可见，且加载 weekly_start.yml 的 weekly_start"""
        dlg = self._make_dialog("run", "鸣潮", 3, supported=True)
        self.assertTrue(dlg._weekly_start_supported)
        # 未 show 时 isVisible 受父链影响为 False，用 isHidden 反映自身 visible 属性
        self.assertFalse(dlg.weekly_start_combo.isHidden())
        # combo index 3 → 周三起
        self.assertEqual(dlg.weekly_start_combo.currentIndex(), 3)

    def test_save_defers_weekly_start_to_pending_changes(self):
        """保存时周几起只暂存到 pending_changes，不在弹窗内写盘

        weekly.yml weekly_start 段与游戏侧原生 config 的落盘统一归
        AppService.update_script（游戏侧须在 config.yml 落盘新路径后）。
        """
        dlg = self._make_dialog("run", "鸣潮", None, supported=True)
        dlg.weekly_start_combo.setCurrentIndex(3)
        with (
            patch("src.gui.dialogs.styled_msg_box"),
            patch.object(SingleScriptConfigDialog, "accept"),
        ):
            dlg.save_data()
        self.assertEqual(dlg.pending_changes["weekly_start_day"], 3)

    def test_save_clears_weekly_start_when_unset(self):
        """选择「不设置」时 pending_changes 记为 None（update_script 据此清 weekly.yml 条目）"""
        dlg = self._make_dialog("run", "鸣潮", 5, supported=True)
        dlg.weekly_start_combo.setCurrentIndex(0)
        with (
            patch("src.gui.dialogs.styled_msg_box"),
            patch.object(SingleScriptConfigDialog, "accept"),
        ):
            dlg.save_data()
        self.assertIsNone(dlg.pending_changes["weekly_start_day"])


class TestGameProcessInputAlwaysEnabled(unittest.TestCase):
    """游戏进程输入框应始终可编辑，不受「结束后关闭游戏」复选框门控。

    早期实现默认禁用，需先勾选「结束后关闭游戏」才启用，导致用户误以为无法填写。
    现改为始终可编辑，仅在勾选关闭游戏且留空时才提示必填。
    """

    def _make_dialog(self, script_data):
        app = MagicMock()
        app.get_script.return_value = script_data
        app.weekly_inputs.return_value = [3600] * 7
        app.get_weekly_start.return_value = None
        return SingleScriptConfigDialog(
            "collect_log", "日志分析", "C:/x.py", app_service=app
        )

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
        app = MagicMock()
        # 仅本脚本标识命中：新标识（改名后）返回 None，避免走进「已存在同标识」分支。
        app.get_script.side_effect = lambda name: (
            script_data if name == "collect_log" else None
        )
        app.weekly_inputs.return_value = [3600] * 7
        app.get_weekly_start.return_value = None
        return SingleScriptConfigDialog(
            "collect_log", "日志分析", "C:/x.py", app_service=app
        )

    def test_load_restores_game_path(self):
        """打开弹窗时回填条目里已存的 game_path。"""
        dlg = self._make_dialog({"game_path": "C:/games/Endfield.exe"})
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
            with (
                patch("src.gui.dialogs.styled_msg_box") as warn,
                patch.object(SingleScriptConfigDialog, "accept"),
            ):
                dlg.save_data()
        finally:
            os.unlink(path)
        warn.assert_not_called()
        self.assertEqual(dlg.pending_changes["config_patch"]["game_path"], path)

    def test_save_blocks_when_path_not_exists(self):
        """填了但文件不存在 → 弹警告并中止保存（不进 accept）。"""
        dlg = self._make_dialog({})
        dlg.game_path_input.setText("D:/not/exist/Endfield.exe")
        with (
            patch("src.gui.dialogs.styled_msg_box") as warn,
            patch.object(SingleScriptConfigDialog, "accept") as accept,
        ):
            dlg.save_data()
        warn.assert_called_once()
        accept.assert_not_called()

    def test_empty_skips_existence_check(self):
        """留空是合法值，不触发存在性校验。"""
        dlg = self._make_dialog({})
        with (
            patch("src.gui.dialogs.styled_msg_box") as warn,
            patch.object(SingleScriptConfigDialog, "accept"),
        ):
            dlg.save_data()
        self.assertEqual(dlg.pending_changes["config_patch"]["game_path"], "")
        warn.assert_not_called()


class TestFramelessDialogs(unittest.TestCase):
    """弹窗去系统标题栏、透明圆角（无边框深色，四角透出桌面）；空白处可拖动。"""

    def _assert_round(self, dlg):
        """无边框 + 透明背景 + 圆角深底样式三件套。"""
        self.assertTrue(dlg.windowFlags() & Qt.FramelessWindowHint)
        self.assertTrue(dlg.testAttribute(Qt.WA_TranslucentBackground))
        self.assertIn("border-radius", dlg.styleSheet())
        self.assertIn(BG_DIALOG, dlg.styleSheet())
        dlg.show()
        _app.processEvents()
        # 顶部空白的真实绘制像素必须半透明，不能仅设置透明窗口属性。
        image = dlg.grab().toImage()
        self.assertEqual(image.pixelColor(image.width() // 2, 3).alpha(), 235)
        self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
        self.assertEqual(dlg.windowOpacity(), 1.0)
        self.assertEqual(QColor(BG_DIALOG).alpha(), 235)

    def _single_script_dialog(self):
        app = MagicMock()
        app.get_script.return_value = {}
        app.weekly_inputs.return_value = [3600] * 7
        app.get_weekly_start.return_value = None
        dlg = SingleScriptConfigDialog(
            "collect_log", "日志分析", "C:/x.py", app_service=app
        )
        self.addCleanup(dlg.close)
        return dlg

    def test_single_script_dialog_frameless(self):
        self._assert_round(self._single_script_dialog())

    def test_run_confirm_dialog_frameless(self):
        from src.gui.run_confirm_dialog import RunConfirmDialog
        from src.service.schedule import RunOptions

        dlg = RunConfirmDialog(1, RunOptions())
        self.addCleanup(dlg.close)
        self._assert_round(dlg)

    def test_countdown_dialog_frameless(self):
        from src.gui.shutdown_dialog import ShutdownConfirmDialog

        dlg = ShutdownConfirmDialog(10)
        self.addCleanup(dlg.close)
        self._assert_round(dlg)

    def test_startup_dialog_translucent(self):
        from src.gui.startup_dialog import StartupConfirmDialog

        dlg = StartupConfirmDialog(60)
        self.addCleanup(dlg.close)
        self._assert_round(dlg)

    def test_config_dialog_translucent(self):
        from src.gui.config_dialog import ConfigDialog

        dlg = ConfigDialog()
        self.addCleanup(dlg.close)
        self._assert_round(dlg)

    def test_styled_msg_box_frameless_and_styled(self):
        box = styled_msg_box(None, QMessageBox.Warning, "标题", "内容")
        self.addCleanup(box.close)
        self._assert_round(box)


if __name__ == "__main__":
    unittest.main()
