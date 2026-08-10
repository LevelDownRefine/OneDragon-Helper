"""测试 src/gui/main_window.py：重排、删除、添加脚本与持久化"""

import os
import unittest
from unittest.mock import MagicMock, patch

# 在导入 PySide6 之前设置 offscreen 平台插件（CI 无显示器环境）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.config.subscript import default_script_entry
from src.gui.main_window import MainWindow, QMessageBox
from src.gui.widgets import ScriptItem

# 全局 QApplication 实例（测试共享）
_app = QApplication.instance() or QApplication([])


def _make_window(script_count=3, disable_persist=False):
    """构造测试用 MainWindow：跳过真实 _load_scripts（涉及文件 I/O），手动注入状态。

    disable_persist=True 时把写回 config.yml / gui_state.json 的方法换成 no-op，
    防止测试桩数据污染真实配置文件。script_service 注入 mock，隔离 weekly_timeouts 副作用。
    """
    with patch.object(MainWindow, "_load_scripts", lambda self: None):
        win = MainWindow()
    win.dungeon_map = {}
    win.script_items = [
        ScriptItem({"display_name": f"脚本{i}", "script_type": "external", "script_path": f"脚本{i}.exe"})
        for i in range(script_count)
    ]
    win.all_config_data = {
        "script_list": [
            {"display_name": f"脚本{i}", "script_type": "external", "script_path": f"脚本{i}.exe"}
            for i in range(script_count)
        ]
    }
    win._script_service = MagicMock()  # 隔离 ScriptService 文件读写副作用
    # 仅隔离 ChainService 的落盘方法（总 config.yml）；其余方法保留真实实现
    win.service.add_script = MagicMock()
    win.service.remove_script = MagicMock()
    win.service.save_config = MagicMock()
    win.service.update_script = MagicMock()
    if disable_persist:
        win._save_script_order = lambda: None
        win._persist_ui_state = lambda: None
    return win


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
        """重排后调 ChainService.save_config 传入顺序一致的 script_list。"""
        win = _make_window()
        win._reorder_scripts("脚本0", "脚本2")
        win.service.save_config.assert_called_once()
        args, _ = win.service.save_config.call_args
        names = [s["display_name"] for s in args[0]["script_list"]]
        self.assertEqual(names, ["脚本1", "脚本2", "脚本0"])

    def test_reorder_noop_when_same_target(self):
        """源与目标相同（src==dst）时顺序不变"""
        win = _make_window(disable_persist=True)
        win._reorder_scripts("脚本1", "脚本1")
        names = [it.display_name for it in win.script_items]
        self.assertEqual(names, ["脚本0", "脚本1", "脚本2"])


