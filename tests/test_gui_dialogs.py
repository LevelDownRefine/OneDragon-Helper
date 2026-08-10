"""测试 src/gui/dialogs.py：AddScriptDialog 表单（default_script_entry 见 test_subscript）"""

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import yaml

# 在导入 PySide6 之前设置 offscreen 平台插件（CI 无显示器环境）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from src.gui.dialogs import (
    AddScriptDialog,
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
        with patch("src.gui.dialogs.QMessageBox") as mock_box:
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

    def test_inject_callback_returns_false_on_no(self):
        """用户点 No 时回调返回 False（对应 config 层 enabled 置 False）"""
        from src.config.set_config import ScriptConfig

        inject_config_confirm()
        callback = ScriptConfig.confirm_before_save
        with patch("src.gui.dialogs.QMessageBox") as mock_box:
            mock_box.No = QMessageBox.No
            instance = mock_box.return_value
            instance.exec.return_value = None
            instance.result.return_value = QMessageBox.No
            self.assertFalse(callback("测试脚本"))


class TestAddScriptDialog(unittest.TestCase):
    """测试 AddScriptDialog 表单校验与结果构造"""

    def test_save_builds_script_entry(self):
        """填入合法字段后 save_data 构造完整 script_entry 并 accept"""
        dlg = AddScriptDialog(existing_script_names=["已存在"])
        dlg.name_input.setText("新脚本")
        dlg.type_combo.setCurrentText("python")
        dlg.path_input.setText("C:/foo/bar.py")
        with patch.object(dlg, "accept") as acc:
            dlg.save_data()
        self.assertIsNotNone(dlg.script_entry)
        self.assertEqual(dlg.script_entry["display_name"], "新脚本")
        self.assertEqual(dlg.script_entry["script_type"], "python")
        self.assertEqual(dlg.script_entry["script_path"], "C:/foo/bar.py")
        self.assertEqual(dlg.script_entry["script_arguments"], "")
        acc.assert_called_once()

    def test_save_captures_script_arguments(self):
        """填入启动参数后写入 script_entry['script_arguments']"""
        dlg = AddScriptDialog()
        dlg.name_input.setText("带参脚本")
        dlg.path_input.setText("C:/foo/bar.exe")
        dlg.args_input.setText("--task daily --fast")
        with patch.object(dlg, "accept"):
            dlg.save_data()
        self.assertIsNotNone(dlg.script_entry)
        self.assertEqual(dlg.script_entry["script_arguments"], "--task daily --fast")

    def test_save_rejects_empty_name(self):
        """名称为空时不构造 script_entry"""
        dlg = AddScriptDialog()
        dlg.name_input.setText("")
        dlg.path_input.setText("C:/x.exe")
        with patch("src.gui.dialogs.QMessageBox.warning"):
            dlg.save_data()
        self.assertIsNone(dlg.script_entry)

    def test_save_rejects_duplicate_key(self):
        """脚本标识重复时不构造 script_entry"""
        dlg = AddScriptDialog(existing_script_names=["BetterGI"])
        dlg.name_input.setText("原神改")
        dlg.path_input.setText("C:/game_helper/BetterGI.exe")
        with patch("src.gui.dialogs.QMessageBox.warning"):
            dlg.save_data()
        self.assertIsNone(dlg.script_entry)

    def test_save_rejects_empty_path(self):
        """路径为空时不构造 script_entry"""
        dlg = AddScriptDialog()
        dlg.name_input.setText("新脚本")
        dlg.path_input.setText("")
        with patch("src.gui.dialogs.QMessageBox.warning"):
            dlg.save_data()
        self.assertIsNone(dlg.script_entry)


class TestSingleScriptConfigDialogLoad(unittest.TestCase):
    """测试 SingleScriptConfigDialog.load_data 默认值行为。"""

    def _make_weekly_file(self, weekly_map):
        d = tempfile.mkdtemp()
        wt = os.path.join(d, "weekly_timeouts.yml")
        with open(wt, "w", encoding="utf-8") as f:
            yaml.safe_dump(weekly_map, f, allow_unicode=True)
        return wt

    def _make_config_file(self):
        """构造一个最小、存在的 config.yml 供对话框读取（对话框依赖 config.yml 已存在）。"""
        d = tempfile.mkdtemp()
        cfg = os.path.join(d, "config.yml")
        with open(cfg, "w", encoding="utf-8") as f:
            yaml.safe_dump({"script_list": []}, f, allow_unicode=True)
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
                "src.service.script_service.get_weekly_timeouts_yml_path_under_root",
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
                "src.service.script_service.get_weekly_timeouts_yml_path_under_root",
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
        with open(cfg, "w", encoding="utf-8") as f:
            yaml.safe_dump({"script_list": script_list}, f, allow_unicode=True)
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

    def __init__(self, script_type, script_path):
        self._data = {"script_type": script_type, "script_path": script_path}

    def get_script(self, name):
        return self._data

    def weekly_inputs(self, name):
        return [3600] * 7


