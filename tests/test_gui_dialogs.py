"""测试 src/gui/dialogs.py：配置确认回调与 SingleScriptConfigDialog。"""

import os
import tempfile
import unittest
from unittest.mock import patch

from src.utils_yaml import dump_yaml_file

# 在导入 PySide6 之前设置 offscreen 平台插件（CI 无显示器环境）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from src.gui.dialogs import (
    SingleScriptConfigDialog,
    inject_config_confirm,
)

# 全局 QApplication 实例（测试共享）
_app = QApplication.instance() or QApplication([])


class TestInjectConfigConfirm(unittest.TestCase):
    """测试 inject_config_confirm：把 GUI 确认弹窗注入 config 层回调"""

    def setUp(self):
        from src.config.set_config import ScriptConfig

        self.original = ScriptConfig.confirm_before_save
        self.addCleanup(self._restore)

    def _restore(self):
        from src.config.set_config import ScriptConfig

        ScriptConfig.confirm_before_save = self.original

    def test_inject_sets_callback(self):
        """注入后 ScriptConfig.confirm_before_save 指向 GUI 弹窗回调"""
        from src.config.set_config import ScriptConfig

        inject_config_confirm()
        callback = ScriptConfig.confirm_before_save
        self.assertIsNotNone(callback)
        # 回调是可调用函数且签名只收 display_name（描述符绑定回归防护）
        with (
            patch("src.gui.dialogs.QMessageBox") as mock_box,
            patch("src.gui.dialogs.QTimer.singleShot") as mock_timer,
        ):
            mock_box.Yes = QMessageBox.Yes
            instance = mock_box.return_value
            instance.exec.return_value = None
            instance.result.return_value = QMessageBox.Yes
            result = callback("测试脚本")
        self.assertTrue(result)
        self.assertEqual(
            instance.setText.call_args[0][0],
            "「测试脚本」的配置文件与模板不一致，是否更新并保存？",
        )
        # 限时 30 秒
        mock_timer.assert_called_once()
        self.assertEqual(mock_timer.call_args[0][0], 30_000)

    def test_inject_callback_returns_false_on_no(self):
        """用户点 No 时回调返回 False（对应 config 层 enabled 置 False）"""
        from src.config.set_config import ScriptConfig

        inject_config_confirm()
        callback = ScriptConfig.confirm_before_save
        with (
            patch("src.gui.dialogs.QMessageBox") as mock_box,
            patch("src.gui.dialogs.QTimer.singleShot"),
        ):
            mock_box.No = QMessageBox.No
            instance = mock_box.return_value
            instance.exec.return_value = None
            instance.result.return_value = QMessageBox.No
            self.assertFalse(callback("测试脚本"))

    def test_timeout_auto_rejects(self):
        """超时未选择 → 自动按拒绝（done(No)）处理，回调返回 False"""
        from src.config.set_config import ScriptConfig

        inject_config_confirm()
        callback = ScriptConfig.confirm_before_save
        with (
            patch("src.gui.dialogs.QMessageBox") as mock_box,
            patch("src.gui.dialogs.QTimer.singleShot") as mock_timer,
        ):
            mock_box.No = QMessageBox.No
            instance = mock_box.return_value
            instance.exec.return_value = None
            instance.result.return_value = QMessageBox.No
            # 模拟超时：singleShot 的延时回调立即触发（box.done(No)）
            mock_timer.side_effect = lambda _ms, fn: fn()
            result = callback("测试脚本")
        self.assertFalse(result)
        instance.done.assert_called_once_with(QMessageBox.No)

    def test_timeout_real_auto_closes(self):
        """真实弹窗小超时：exec 事件循环中 QTimer 到期自动 done(No) → 返回 False"""
        from src.gui.dialogs import confirm_config_update

        # 真实 QMessageBox（未 mock），200ms 超时后自动按拒绝关闭
        result = confirm_config_update("测试脚本", timeout_ms=200)
        self.assertFalse(result)