class TestDeleteScript(unittest.TestCase):
    """测试 MainWindow 删除脚本：UI 与 config.yml 同步移除并持久化

    确认交互由弹窗（SingleScriptConfigDialog._on_delete_clicked）负责，
    MainWindow._delete_script 不再二次确认，故此处不测「取消」分支。
    """

    def test_delete_removes_from_script_items(self):
        """删除后 self.script_items 不再包含该脚本"""
        win = _make_window(disable_persist=True)
        win._delete_script("脚本1")
        names = [it.display_name for it in win.script_items]
        self.assertEqual(names, ["脚本0", "脚本2"])

    def test_delete_removes_from_config_data(self):
        """删除后 self.all_config_data['script_list'] 不再包含该脚本"""
        win = _make_window(disable_persist=True)
        win._delete_script("脚本1")
        names = [s["display_name"] for s in win.all_config_data["script_list"]]
        self.assertEqual(names, ["脚本0", "脚本2"])

    def test_delete_removes_widget_from_layout(self):
        """删除后 widget 从滚动区布局移除"""
        win = _make_window(disable_persist=True)
        item = win.script_items[1]
        win.scroll_layout.addWidget(item)
        win._delete_script("脚本1")
        self.assertEqual(win.scroll_layout.indexOf(item), -1)

    def test_delete_delegates_to_services(self):
        """删除委托 ChainService.remove_script（内部自动处理 config + weekly）"""
        win = _make_window(disable_persist=True)
        win._delete_script("脚本1")
        win.service.remove_script.assert_called_once_with("脚本1")


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
    """测试 MainWindow「打开配置」按钮：用 safe_startfile 打开 get_config_yml_path_under_root 返回的路径"""

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

    def test_open_config_yml_callssafe_startfile_with_path(self):
        """调用 safe_startfile，传入 config.yml 路径与统一失败文案"""
        win = _make_window(disable_persist=True)
        with (
            patch("src.gui.main_window.safe_startfile") as mock_start,
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
            patch.object(win.service, "collect_invalid_scripts", return_value=[]),
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
                {
                    "display_name": "脚本0",
                    "script_type": "external",
                    "script_path": "脚本0.exe",
                },
                {
                    "display_name": "脚本1",
                    "script_type": "external",
                    "script_path": "脚本1.exe",
                },
            ]
        }
        invalid = [
            ("脚本0", "脚本路径为空"),
            ("脚本1", "游戏进程名称为空"),
        ]
        with (
            patch.object(
                win.service, "collect_invalid_scripts", return_value=invalid
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
            patch.object(win.service, "collect_invalid_scripts", return_value=invalid),
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

    def test_append_delegates_to_chain_service(self):
        """追加委托 ChainService.add_script 落盘（config.yml 写回），且内存 script_list 含新脚本"""
        win = _make_window(script_count=2)
        win._persist_ui_state = lambda: None  # 隔离 gui_state.json
        entry = default_script_entry("新脚本", "python", "C:/x.py")
        win._append_script(entry)
        win.service.add_script.assert_called_once_with(entry)
        names = [s["display_name"] for s in win.all_config_data["script_list"]]
        self.assertEqual(names, ["脚本0", "脚本1", "新脚本"])

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
        win._script_service.build_script_entry.return_value = {
            "display_name": "y",
            "script_type": "external",
            "script_path": "C:/y.exe",
        }
        with patch(
            "src.gui.main_window.QFileDialog.getOpenFileName",
            return_value=("C:/y.exe", ""),
        ):
            win._add_script()
        names = [it.display_name for it in win.script_items]
        self.assertEqual(names, ["脚本0", "脚本1", "y"])
        self.assertEqual(win.script_items[-1].script_type, "external")


class TestConfigSaveSync(unittest.TestCase):
    """弹窗保存后，MainWindow 委托 ChainService.update_script 落盘并同步内存。"""

    def _make_result(self, old="脚本0", new="脚本0", **patch_overrides):
        base_patch = {
            "script_path": "C:/new.exe",
            "script_type": "external",
            "script_arguments": "",
            "check_done": "script_closed",
            "kill_script_after_done": True,
            "kill_game_after_done": False,
            "game_process_name": "",
            "block": True,
        }
        base_patch.update(patch_overrides)
        return {
            "old_script_name": old,
            "new_display_name": new,
            "config_patch": base_patch,
            "weekly_timeouts": [3600] * 7,
        }

    def _updated_config(self, win, **patch_overrides):
        """返回更新后的 all_config_data（模拟 load_config 返回）。"""
        result = {"script_list": []}
        for script in win.all_config_data["script_list"]:
            copy = dict(script)
            if copy["display_name"] == "脚本0":
                copy["script_path"] = "C:/new.exe"
                copy["script_type"] = "external"
                copy["script_arguments"] = ""
                copy["check_done"] = "script_closed"
                copy["kill_script_after_done"] = True
                copy["kill_game_after_done"] = False
                copy["game_process_name"] = ""
                copy["block"] = True
                copy.update(patch_overrides)
            result["script_list"].append(copy)
        return result

    def test_on_config_saved_delegates_to_service(self):
        """_on_script_config_saved 应委托 ChainService.update_script 落盘，
        再重新 load_config 同步内存与卡片。"""
        win = _make_window(disable_persist=True)
        win.all_config_data["script_list"][0]["script_path"] = "C:/old.exe"
        win.script_items[0].script_path = "C:/old.exe"
        win.script_items[0].script_name = "old"

        result_data = self._make_result(old="old")
        updated = self._updated_config(win)
        win.service.load_config = MagicMock(return_value=updated)

        win._on_script_config_saved(result_data)

        # 委托 ChainService
        win.service.update_script.assert_called_once_with(
            "old",
            "脚本0",
            result_data["config_patch"],
            result_data["weekly_timeouts"],
        )
        # 内存重新加载
        reloaded = next(
            s
            for s in win.all_config_data["script_list"]
            if s["display_name"] == "脚本0"
        )
        self.assertEqual(reloaded["script_path"], "C:/new.exe")
        # 卡片同步（原卡片 script_name=old 被更新为 new）
        self.assertEqual(win.script_items[0].script_path, "C:/new.exe")
        self.assertEqual(win.script_items[0].script_name, "new")

    def test_on_config_saved_handles_rename(self):
        """改名时 ChainService 处理 weekly 迁移，load_config 返回新名条目后同步卡片。"""
        win = _make_window(script_count=2, disable_persist=True)
        win.script_items[0].display_name = "脚本0"
        result_data = self._make_result(old="脚本0", new="脚本改")
        updated = {
            "script_list": [
                {
                    "display_name": "脚本改",
                    "script_type": "external",
                    "script_path": "C:/new.exe",
                },
                {"display_name": "脚本1", "script_type": "external", "script_path": ""},
            ]
        }
        win.service.load_config = MagicMock(return_value=updated)

        win._on_script_config_saved(result_data)

        win.service.update_script.assert_called_once_with(
            "脚本0",
            "脚本改",
            result_data["config_patch"],
            result_data["weekly_timeouts"],
        )
        names = [s["display_name"] for s in win.all_config_data["script_list"]]
        self.assertIn("脚本改", names)

    def test_on_config_saved_syncs_card_after_load(self):
        """卡片同步发生在 load_config 返回后，数据源为磁盘加载结果。"""
        win = _make_window(disable_persist=True)
        win.script_items[0].script_path = "C:/old.exe"
        win.script_items[0].script_name = "old"

        updated = {
            "script_list": [
                {
                    "display_name": "脚本0",
                    "script_type": "external",
                    "script_path": "C:/brand_new.exe",
                },
                {"display_name": "脚本1", "script_type": "external", "script_path": ""},
                {"display_name": "脚本2", "script_type": "external", "script_path": ""},
            ]
        }
        win.service.load_config = MagicMock(return_value=updated)

        win._on_script_config_saved(
            self._make_result(old="old", script_path="C:/brand_new.exe")
        )
        self.assertEqual(win.script_items[0].script_path, "C:/brand_new.exe")

    def test_on_config_saved_python_script(self):
        """python 脚本（key=display_name）：config_patch 不含 display_name，
        但 new_script_name 需由 new_display_name 补算，否则定位不到 new_data。"""
        win = _make_window(script_count=1, disable_persist=True)
        win.script_items[0].display_name = "日志分析"
        win.script_items[0].script_name = "日志分析"
        win.script_items[0].script_path = "C:/x.py"
        win.script_items[0].script_type = "python"

        result_data = self._make_result(
            old="日志分析",
            new="日志分析",
            script_path="C:/y.py",
            script_type="python",
        )
        updated = {
            "script_list": [
                {
                    "display_name": "日志分析",
                    "script_type": "python",
                    "script_path": "C:/y.py",
                },
            ]
        }
        win.service.load_config = MagicMock(return_value=updated)

        # 修复前：new_script_name 由 config_patch 算出空串，此处 assert 崩溃
        win._on_script_config_saved(result_data)

        self.assertEqual(win.script_items[0].script_path, "C:/y.py")
        self.assertEqual(win.script_items[0].script_name, "日志分析")


class TestPersistUiState(unittest.TestCase):
    """测试 _persist_ui_state 同步更新内存态 self._ui_state。

    修复：用户在 GUI 改选副本后，_persist_ui_state 只写盘不更新内存，
    导致点「运行」时 _generate_config 传的是过期的 self._ui_state，
    set_config 收到的 sequence 不是用户刚选的值。
    """

    def test_persist_syncs_in_memory_ui_state(self):
        """改选副本后 _persist_ui_state 同步更新 self._ui_state"""
        win = _make_window()
        win.service.save_ui_state = MagicMock()  # 隔离写盘
        win._ui_state = {}

        # 直接设置选择状态，聚焦 _persist_ui_state 逻辑
        win.script_items[0]._selected_dungeon = "凝素领域"
        win.script_items[0]._selected_sequence = 5
        win._persist_ui_state()

        self.assertEqual(
            win._ui_state.get("脚本0"),
            {"dungeon": "凝素领域", "sequence": 5},
        )

    def test_persist_overwrites_previous_selection(self):
        """已有旧选择时，改选后 self._ui_state 被新值覆盖"""
        win = _make_window()
        win.service.save_ui_state = MagicMock()
        win._ui_state = {"脚本0": {"dungeon": "无音区", "sequence": 1}}

        win.script_items[0]._selected_dungeon = "凝素领域"
        win.script_items[0]._selected_sequence = 5
        win._persist_ui_state()

        self.assertEqual(
            win._ui_state["脚本0"],
            {"dungeon": "凝素领域", "sequence": 5},
        )


if __name__ == "__main__":
    unittest.main()
