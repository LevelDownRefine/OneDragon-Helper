"""测试 src/gui/dialogs.py：AddScriptDialog 表单（default_script_entry 见 test_subscript）"""

import os
import tempfile
import unittest
from unittest.mock import patch

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

    def test_save_builds_result_data(self):
        """填入合法字段后 save_data 构造完整 result_data 并 accept"""
        dlg = AddScriptDialog(existing_names=["已存在"])
        dlg.name_input.setText("新脚本")
        dlg.type_combo.setCurrentText("python")
        dlg.path_input.setText("C:/foo/bar.py")
        with patch.object(dlg, "accept") as acc:
            dlg.save_data()
        self.assertIsNotNone(dlg.result_data)
        self.assertEqual(dlg.result_data["display_name"], "新脚本")
        self.assertEqual(dlg.result_data["script_type"], "python")
        self.assertEqual(dlg.result_data["script_path"], "C:/foo/bar.py")
        self.assertEqual(dlg.result_data["script_arguments"], "")
        acc.assert_called_once()

    def test_save_captures_script_arguments(self):
        """填入启动参数后写入 result_data['script_arguments']"""
        dlg = AddScriptDialog()
        dlg.name_input.setText("带参脚本")
        dlg.path_input.setText("C:/foo/bar.exe")
        dlg.args_input.setText("--task daily --fast")
        with patch.object(dlg, "accept"):
            dlg.save_data()
        self.assertIsNotNone(dlg.result_data)
        self.assertEqual(dlg.result_data["script_arguments"], "--task daily --fast")

    def test_save_rejects_empty_name(self):
        """名称为空时不构造 result_data"""
        dlg = AddScriptDialog()
        dlg.name_input.setText("")
        dlg.path_input.setText("C:/x.exe")
        with patch("src.gui.dialogs.QMessageBox.warning"):
            dlg.save_data()
        self.assertIsNone(dlg.result_data)

    def test_save_rejects_duplicate_name(self):
        """名称重复时不构造 result_data"""
        dlg = AddScriptDialog(existing_names=["原神"])
        dlg.name_input.setText("原神")
        dlg.path_input.setText("C:/x.exe")
        with patch("src.gui.dialogs.QMessageBox.warning"):
            dlg.save_data()
        self.assertIsNone(dlg.result_data)

    def test_save_rejects_empty_path(self):
        """路径为空时不构造 result_data"""
        dlg = AddScriptDialog()
        dlg.name_input.setText("新脚本")
        dlg.path_input.setText("")
        with patch("src.gui.dialogs.QMessageBox.warning"):
            dlg.save_data()
        self.assertIsNone(dlg.result_data)


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
                "src.service.script_service.get_config_yml_path_under_root",
                return_value=cfg,
            ),
            patch(
                "src.service.script_service.get_weekly_timeouts_yml_path_under_root",
                return_value=wt,
            ),
        ):
            dlg = SingleScriptConfigDialog("日志分析", "C:/x.py")
            values = [le.text() for le in dlg.timeout_inputs]
        self.assertEqual(values, ["3600"] * 7)

    def test_load_uses_existing_weekly_entry(self):
        """weekly_timeouts 已有条目时使用已有值"""
        wt = self._make_weekly_file({"日志分析": [60, 60, 60, 60, 60, 60, 60]})
        cfg = self._make_config_file()
        with (
            patch(
                "src.service.script_service.require_config_yml_path",
                return_value=cfg,
            ),
            patch(
                "src.service.script_service.get_config_yml_path_under_root",
                return_value=cfg,
            ),
            patch(
                "src.service.script_service.get_weekly_timeouts_yml_path_under_root",
                return_value=wt,
            ),
        ):
            dlg = SingleScriptConfigDialog("日志分析", "C:/x.py")
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
            SingleScriptConfigDialog("日志分析", "C:/x.py")


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
        with (
            patch(
                "src.service.script_service.require_config_yml_path",
                return_value=cfg,
            ),
            patch(
                "src.service.script_service.get_config_yml_path_under_root",
                return_value=cfg,
            ),
        ):
            dlg = SingleScriptConfigDialog("日志分析", "C:/x.py")
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
        with (
            patch(
                "src.service.script_service.require_config_yml_path",
                return_value=cfg,
            ),
            patch(
                "src.service.script_service.get_config_yml_path_under_root",
                return_value=cfg,
            ),
        ):
            dlg = SingleScriptConfigDialog("日志分析", "C:/x.py")
        self.assertTrue(dlg.block_cb.isChecked())

    def test_save_writes_block(self):
        """保存时把复选框状态写回 config.yml 的 block 字段"""
        cfg = self._make_config_file(
            [
                {
                    "display_name": "日志分析",
                    "script_type": "python",
                    "script_path": "C:/x.py",
                },
            ]
        )
        weekly = os.path.join(tempfile.mkdtemp(), "weekly_timeouts.yml")
        with (
            patch(
                "src.service.script_service.require_config_yml_path",
                return_value=cfg,
            ),
            patch(
                "src.service.script_service.get_config_yml_path_under_root",
                return_value=cfg,
            ),
            patch(
                "src.service.script_service.get_weekly_timeouts_yml_path_under_root",
                return_value=weekly,
            ),
            patch("src.gui.dialogs.QMessageBox.information"),
            patch.object(SingleScriptConfigDialog, "accept"),
        ):
            dlg = SingleScriptConfigDialog("日志分析", "C:/x.py")
            dlg.block_cb.setChecked(False)
            dlg.save_data()
        with open(cfg, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self.assertFalse(data["script_list"][0]["block"])


if __name__ == "__main__":
    unittest.main()
