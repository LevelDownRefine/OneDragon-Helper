"""测试 src/gui/widgets.py：ScriptItem 状态、回调、拖拽与删除按钮"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# 在导入 PySide6 之前设置 offscreen 平台插件（CI 无显示器环境）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, QPoint, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QImage
from PySide6.QtWidgets import QApplication

from src.gui.utils import (
    get_icon_source,
    get_script_icon,
)
from src.gui.widgets import _EXE_ICON_PIXMAP_CACHE, DRAG_MIME, ScriptItem

# 全局 QApplication 实例（测试共享）
_app = QApplication.instance() or QApplication([])


class TestScriptItemGetState(unittest.TestCase):
    """测试 ScriptItem.get_state — 不含 enabled"""

    def test_get_state_no_dungeon_no_sequence(self):
        """无副本无序列时返回空 dict"""
        item = ScriptItem(
            {"display_name": "test", "script_type": "external", "enabled": True}
        )
        state = item.get_state()
        self.assertEqual(state, {})

    def test_get_state_with_dungeon(self):
        """有副本选择时返回 dungeon"""
        item = ScriptItem(
            {"display_name": "test", "script_type": "external"},
            dungeon_options=["副本A", "副本B"],
        )
        item._on_dungeon_selected("副本B")
        state = item.get_state()
        self.assertEqual(state, {"dungeon": "副本B"})

    def test_get_state_with_sequence(self):
        """有序列时返回 sequence"""
        item = ScriptItem(
            {"display_name": "test", "script_type": "external"},
            dungeon_options=["未选择", "副本A"],
            sequence_options_map={
                "副本A": [
                    ("共鸣者经验", "共鸣者经验"),
                    ("武器经验", "武器经验"),
                    ("贝币", "贝币"),
                ]
            },
            show_sequence=True,
        )
        item._on_dungeon_selected("副本A", "武器经验")
        state = item.get_state()
        self.assertEqual(state, {"dungeon": "副本A", "sequence": "武器经验"})

    def test_get_state_excludes_enabled(self):
        """get_state 不包含 enabled"""
        item = ScriptItem(
            {"display_name": "test", "script_type": "external", "enabled": True}
        )
        state = item.get_state()
        self.assertNotIn("enabled", state)


class TestScriptItemEnabledNotPersisted(unittest.TestCase):
    """测试 enabled 不被持久化"""

    def test_toggle_does_not_trigger_callback(self):
        """toggle 不触发 _on_state_changed"""
        item = ScriptItem(
            {"display_name": "test", "script_type": "external", "enabled": True}
        )
        callback_called = []
        item.set_state_callback(lambda: callback_called.append(True))
        item._toggle()
        self.assertEqual(len(callback_called), 0)

    def test_enabled_always_true_ignores_config(self):
        """enabled 为纯内存态、硬编码 True，不读 script_data 也不读 saved_state"""
        item = ScriptItem(
            {"display_name": "test", "script_type": "external", "enabled": False},
            saved_state={"enabled": False, "dungeon": "A"},
        )
        self.assertTrue(item.enabled)


class TestScriptItemSavedState(unittest.TestCase):
    """测试 saved_state 恢复 dungeon 和 sequence"""

    def test_dungeon_restored_from_saved_state(self):
        """副本选择从 saved_state 恢复"""
        item = ScriptItem(
            {"display_name": "test", "script_type": "external"},
            dungeon_options=["副本A", "副本B"],
            saved_state={"dungeon": "副本B"},
        )
        self.assertEqual(item._selected_dungeon, "副本B")

    def test_sequence_restored_from_saved_state(self):
        """序列从 saved_state 恢复"""
        item = ScriptItem(
            {"display_name": "test", "script_type": "external"},
            dungeon_options=["未选择", "副本A"],
            sequence_options_map={
                "副本A": [
                    ("共鸣者经验", "共鸣者经验"),
                    ("武器经验", "武器经验"),
                    ("贝币", "贝币"),
                ]
            },
            show_sequence=True,
            saved_state={"dungeon": "副本A", "sequence": "武器经验"},
        )
        self.assertEqual(item._selected_dungeon, "副本A")
        self.assertEqual(item._selected_sequence, "武器经验")

    def test_dungeon_not_restored_if_not_in_options(self):
        """saved_state 中的副本不在选项中时不恢复"""
        item = ScriptItem(
            {"display_name": "test", "script_type": "external"},
            dungeon_options=["副本A", "副本B"],
            saved_state={"dungeon": "不存在"},
        )
        # 不在选项中，不恢复
        self.assertIsNone(item._selected_dungeon)


class TestScriptItemCallback(unittest.TestCase):
    """测试 dungeon/sequence 变化触发回调"""

    def test_dungeon_change_triggers_callback(self):
        """切换副本触发回调"""
        item = ScriptItem(
            {"display_name": "test", "script_type": "external"},
            dungeon_options=["副本A", "副本B"],
        )
        called = []
        item.set_state_callback(lambda: called.append(True))
        item._on_dungeon_selected("副本B")
        self.assertEqual(len(called), 1)

    def test_sequence_change_triggers_callback(self):
        """修改序列触发回调"""
        item = ScriptItem(
            {"display_name": "test", "script_type": "external"},
            dungeon_options=["未选择", "副本A"],
            sequence_options_map={
                "副本A": [
                    ("共鸣者经验", "共鸣者经验"),
                    ("武器经验", "武器经验"),
                    ("贝币", "贝币"),
                ]
            },
            show_sequence=True,
        )
        called = []
        item.set_state_callback(lambda: called.append(True))
        item._on_dungeon_selected("副本A", "武器经验")
        # 选副本+序列一次性触发 1 次
        self.assertEqual(len(called), 1)


class TestScriptItemDragDrop(unittest.TestCase):
    """测试 ScriptItem 拖拽手柄与 drop 事件"""

    def test_handle_created_and_accepts_drops(self):
        """构造后存在拖拽手柄且接受 drop"""
        item = ScriptItem({"display_name": "A", "script_type": "external"})
        self.assertIsNotNone(item.handle)
        self.assertTrue(item.acceptDrops())

    def test_dragEnterEvent_accepts_our_mime(self):
        """dragEnterEvent 接受本应用的自定义 MIME"""
        item = ScriptItem({"display_name": "A", "script_type": "external"})
        item._reorder_callback = lambda src, dst: None
        mime = QMimeData()
        mime.setData(DRAG_MIME, b"B")
        event = QDragEnterEvent(
            QPoint(0, 0), Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier
        )
        event.ignore()
        item.dragEnterEvent(event)
        self.assertTrue(event.isAccepted())

    def test_dragEnterEvent_ignores_unknown_mime(self):
        """dragEnterEvent 忽略未知 MIME"""
        item = ScriptItem({"display_name": "A", "script_type": "external"})
        mime = QMimeData()
        mime.setText("B")
        event = QDragEnterEvent(
            QPoint(0, 0), Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier
        )
        event.accept()
        item.dragEnterEvent(event)
        self.assertFalse(event.isAccepted())

    def test_dropEvent_calls_reorder_callback(self):
        """dropEvent 以 (src_name, dst_name) 调用重排回调"""
        item = ScriptItem({"display_name": "A", "script_type": "external"})
        called = []
        item._reorder_callback = lambda src, dst: called.append((src, dst))
        mime = QMimeData()
        mime.setData(DRAG_MIME, b"B")
        event = QDropEvent(
            QPoint(0, 0), Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier
        )
        item.dropEvent(event)
        self.assertEqual(called, [("B", "A")])
        self.assertTrue(event.isAccepted())

    def test_dropEvent_ignores_unknown_mime(self):
        """dropEvent 忽略未知 MIME 且不触发回调"""
        item = ScriptItem({"display_name": "A", "script_type": "external"})
        called = []
        item._reorder_callback = lambda src, dst: called.append((src, dst))
        mime = QMimeData()
        mime.setText("B")
        event = QDropEvent(
            QPoint(0, 0), Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier
        )
        item.dropEvent(event)
        self.assertEqual(called, [])
        self.assertFalse(event.isAccepted())

    def test_dropEvent_noop_when_same_name(self):
        """拖到自己身上（src==dst）时不触发重排"""
        item = ScriptItem({"display_name": "A", "script_type": "external"})
        called = []
        item._reorder_callback = lambda src, dst: called.append((src, dst))
        mime = QMimeData()
        mime.setData(DRAG_MIME, b"A")
        event = QDropEvent(
            QPoint(0, 0), Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier
        )
        item.dropEvent(event)
        self.assertEqual(called, [])
        self.assertTrue(event.isAccepted())


class TestScriptItemDeleteButton(unittest.TestCase):
    """测试删除按钮接线"""

    def test_script_item_delete_button_wired(self):
        """脚本项的删除按钮点击应触发注入的回调，并传入 display_name"""
        called = []
        item = ScriptItem(
            {"display_name": "X", "script_type": "external"},
            delete_callback=lambda name: called.append(name),
        )
        self.assertTrue(hasattr(item, "overflow_btn"))
        item._on_delete_clicked()
        self.assertEqual(called, ["X"])


class TestSyncFromScriptData(unittest.TestCase):
    """测试配置弹窗保存后同步内存态（路径/类型/副本按钮）。"""

    def _show(self, item):
        item.show()
        _app.processEvents()

    def test_sync_updates_path_and_type(self):
        """sync 更新 script_path 与 script_type"""
        item = ScriptItem(
            {"display_name": "t", "script_type": "external"},
            dungeon_options=["副本A", "副本B"],
        )
        item.sync_from_script_data(
            {"display_name": "t", "script_type": "python", "script_path": "C:/y.py"}
        )
        self.assertEqual(item.script_path, "C:/y.py")
        self.assertEqual(item.script_type, "python")

    def test_sync_to_python_hides_dungeon_button_and_clears_selection(self):
        """改为 python 后：副本按钮隐藏且已选副本被清除"""
        item = ScriptItem(
            {"display_name": "t", "script_type": "external"},
            dungeon_options=["副本A", "副本B"],
        )
        item._on_dungeon_selected("副本A")
        self.assertIsNotNone(item.dungeon_btn)
        self._show(item)
        item.sync_from_script_data(
            {"display_name": "t", "script_type": "python", "script_path": "C:/y.py"}
        )
        _app.processEvents()
        self.assertFalse(item.dungeon_btn.isVisible())
        self.assertIsNone(item._selected_dungeon)
        self.assertIsNone(item._selected_sequence)

    def test_sync_to_external_creates_dungeon_button(self):
        """改为 external（有副本）后：自动创建并显示副本按钮"""
        item = ScriptItem(
            {"display_name": "t", "script_type": "python"},
            dungeon_options=["副本A", "副本B"],
        )
        self.assertIsNone(item.dungeon_btn)
        self._show(item)
        item.sync_from_script_data(
            {"display_name": "t", "script_type": "external", "script_path": "C:/y.exe"}
        )
        _app.processEvents()
        self.assertIsNotNone(item.dungeon_btn)
        self.assertTrue(item.dungeon_btn.isVisible())


class TestScriptItemOpenButton(unittest.TestCase):
    """测试打开脚本逻辑：python 用解释器运行，external 启动 exe（不依赖交互式消息框）"""

    def test_open_script_external_launches_exe(self):
        """external 脚本：解析出 script_path 后以 startfile 启动该 exe"""
        item = ScriptItem(
            {
                "display_name": "鸣潮",
                "script_type": "external",
                "script_path": "C:/games/run.exe",
            }
        )
        exe = "C:/games/run.exe"
        with (
            patch("os.startfile", create=True) as mock_start,
            patch("src.gui.widgets.get_script_path", return_value=exe),
        ):
            item._open_script()
        mock_start.assert_called_once_with(exe)

    def test_open_script_external_missing_shows_msg(self):
        """external 脚本 get_script_path 抛错时弹出清晰提示且不调用 startfile"""
        item = ScriptItem(
            {
                "display_name": "我的自定义脚本",
                "script_type": "external",
                "script_path": "C:/games/run.exe",
            }
        )
        with (
            patch("os.startfile", create=True) as mock_start,
            patch(
                "src.gui.widgets.get_script_path",
                side_effect=AssertionError("exe 不存在: C:/x"),
            ),
            patch("src.gui.widgets._styled_msg_box") as mock_box,
        ):
            item._open_script()
        mock_start.assert_not_called()
        mock_box.assert_called_once()

    def test_open_script_python_runs_with_interpreter(self):
        """python 脚本：命令构造委派给 build_script_command，_open_script 只负责 spawn"""
        item = ScriptItem(
            {
                "display_name": "静音",
                "script_type": "python",
                "script_path": "C:/proj/src/python_script/mute.py",
            }
        )
        fake_cmd = [
            sys.executable,
            "-m",
            "src.runner.launcher",
            "--script",
            "C:/proj/src/python_script/mute.py",
        ]
        with (
            patch(
                "src.gui.widgets.build_script_command",
                return_value=(fake_cmd, "C:/root", None),
            ) as bsc,
            patch("src.gui.widgets.subprocess.Popen") as mock_popen,
            patch("os.path.isfile", return_value=True),
        ):
            item._open_script()
        bsc.assert_called_once_with(["--script", "C:/proj/src/python_script/mute.py"])
        mock_popen.assert_called_once()
        args, kwargs = mock_popen.call_args
        self.assertEqual(list(args[0]), fake_cmd)
        self.assertEqual(kwargs.get("cwd"), "C:/root")

    def test_open_script_python_missing_file_shows_msg(self):
        """python 脚本文件不存在时弹出清晰提示且不启动进程"""
        item = ScriptItem(
            {
                "display_name": "静音",
                "script_type": "python",
                "script_path": "C:/nope/mute.py",
            }
        )
        with (
            patch("src.gui.widgets.subprocess.Popen") as mock_popen,
            patch("os.path.isfile", return_value=False),
            patch("src.gui.widgets._styled_msg_box") as mock_box,
        ):
            item._open_script()
        mock_popen.assert_not_called()
        mock_box.assert_called_once()


class TestScriptItemOpenConfigButton(unittest.TestCase):
    """测试打开脚本配置逻辑：python 打开 .py 源文件，external 打开内部 config 文本文件"""

    def test_open_config_external_opens_resolved_config(self):
        """external 已适配：用 get_config_path 解析并以 startfile 打开配置文件"""
        item = ScriptItem(
            {
                "display_name": "鸣潮",
                "script_type": "external",
                "script_path": "C:/games/run.exe",
            }
        )
        cfg = "C:/games/config/DailyTask.json"
        with (
            patch("os.startfile", create=True) as mock_start,
            patch("src.gui.widgets.get_config_path", return_value=cfg),
        ):
            item._open_script_config()
        mock_start.assert_called_once_with(cfg)

    def test_open_config_external_missing_shows_msg(self):
        """external 未适配/文件缺失时弹出清晰提示且不调用 startfile"""
        item = ScriptItem(
            {
                "display_name": "我的自定义脚本",
                "script_type": "external",
                "script_path": "C:/games/run.exe",
            }
        )
        with (
            patch("os.startfile", create=True) as mock_start,
            patch(
                "src.gui.widgets.get_config_path",
                side_effect=AssertionError("未适配脚本: 我的自定义脚本"),
            ),
            patch("src.gui.widgets._styled_msg_box") as mock_box,
        ):
            item._open_script_config()
        mock_start.assert_not_called()
        mock_box.assert_called_once()

    def test_open_config_python_opens_py_file(self):
        """python 脚本：打开其 .py 源文件（os.startfile）"""
        item = ScriptItem(
            {
                "display_name": "静音",
                "script_type": "python",
                "script_path": "C:/proj/src/python_script/mute.py",
            }
        )
        with (
            patch("os.startfile", create=True) as mock_start,
            patch("os.path.isfile", return_value=True),
        ):
            item._open_script_config()
        mock_start.assert_called_once_with("C:/proj/src/python_script/mute.py")

    def test_open_config_python_missing_file_shows_msg(self):
        """python 脚本文件不存在时弹出清晰提示且不调用 startfile"""
        item = ScriptItem(
            {
                "display_name": "静音",
                "script_type": "python",
                "script_path": "C:/nope/mute.py",
            }
        )
        with (
            patch("os.startfile", create=True) as mock_start,
            patch("os.path.isfile", return_value=False),
            patch("src.gui.widgets._styled_msg_box") as mock_box,
        ):
            item._open_script_config()
        mock_start.assert_not_called()
        mock_box.assert_called_once()


class TestScriptItemOverflowMenu(unittest.TestCase):
    """测试 ⋮ 溢出菜单：把删除/打开脚本/打开配置/配置都收进菜单（不依赖真实弹窗）"""

    def _build(self, **kwargs):
        return ScriptItem(
            {
                "display_name": "鸣潮",
                "script_type": "external",
                "script_path": "C:/games/run.exe",
            },
            **kwargs,
        )

    def test_overflow_btn_exists(self):
        """构造后存在 ⋮ 溢出按钮"""
        item = self._build()
        self.assertTrue(hasattr(item, "overflow_btn"))

    def test_menu_contains_expected_actions(self):
        """菜单含 启动脚本 / 配置文件 / 脚本参数 / 删除脚本 四项"""
        item = self._build()
        menu = item._build_overflow_menu()
        texts = [a.text() for a in menu.actions()]
        self.assertIn("启动脚本", texts)
        self.assertIn("配置文件", texts)
        self.assertIn("脚本参数", texts)
        self.assertIn("删除脚本", texts)

    def test_menu_open_script_action_triggers_handler(self):
        """点击「打开脚本」菜单项应触发 _open_script"""
        item = self._build()
        called = []
        item._open_script = lambda: called.append(True)
        menu = item._build_overflow_menu()
        action = next(a for a in menu.actions() if a.text() == "启动脚本")
        action.trigger()
        self.assertEqual(called, [True])

    def test_menu_delete_action_disabled_without_callback(self):
        """无删除回调时，菜单里的「删除」项应被禁用"""
        item = self._build()  # 未传 delete_callback
        menu = item._build_overflow_menu()
        action = next(a for a in menu.actions() if a.text() == "删除脚本")
        self.assertFalse(action.isEnabled())


class TestGetScriptIcon(unittest.TestCase):
    """测试 get_script_icon：external 用 exe 自带图标，其余用默认图标。"""

    def test_python_script_uses_default_icon(self):
        """python 脚本无自带图标 → 返回非空的默认图标"""
        icon = get_script_icon(
            {"display_name": "静音", "script_type": "python", "script_path": "x.py"}
        )
        self.assertFalse(icon.isNull())

    def test_external_missing_exe_falls_back_to_default(self):
        """external 但 exe 不存在 → 回退到非空的默认图标（不崩溃）"""
        icon = get_script_icon(
            {
                "display_name": "x",
                "script_type": "external",
                "script_path": "C:/nope/run.exe",
            }
        )
        self.assertFalse(icon.isNull())

    def test_external_existing_exe_uses_own_icon(self):
        """external 且 exe 存在 → 返回该 exe 自带图标（非空）。"""
        icon = get_script_icon(
            {
                "display_name": "x",
                "script_type": "external",
                "script_path": sys.executable,
            }
        )
        self.assertFalse(icon.isNull())

    @patch("src.gui.widgets._ICON_EXTRACTION_AVAILABLE", True)
    def test_external_icon_deferred_not_eager(self):
        """external 的 exe 图标延迟加载：构造时不同步提取，交由后台线程，主线程只做转换。

        用假 QThreadPool 捕获提交的 worker，验证构造阶段不内联执行提取；随后手动触发
        worker.run()（模拟后台线程：提取 HICON → GDI 转 QImage → 销毁句柄），再
        processEvents() 把结果信号送回主线程设置 pixmap。
        """
        captured = []
        fake_pool = MagicMock()
        fake_pool.start.side_effect = lambda runnable: captured.append(runnable)

        with patch(
            "src.gui.widgets.QThreadPool.globalInstance", return_value=fake_pool
        ):
            item = ScriptItem(
                {
                    "display_name": "x",
                    "script_type": "external",
                    "script_path": sys.executable,
                }
            )
        # 构造返回后 worker 已被提交（延迟），但尚未执行
        self.assertEqual(len(captured), 1)
        # 占位图标已设置（默认图标），非空
        self.assertFalse(item.icon_label.pixmap().isNull())

        real_img = QImage(28, 28, QImage.Format_RGBA8888)
        with (
            patch("src.gui.widgets._extract_hicon", return_value=0x1234),
            patch("src.gui.widgets._hicon_to_qimage", return_value=real_img),
        ):
            captured[0].run()  # 模拟后台线程：提取并转 QImage
        # 主线程收到信号后把 QImage 转成 QPixmap 并设置（跨线程信号经事件循环投递）
        QApplication.processEvents()
        self.assertFalse(item.icon_label.pixmap().isNull())
        # 已写入图标缓存（key 为该 exe 路径）
        self.assertIn(sys.executable, _EXE_ICON_PIXMAP_CACHE)

    def test_star_rail_swaps_to_launcher_icon(self):
        """崩铁：同目录存在 March7th Launcher.exe 时，图标源换成它而非自身 exe。"""
        data = {
            "display_name": "崩铁",
            "script_type": "external",
            "script_path": "D:/game_helper/March7thAssistant/March7th Assistant.exe",
        }
        with patch("src.gui.utils.os.path.isfile", return_value=True):
            self.assertEqual(
                get_icon_source(data),
                os.path.join(
                    "D:/game_helper/March7thAssistant", "March7th Launcher.exe"
                ),
            )

    def test_star_rail_launcher_missing_uses_own_exe(self):
        """崩铁：若同目录没有 March7th Launcher.exe，则仍用自身 exe 作为图标源。"""
        data = {
            "display_name": "崩铁",
            "script_type": "external",
            "script_path": "D:/game_helper/March7thAssistant/March7th Assistant.exe",
        }
        with patch("src.gui.utils.os.path.isfile", return_value=False):
            self.assertEqual(
                get_icon_source(data),
                "D:/game_helper/March7thAssistant/March7th Assistant.exe",
            )


if __name__ == "__main__":
    unittest.main()
