"""测试 src/gui/main_window.py：重排、删除、添加脚本与持久化"""

import os
import tempfile
import unittest
from io import StringIO
from unittest.mock import MagicMock, patch

import yaml

# 在导入 PySide6 之前设置 offscreen 平台插件（CI 无显示器环境）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog

from src.gui.dialogs import default_script_entry
from src.gui.main_window import MainWindow, QMessageBox
from src.gui.widgets import ScriptItem

# 全局 QApplication 实例（测试共享）
_app = QApplication.instance() or QApplication([])


def _make_window(script_count=3, disable_persist=False):
    """构造测试用 MainWindow：跳过真实 _load_scripts（涉及文件 I/O），手动注入状态。

    disable_persist=True 时把写回 config.yml / gui_state.json 的方法换成 no-op，
    防止测试桩数据污染真实配置文件。
    """
    with patch.object(MainWindow, "_load_scripts", lambda self: None):
        win = MainWindow()
    win.dungeon_map = {}
    win.script_items = [
        ScriptItem({"display_name": f"脚本{i}", "script_type": "external"})
        for i in range(script_count)
    ]
    win.all_config_data = {
        "script_list": [
            {"display_name": f"脚本{i}", "script_type": "external"}
            for i in range(script_count)
        ]
    }
    if disable_persist:
        win._save_script_order = lambda: None
        win._persist_ui_state = lambda: None
    return win


def _fake_open_capture(captured):
    """返回一个 fake open：写入内容捕获到 captured['buf']"""

    def fake_open(file, mode="w", encoding=None):
        m = MagicMock()
        buf = StringIO()
        captured["buf"] = buf
        m.__enter__ = MagicMock(return_value=buf)
        m.__exit__ = MagicMock(return_value=False)
        return m

    return fake_open


class TestReorderScripts(unittest.TestCase):
    """测试 MainWindow._reorder_scripts 顺序同步与持久化"""

    def test_reorder_updates_script_items_order(self):
        """重排后 self.script_items 顺序改变（脚本0 移动到 脚本2 之后）"""
        win = _make_window(disable_persist=True)
        win._reorder_scripts("脚本0", "脚本2")
        names = [it.display_name for it in win.script_items]
        self.assertEqual(names, ["脚本1", "脚本2", "脚本0"])

    def test_reorder_updates_config_data_order(self):
        """重排后 self.all_config_data['script_list'] 顺序同步改变"""
        win = _make_window(disable_persist=True)
        win._reorder_scripts("脚本0", "脚本2")
        names = [s["display_name"] for s in win.all_config_data["script_list"]]
        self.assertEqual(names, ["脚本1", "脚本2", "脚本0"])

    def test_reorder_persists_to_config_yml(self):
        """重排后写回 config.yml（script_list 顺序一致）"""
        win = _make_window()
        captured = {}
        with (
            patch(
                "src.utils.get_config_yml_path_under_root", return_value="CONFIG.yml"
            ),
            patch("builtins.open", side_effect=_fake_open_capture(captured)),
        ):
            win._reorder_scripts("脚本0", "脚本2")
        written = yaml.safe_load(captured["buf"].getvalue())
        names = [s["display_name"] for s in written["script_list"]]
        self.assertEqual(names, ["脚本1", "脚本2", "脚本0"])

    def test_reorder_noop_when_same_target(self):
        """源与目标相同（src==dst）时顺序不变"""
        win = _make_window(disable_persist=True)
        win._reorder_scripts("脚本1", "脚本1")
        names = [it.display_name for it in win.script_items]
        self.assertEqual(names, ["脚本0", "脚本1", "脚本2"])