class TestSingleScriptConfigDialogOpenConfig(unittest.TestCase):
    """测试弹窗内「配置文件」动作：委托 ScriptService.config_file_path。"""

    def _make_dialog(self, config_return):
        dlg = SingleScriptConfigDialog(
            "ok-ww",
            "鸣潮",
            "C:/games/run.exe",
            script_service=_FakeService("external", "C:/games/run.exe"),
        )
        svc = MagicMock()
        svc.config_file_path.return_value = config_return
        dlg._script_service = svc
        return dlg

    def test_external_opens_resolved_config(self):
        """service 返回 external config 路径：以 safe_startfile 打开"""
        dlg = self._make_dialog(("C:/games/config/DailyTask.json", None))
        with patch("src.gui.dialogs.safe_startfile") as mock_start:
            dlg._open_config_file()
        mock_start.assert_called_once_with(
            dlg, "C:/games/config/DailyTask.json", "无法打开配置文件"
        )

    def test_external_missing_shows_msg(self):
        """service 返回错误：弹窗提示且不打开文件"""
        dlg = self._make_dialog((None, "该脚本暂未适配配置文件，无法打开"))
        with (
            patch("src.gui.dialogs.safe_startfile") as mock_start,
            patch("src.gui.dialogs._styled_msg_box") as mock_box,
        ):
            dlg._open_config_file()
        mock_start.assert_not_called()
        mock_box.assert_called_once()

    def test_python_opens_py_file(self):
        """service 返回 python .py 路径：以 safe_startfile 打开"""
        dlg = self._make_dialog(("C:/proj/src/scripts/mute.py", None))
        with patch("src.gui.dialogs.safe_startfile") as mock_start:
            dlg._open_config_file()
        mock_start.assert_called_once_with(
            dlg, "C:/proj/src/scripts/mute.py", "无法打开配置文件"
        )

    def test_python_missing_file_shows_msg(self):
        """service 返回错误：弹窗提示且不打开文件"""
        dlg = self._make_dialog((None, "找不到脚本文件"))
        with (
            patch("src.gui.dialogs.safe_startfile") as mock_start,
            patch("src.gui.dialogs._styled_msg_box") as mock_box,
        ):
            dlg._open_config_file()
        mock_start.assert_not_called()
        mock_box.assert_called_once()


class TestSingleScriptConfigDialogDelete(unittest.TestCase):
    """测试弹窗内「删除脚本」动作。"""

    def _make_dialog(self):
        return SingleScriptConfigDialog(
            "ok-ww",
            "鸣潮",
            "C:/games/run.exe",
            script_service=_FakeService("external", "C:/games/run.exe"),
        )

    def test_delete_emits_signal_and_closes(self):
        """确认删除后发出 delete_requested 并关闭弹窗"""
        dlg = self._make_dialog()
        received = []
        dlg.delete_requested.connect(lambda n: received.append(n))
        with (
            patch("src.gui.dialogs.QMessageBox") as mock_box,
            patch.object(dlg, "close") as mock_close,
        ):
            mock_box.Ok = "OK"
            mock_box.return_value.exec.return_value = "OK"
            dlg._on_delete_clicked()
        self.assertEqual(received, ["ok-ww"])
        mock_close.assert_called_once()

    def test_delete_cancelled_does_not_emit(self):
        """取消删除时不发信号、不关闭弹窗"""
        dlg = self._make_dialog()
        received = []
        dlg.delete_requested.connect(lambda n: received.append(n))
        with (
            patch("src.gui.dialogs.QMessageBox") as mock_box,
            patch.object(dlg, "close") as mock_close,
        ):
            mock_box.Ok = "OK"
            mock_box.return_value.exec.return_value = "CANCEL"
            dlg._on_delete_clicked()
        self.assertEqual(received, [])
        mock_close.assert_not_called()


if __name__ == "__main__":
    unittest.main()