class TestSingleScriptConfigDialogLoad(unittest.TestCase):
    """测试 SingleScriptConfigDialog.load_data 默认值行为。"""

    def _make_weekly_file(self, weekly_map):
        d = tempfile.mkdtemp()
        wt = os.path.join(d, "weekly_timeouts.yml")
        dump_yaml_file(wt, weekly_map)
        return wt

    def _make_config_file(self):
        """构造一个最小、存在的 config.yml 供对话框读取（对话框依赖 config.yml 已存在）。"""
        d = tempfile.mkdtemp()
        cfg = os.path.join(d, "config.yml")
        dump_yaml_file(cfg, {"script_list": []})
        return cfg

    def test_load_seeds_from_default_when_no_weekly_entry(self):
        """weekly_timeouts 无该脚本条目时，7 格应显示 DEFAULT_RUN_TIMEOUT（3600）"""
        wt = self._make_weekly_file({})
        cfg = self._make_config_file()
        with (
            patch(
                "src.service.script_service.require_config_yml_path",
                return_value=cfg,
            ),
            patch(
                "src.service.weekly_service.get_weekly_timeouts_yml_path_under_root",
                return_value=wt,
            ),
        ):
            dlg = SingleScriptConfigDialog("collect_log", "日志分析", "C:/x.py")
            values = [le.text() for le in dlg.timeout_inputs]
        self.assertEqual(values, ["3600"] * 7)

    def test_load_uses_existing_weekly_entry(self):
        """weekly_timeouts 已有条目时使用已有值"""
        wt = self._make_weekly_file({"collect_log": [60, 60, 60, 60, 60, 60, 60]})
        cfg = self._make_config_file()
        with (
            patch(
                "src.service.script_service.require_config_yml_path",
                return_value=cfg,
            ),
            patch(
                "src.service.weekly_service.get_weekly_timeouts_yml_path_under_root",
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
                "src.service.script_service.require_config_yml_path",
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
            "src.service.script_service.require_config_yml_path",
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
            "src.service.script_service.require_config_yml_path",
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
                "src.service.script_service.require_config_yml_path",
                return_value=cfg,
            ),
            patch("src.gui.dialogs.QMessageBox.warning"),
            patch.object(SingleScriptConfigDialog, "accept"),
        ):
            dlg = SingleScriptConfigDialog("日志分析", "日志分析", "C:/y.py")
            dlg.block_cb.setChecked(False)
            dlg.save_data()
        self.assertFalse(dlg.pending_changes["config_patch"]["block"])
        self.assertEqual(dlg.pending_changes["new_display_name"], "日志分析")


class _FakeService:
    """极简 ScriptService 替身：供弹窗构造时读取脚本数据，避免依赖真实 config。"""

    def __init__(
        self, script_type, script_path, display_name="日志分析", weekly_start=None
    ):
        self._data = {
            "script_type": script_type,
            "script_path": script_path,
            "display_name": display_name,
        }
        self._weekly_start = weekly_start
        self.saved_weekly_start = None

    def get_script(self, name):
        return self._data

    def weekly_inputs(self, name):
        return [3600] * 7

    def get_weekly_start(self, script_name):
        return self._weekly_start

    def set_weekly_start(self, script_name, start_day):
        self.saved_weekly_start = start_day


class TestSingleScriptConfigDialogWeeklyStart(unittest.TestCase):
    """测试配置弹窗的「周几起」行：仅支持周常脚本显示，读写 weekly_list.yml。"""

    def _make_dialog(self, script_name, display_name, weekly_start, supported):
        fake_service = _FakeService(
            "external", "C:/games/run.exe", display_name, weekly_start
        )
        with patch("src.gui.dialogs.supports_weekly", return_value=supported):
            return SingleScriptConfigDialog(
                script_name,
                display_name,
                "C:/games/run.exe",
                script_service=fake_service,
                weekly_service=fake_service,
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

    def test_save_writes_weekly_start(self):
        """保存时把周几起（周三起）经 ScriptService 持久化，并暂存到 pending_changes

        游戏侧原生 config 的同步不在 save_data 内进行（那时 config.yml 尚未落盘新路径，
        目录解析会指向旧目录）；由调用方落盘后触发，见 game_list.configCurrent。
        """
        dlg = self._make_dialog("run", "鸣潮", None, supported=True)
        dlg.weekly_start_combo.setCurrentIndex(3)
        with (
            patch("src.gui.dialogs.QMessageBox.warning"),
            patch.object(SingleScriptConfigDialog, "accept"),
        ):
            dlg.save_data()
        self.assertEqual(dlg._weekly_service.saved_weekly_start, 3)
        self.assertEqual(dlg.pending_changes["weekly_start_day"], 3)

    def test_save_clears_weekly_start_when_unset(self):
        """选择「不设置」时经 ScriptService 清除（传 None），pending_changes 记为 None"""
        dlg = self._make_dialog("run", "鸣潮", 5, supported=True)
        dlg.weekly_start_combo.setCurrentIndex(0)
        with (
            patch("src.gui.dialogs.QMessageBox.warning"),
            patch.object(SingleScriptConfigDialog, "accept"),
        ):
            dlg.save_data()
        self.assertIsNone(dlg._weekly_service.saved_weekly_start)
        self.assertIsNone(dlg.pending_changes["weekly_start_day"])


if __name__ == "__main__":
    unittest.main()