class TestDeleteScript(unittest.TestCase):
    """测试 MainWindow 删除脚本：UI 与 config.yml 同步移除并持久化"""

    def test_delete_removes_from_script_items(self):
        """确认删除后 self.script_items 不再包含该脚本"""
        win = _make_window(disable_persist=True)
        with patch(
            "src.gui.main_window.QMessageBox.question", return_value=QMessageBox.Yes
        ):
            win._delete_script("脚本1")
        names = [it.display_name for it in win.script_items]
        self.assertEqual(names, ["脚本0", "脚本2"])

    def test_delete_removes_from_config_data(self):
        """确认删除后 self.all_config_data['script_list'] 不再包含该脚本"""
        win = _make_window(disable_persist=True)
        with patch(
            "src.gui.main_window.QMessageBox.question", return_value=QMessageBox.Yes
        ):
            win._delete_script("脚本1")
        names = [s["display_name"] for s in win.all_config_data["script_list"]]
        self.assertEqual(names, ["脚本0", "脚本2"])

    def test_delete_removes_widget_from_layout(self):
        """确认删除后 widget 从滚动区布局移除"""
        win = _make_window(disable_persist=True)
        item = win.script_items[1]
        win.scroll_layout.addWidget(item)
        with patch(
            "src.gui.main_window.QMessageBox.question", return_value=QMessageBox.Yes
        ):
            win._delete_script("脚本1")
        self.assertEqual(win.scroll_layout.indexOf(item), -1)

    def test_delete_persists_to_config_yml(self):
        """确认删除后写回 config.yml（script_list 不含被删脚本）"""
        win = _make_window()  # 保留真实 _save_script_order，验证写回
        win._persist_ui_state = lambda: (
            None
        )  # 仅验证 config.yml 写回，隔离 gui_state.json
        captured = {}
        with (
            patch(
                "src.gui.main_window.QMessageBox.question", return_value=QMessageBox.Yes
            ),
            patch(
                "src.utils.get_config_yml_path_under_root", return_value="CONFIG.yml"
            ),
            patch("builtins.open", side_effect=_fake_open_capture(captured)),
        ):
            win._delete_script("脚本1")
        written = yaml.safe_load(captured["buf"].getvalue())
        names = [s["display_name"] for s in written["script_list"]]
        self.assertEqual(names, ["脚本0", "脚本2"])

    def test_delete_noop_when_confirm_no(self):
        """确认弹窗选「否」时不删除、不改变任何状态"""
        win = _make_window(disable_persist=True)
        with patch(
            "src.gui.main_window.QMessageBox.question", return_value=QMessageBox.No
        ):
            win._delete_script("脚本1")
        names = [it.display_name for it in win.script_items]
        self.assertEqual(names, ["脚本0", "脚本1", "脚本2"])
        cfg_names = [s["display_name"] for s in win.all_config_data["script_list"]]
        self.assertEqual(cfg_names, ["脚本0", "脚本1", "脚本2"])


class TestAddScript(unittest.TestCase):
    """测试 MainWindow 添加脚本：UI 与 config.yml 同步追加并持久化"""

    def test_append_adds_to_script_items(self):
        """追加后 self.script_items 末尾出现新脚本"""
        win = _make_window(script_count=2, disable_persist=True)
        entry = default_script_entry("新脚本", "external", "C:/x.exe", 100)
        win._append_script(entry)
        names = [it.display_name for it in win.script_items]
        self.assertEqual(names, ["脚本0", "脚本1", "新脚本"])

    def test_append_adds_to_config_data(self):
        """追加后 self.all_config_data['script_list'] 末尾出现新脚本条目"""
        win = _make_window(script_count=2, disable_persist=True)
        entry = default_script_entry("新脚本", "external", "C:/x.exe", 100)
        win._append_script(entry)
        names = [s["display_name"] for s in win.all_config_data["script_list"]]
        self.assertEqual(names, ["脚本0", "脚本1", "新脚本"])
        self.assertIs(win.all_config_data["script_list"][-1], entry)


class TestOpenConfigYml(unittest.TestCase):
    """测试 MainWindow「打开配置」按钮：用 _safe_startfile 打开 get_config_yml_path_under_root 返回的路径"""

    def test_open_config_btn_exists_and_wired(self):
        """存在「打开配置」按钮，且点击触发 _open_config_yml"""
        win = _make_window(disable_persist=True)
        self.assertTrue(hasattr(win, "open_config_btn"))
        captured = []
        win._open_config_yml = lambda: captured.append(True)
        win.open_config_btn.clicked.disconnect()
        win.open_config_btn.clicked.connect(win._open_config_yml)
        win.open_config_btn.click()
        self.assertEqual(captured, [True])

    def test_open_config_yml_calls_safe_startfile_with_path(self):
        """调用 _safe_startfile，传入 config.yml 路径与统一失败文案"""
        win = _make_window(disable_persist=True)
        with (
            patch("src.gui.main_window._safe_startfile") as mock_start,
            patch(
                "src.gui.main_window.get_config_yml_path_under_root",
                return_value="CONFIG.yml",
            ),
        ):
            win._open_config_yml()
        mock_start.assert_called_once_with(win, "CONFIG.yml", "无法打开配置文件")


