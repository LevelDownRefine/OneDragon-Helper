"""测试 src/gui/dialogs.py：default_script_entry 与 AddScriptDialog 表单"""

import os
import tempfile
import unittest
from unittest.mock import patch

import yaml

# 在导入 PySide6 之前设置 offscreen 平台插件（CI 无显示器环境）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.gui.dialogs import (
    AddScriptDialog,
    SingleScriptConfigDialog,
    compute_weekly_timeout_inputs,
    default_script_entry,
)

# 全局 QApplication 实例（测试共享）
_app = QApplication.instance() or QApplication([])


class TestDefaultScriptEntry(unittest.TestCase):
    """测试 default_script_entry 字段补全"""

    def test_default_script_entry_has_all_fields(self):
        """default_script_entry 覆盖 config.yml 全部字段，核心字段用参数值"""
        entry = default_script_entry("崩坏3", "python", "C:/a/b.py")
        self.assertEqual(entry["display_name"], "崩坏3")
        self.assertEqual(entry["script_type"], "python")
        self.assertEqual(entry["script_path"], "C:/a/b.py")
        # 关键默认字段
        self.assertEqual(entry["script_process_name"], [])
        self.assertEqual(entry["kill_script_after_done"], True)
        self.assertEqual(entry["no_log_max_retries"], 3)
        # 与真实条目字段集合一致（无 run_timeout_seconds）
        expected_keys = {
            "display_name",
            "game_label",
            "script_type",
            "script_path",
            "script_process_name",
            "game_process_name",
            "launcher_mode",
            "check_done",
            "kill_script_after_done",
            "kill_game_after_done",
            "script_arguments",
            "notify_start",
            "notify_done",
            "notify_log_interval",
            "attach_direction",
            "no_log_timeout_seconds",
            "no_log_max_retries",
            "block",
        }
        self.assertEqual(set(entry.keys()), expected_keys)


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


class TestComputeWeeklyTimeoutInputs(unittest.TestCase):
    """测试 compute_weekly_timeout_inputs：缺失条目用默认填充，已有条目优先。"""

    def test_missing_entry_seeds_from_default(self):
        """无条目时用 default_timeout 填满 7 格（避免静默写 0）"""
        self.assertEqual(
            compute_weekly_timeout_inputs("日志分析", {}, 60),
            [60, 60, 60, 60, 60, 60, 60],
        )

    def test_existing_entry_used(self):
        """已有条目时优先使用，不被 default 覆盖"""
        self.assertEqual(
            compute_weekly_timeout_inputs("x", {"x": [1, 2, 3, 4, 5, 6, 7]}, 60),
            [1, 2, 3, 4, 5, 6, 7],
        )

    def test_existing_short_entry_padded_with_default(self):
        """已有条目不足 7 格时用 default 补齐"""
        self.assertEqual(
            compute_weekly_timeout_inputs("x", {"x": [10, 20]}, 60),
            [10, 20, 60, 60, 60, 60, 60],
        )

    def test_missing_entry_default_zero(self):
        """默认本身为 0 时（run_timeout_seconds=0）才填 0"""
        self.assertEqual(
            compute_weekly_timeout_inputs("x", {}, 0),
            [0, 0, 0, 0, 0, 0, 0],
        )


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
                "src.gui.dialogs.get_weekly_timeouts_yml_path_under_root",
                return_value=wt,
            ),
            patch("src.utils.get_config_yml_path_under_root", return_value=cfg),
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
                "src.gui.dialogs.get_weekly_timeouts_yml_path_under_root",
                return_value=wt,
            ),
            patch("src.utils.get_config_yml_path_under_root", return_value=cfg),
        ):
            dlg = SingleScriptConfigDialog("日志分析", "C:/x.py")
            values = [le.text() for le in dlg.timeout_inputs]
        self.assertEqual(values, ["60"] * 7)

    def test_init_asserts_when_config_yml_missing(self):
        """config.yml 缺失属内部错误：构造对话框必须 assert，而非静默返回空数据"""
        with (
            patch(
                "src.utils.get_config_yml_path_under_root",
                return_value="C:/no/such/config.yml",
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
        with patch("src.utils.get_config_yml_path_under_root", return_value=cfg):
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
        with patch("src.utils.get_config_yml_path_under_root", return_value=cfg):
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
            patch("src.utils.get_config_yml_path_under_root", return_value=cfg),
            patch(
                "src.gui.dialogs.get_weekly_timeouts_yml_path_under_root",
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