class TestRunSelected(unittest.TestCase):
    """测试 MainWindow._run_selected：生成配置后构造 ScriptChainRunner（无全局 block）。"""

    def _capture_runner_args(self, win):
        captured = {}

        def fake_runner(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return MagicMock()

        with (
            patch(
                "src.gui.main_window.QMessageBox.question", return_value=QMessageBox.Yes
            ),
            patch(
                "src.gui.main_window.collect_invalid_script_messages",
                return_value=[],
            ),
            patch.object(
                win, "_generate_config", return_value="config/script_chain/01.yml"
            ),
            patch("src.gui.main_window.ScriptChainRunner", side_effect=fake_runner),
        ):
            win._run_selected()
        return captured

    def test_runner_constructed_without_global_block(self):
        """后台运行改为 per-script 配置，主窗口不再传全局 block 参数。"""
        win = _make_window(disable_persist=True)
        captured = self._capture_runner_args(win)
        self.assertEqual(captured["args"], ("config/script_chain/01.yml",))
        self.assertNotIn("block", captured["kwargs"])

    def test_invalid_config_warns_and_can_cancel(self):
        """启用脚本配置不合法时弹窗列出明细；点 No 则不运行。"""
        win = _make_window(disable_persist=True)
        win.all_config_data = {
            "script_list": [
                {"display_name": "脚本0", "script_type": "external"},
                {"display_name": "脚本1", "script_type": "external"},
            ]
        }
        invalid = [
            ("脚本0", "脚本路径为空"),
            ("脚本1", "游戏进程名称为空"),
        ]
        with (
            patch(
                "src.gui.main_window.collect_invalid_script_messages",
                return_value=invalid,
            ) as mock_collect,
            patch(
                "src.gui.main_window.QMessageBox.warning", return_value=QMessageBox.No
            ) as mock_warning,
            patch("src.gui.main_window.ScriptChainRunner") as mock_runner,
        ):
            win._run_selected()
        mock_collect.assert_called_once()
        args, _ = mock_warning.call_args
        self.assertIn("脚本路径为空", args[2])
        self.assertIn("游戏进程名称为空", args[2])
        mock_runner.assert_not_called()

    def test_invalid_config_can_force_run(self):
        """配置不合法但用户选择仍然运行 → 继续原有流程。"""
        win = _make_window(disable_persist=True)
        invalid = [("脚本0", "脚本路径为空")]
        with (
            patch(
                "src.gui.main_window.collect_invalid_script_messages",
                return_value=invalid,
            ),
            patch(
                "src.gui.main_window.QMessageBox.warning", return_value=QMessageBox.Yes
            ),
            patch(
                "src.gui.main_window.QMessageBox.question", return_value=QMessageBox.Yes
            ),
            patch.object(
                win, "_generate_config", return_value="config/script_chain/01.yml"
            ),
            patch("src.gui.main_window.ScriptChainRunner") as mock_runner,
        ):
            win._run_selected()
        mock_runner.assert_called_once()

    def test_append_persists_to_config_yml(self):
        """追加后写回 config.yml（末尾含新脚本，字段完整）"""
        win = _make_window(script_count=2)  # 保留真实 _save_script_order
        win._persist_ui_state = lambda: None  # 隔离 gui_state.json
        captured = {}
        entry = default_script_entry("新脚本", "python", "C:/x.py")
        with (
            patch(
                "src.utils.get_config_yml_path_under_root", return_value="CONFIG.yml"
            ),
            patch("builtins.open", side_effect=_fake_open_capture(captured)),
        ):
            win._append_script(entry)
        written = yaml.safe_load(captured["buf"].getvalue())
        names = [s["display_name"] for s in written["script_list"]]
        self.assertEqual(names, ["脚本0", "脚本1", "新脚本"])
        self.assertEqual(written["script_list"][-1]["script_type"], "python")

    def test_append_widget_added_to_layout(self):
        """追加后新脚本 widget 出现在滚动区布局中"""
        win = _make_window(script_count=2, disable_persist=True)
        entry = default_script_entry("新脚本", "external", "C:/x.exe")
        win._append_script(entry)
        new_item = win.script_items[-1]
        self.assertGreaterEqual(win.scroll_layout.indexOf(new_item), 0)

    def test_add_script_cancel_does_nothing(self):
        """文件选择取消（空路径）时不追加任何脚本"""
        win = _make_window(script_count=2, disable_persist=True)
        with patch(
            "src.gui.main_window.QFileDialog.getOpenFileName", return_value=("", "")
        ):
            win._add_script()
        names = [it.display_name for it in win.script_items]
        self.assertEqual(names, ["脚本0", "脚本1"])

    def test_add_script_confirm_appends(self):
        """文件选择确认后自动以文件名作为显示名称追加脚本"""
        win = _make_window(script_count=2, disable_persist=True)
        with patch(
            "src.gui.main_window.QFileDialog.getOpenFileName",
            return_value=("C:/y.exe", ""),
        ):
            win._add_script()
        names = [it.display_name for it in win.script_items]
        self.assertEqual(names, ["脚本0", "脚本1", "y"])
        self.assertEqual(win.script_items[-1].script_type, "external")


class TestConfigSaveSync(unittest.TestCase):
    """测试配置弹窗保存后，MainWindow 重新吸收磁盘改动（修复「保存路径失效」）。"""

    def test_script_config_saved_reloads_all_config_data(self):
        """_on_script_config_saved 应从磁盘重新加载 all_config_data，吸收新路径"""
        win = _make_window(disable_persist=True)
        win.all_config_data["script_list"][0]["script_path"] = "C:/old.exe"
        win.script_items[0].script_path = "C:/old.exe"

        new_cfg = {
            "script_list": [
                {
                    "display_name": f"脚本{i}",
                    "script_type": "external",
                    "script_path": "C:/new.exe" if i == 0 else "",
                }
                for i in range(3)
            ]
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yml", encoding="utf-8", delete=False
        ) as tmp:
            yaml.safe_dump(new_cfg, tmp, allow_unicode=True, sort_keys=False)
            tmp_path = tmp.name
        try:
            with patch(
                "src.utils.get_config_yml_path_under_root", return_value=tmp_path
            ):
                win._on_script_config_saved("脚本0")
        finally:
            os.unlink(tmp_path)

        reloaded = next(
            s
            for s in win.all_config_data["script_list"]
            if s["display_name"] == "脚本0"
        )
        self.assertEqual(reloaded["script_path"], "C:/new.exe")
        self.assertEqual(win.script_items[0].script_path, "C:/new.exe")

    def test_config_dialog_accept_triggers_callback(self):
        """ScriptItem 配置弹窗 accept 后，应调用 config_saved_callback 通知 MainWindow"""
        callback = MagicMock()
        item = ScriptItem(
            {"display_name": "脚本0", "script_type": "external"},
            config_saved_callback=callback,
        )
        fake_dialog = MagicMock()
        fake_dialog.exec.return_value = QDialog.Accepted
        # saved_display_name 用真实字符串：与原名相同 => 不改名分支，仅验证回调原名称
        fake_dialog.saved_display_name = "脚本0"
        with patch(
            "src.gui.widgets.SingleScriptConfigDialog", return_value=fake_dialog
        ):
            item._show_config_dialog()
        callback.assert_called_once_with("脚本0")

    def test_config_dialog_reject_does_not_trigger_callback(self):
        """配置弹窗取消（Rejected）时不触发回调，避免无谓重载"""
        callback = MagicMock()
        item = ScriptItem(
            {"display_name": "脚本0", "script_type": "external"},
            config_saved_callback=callback,
        )
        fake_dialog = MagicMock()
        fake_dialog.exec.return_value = QDialog.Rejected
        with patch(
            "src.gui.widgets.SingleScriptConfigDialog", return_value=fake_dialog
        ):
            item._show_config_dialog()
        callback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
