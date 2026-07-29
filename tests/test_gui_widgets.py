"""测试 src/gui/widgets.py：ScriptItem 状态、回调、拖拽与删除按钮"""
import os
import unittest
from unittest.mock import patch

# 在导入 PySide6 之前设置 offscreen 平台插件（CI 无显示器环境）
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QMimeData, QPoint, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication

from src.gui.widgets import DRAG_MIME, ScriptItem

# 全局 QApplication 实例（测试共享）
_app = QApplication.instance() or QApplication([])


class TestScriptItemGetState(unittest.TestCase):
    """测试 ScriptItem.get_state — 不含 enabled"""

    def test_get_state_no_dungeon_no_sequence(self):
        """无副本无序列时返回空 dict"""
        item = ScriptItem({'display_name': 'test', 'script_type': 'external', 'enabled': True})
        state = item.get_state()
        self.assertEqual(state, {})

    def test_get_state_with_dungeon(self):
        """有副本选择时返回 dungeon"""
        item = ScriptItem(
            {'display_name': 'test', 'script_type': 'external'},
            dungeon_options=["副本A", "副本B"],
        )
        item._on_dungeon_selected("副本B")
        state = item.get_state()
        self.assertEqual(state, {'dungeon': '副本B'})

    def test_get_state_with_sequence(self):
        """有序列时返回 sequence"""
        item = ScriptItem(
            {'display_name': 'test', 'script_type': 'external'},
            dungeon_options=['未选择', '副本A'],
            sequence_options_map={'副本A': [('共鸣者经验', '共鸣者经验'), ('武器经验', '武器经验'), ('贝币', '贝币')]},
            show_sequence=True,
        )
        item._on_dungeon_selected('副本A', '武器经验')
        state = item.get_state()
        self.assertEqual(state, {'dungeon': '副本A', 'sequence': '武器经验'})

    def test_get_state_excludes_enabled(self):
        """get_state 不包含 enabled"""
        item = ScriptItem({'display_name': 'test', 'script_type': 'external', 'enabled': True})
        state = item.get_state()
        self.assertNotIn('enabled', state)


class TestScriptItemEnabledNotPersisted(unittest.TestCase):
    """测试 enabled 不被持久化"""

    def test_toggle_does_not_trigger_callback(self):
        """toggle 不触发 _on_state_changed"""
        item = ScriptItem({'display_name': 'test', 'script_type': 'external', 'enabled': True})
        callback_called = []
        item.set_state_callback(lambda: callback_called.append(True))
        item._toggle()
        self.assertEqual(len(callback_called), 0)

    def test_enabled_always_true_ignores_config(self):
        """enabled 为纯内存态、硬编码 True，不读 script_data 也不读 saved_state"""
        item = ScriptItem(
            {'display_name': 'test', 'script_type': 'external', 'enabled': False},
            saved_state={'enabled': False, 'dungeon': 'A'},
        )
        self.assertTrue(item.enabled)


class TestScriptItemSavedState(unittest.TestCase):
    """测试 saved_state 恢复 dungeon 和 sequence"""

    def test_dungeon_restored_from_saved_state(self):
        """副本选择从 saved_state 恢复"""
        item = ScriptItem(
            {'display_name': 'test', 'script_type': 'external'},
            dungeon_options=["副本A", "副本B"],
            saved_state={'dungeon': '副本B'},
        )
        self.assertEqual(item._selected_dungeon, '副本B')

    def test_sequence_restored_from_saved_state(self):
        """序列从 saved_state 恢复"""
        item = ScriptItem(
            {'display_name': 'test', 'script_type': 'external'},
            dungeon_options=['未选择', '副本A'],
            sequence_options_map={'副本A': [('共鸣者经验', '共鸣者经验'), ('武器经验', '武器经验'), ('贝币', '贝币')]},
            show_sequence=True,
            saved_state={'dungeon': '副本A', 'sequence': '武器经验'},
        )
        self.assertEqual(item._selected_dungeon, '副本A')
        self.assertEqual(item._selected_sequence, '武器经验')

    def test_dungeon_not_restored_if_not_in_options(self):
        """saved_state 中的副本不在选项中时不恢复"""
        item = ScriptItem(
            {'display_name': 'test', 'script_type': 'external'},
            dungeon_options=["副本A", "副本B"],
            saved_state={'dungeon': '不存在'},
        )
        # 不在选项中，不恢复
        self.assertIsNone(item._selected_dungeon)


class TestScriptItemCallback(unittest.TestCase):
    """测试 dungeon/sequence 变化触发回调"""

    def test_dungeon_change_triggers_callback(self):
        """切换副本触发回调"""
        item = ScriptItem(
            {'display_name': 'test', 'script_type': 'external'},
            dungeon_options=["副本A", "副本B"],
        )
        called = []
        item.set_state_callback(lambda: called.append(True))
        item._on_dungeon_selected("副本B")
        self.assertEqual(len(called), 1)

    def test_sequence_change_triggers_callback(self):
        """修改序列触发回调"""
        item = ScriptItem(
            {'display_name': 'test', 'script_type': 'external'},
            dungeon_options=['未选择', '副本A'],
            sequence_options_map={'副本A': [('共鸣者经验', '共鸣者经验'), ('武器经验', '武器经验'), ('贝币', '贝币')]},
            show_sequence=True,
        )
        called = []
        item.set_state_callback(lambda: called.append(True))
        item._on_dungeon_selected('副本A', '武器经验')
        # 选副本+序列一次性触发 1 次
        self.assertEqual(len(called), 1)


class TestScriptItemDragDrop(unittest.TestCase):
    """测试 ScriptItem 拖拽手柄与 drop 事件"""

    def test_handle_created_and_accepts_drops(self):
        """构造后存在拖拽手柄且接受 drop"""
        item = ScriptItem({'display_name': 'A', 'script_type': 'external'})
        self.assertIsNotNone(item.handle)
        self.assertTrue(item.acceptDrops())

    def test_dragEnterEvent_accepts_our_mime(self):
        """dragEnterEvent 接受本应用的自定义 MIME"""
        item = ScriptItem({'display_name': 'A', 'script_type': 'external'})
        item._reorder_callback = lambda src, dst: None
        mime = QMimeData()
        mime.setData(DRAG_MIME, b'B')
        event = QDragEnterEvent(QPoint(0, 0), Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
        event.ignore()
        item.dragEnterEvent(event)
        self.assertTrue(event.isAccepted())

    def test_dragEnterEvent_ignores_unknown_mime(self):
        """dragEnterEvent 忽略未知 MIME"""
        item = ScriptItem({'display_name': 'A', 'script_type': 'external'})
        mime = QMimeData()
        mime.setText('B')
        event = QDragEnterEvent(QPoint(0, 0), Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
        event.accept()
        item.dragEnterEvent(event)
        self.assertFalse(event.isAccepted())

    def test_dropEvent_calls_reorder_callback(self):
        """dropEvent 以 (src_name, dst_name) 调用重排回调"""
        item = ScriptItem({'display_name': 'A', 'script_type': 'external'})
        called = []
        item._reorder_callback = lambda src, dst: called.append((src, dst))
        mime = QMimeData()
        mime.setData(DRAG_MIME, b'B')
        event = QDropEvent(QPoint(0, 0), Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
        item.dropEvent(event)
        self.assertEqual(called, [('B', 'A')])
        self.assertTrue(event.isAccepted())

    def test_dropEvent_ignores_unknown_mime(self):
        """dropEvent 忽略未知 MIME 且不触发回调"""
        item = ScriptItem({'display_name': 'A', 'script_type': 'external'})
        called = []
        item._reorder_callback = lambda src, dst: called.append((src, dst))
        mime = QMimeData()
        mime.setText('B')
        event = QDropEvent(QPoint(0, 0), Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
        item.dropEvent(event)
        self.assertEqual(called, [])
        self.assertFalse(event.isAccepted())

    def test_dropEvent_noop_when_same_name(self):
        """拖到自己身上（src==dst）时不触发重排"""
        item = ScriptItem({'display_name': 'A', 'script_type': 'external'})
        called = []
        item._reorder_callback = lambda src, dst: called.append((src, dst))
        mime = QMimeData()
        mime.setData(DRAG_MIME, b'A')
        event = QDropEvent(QPoint(0, 0), Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
        item.dropEvent(event)
        self.assertEqual(called, [])
        self.assertTrue(event.isAccepted())


class TestScriptItemDeleteButton(unittest.TestCase):
    """测试删除按钮接线"""

    def test_script_item_delete_button_wired(self):
        """脚本项的删除按钮点击应触发注入的回调，并传入 display_name"""
        called = []
        item = ScriptItem(
            {'display_name': 'X', 'script_type': 'external'},
            delete_callback=lambda name: called.append(name),
        )
        self.assertTrue(hasattr(item, 'delete_btn'))
        item._on_delete_clicked()
        self.assertEqual(called, ['X'])


class TestSyncFromScriptData(unittest.TestCase):
    """测试配置弹窗保存后同步内存态（路径/类型/副本按钮）。"""

    def _show(self, item):
        item.show()
        _app.processEvents()

    def test_sync_updates_path_and_type(self):
        """sync 更新 script_path 与 script_type"""
        item = ScriptItem(
            {'display_name': 't', 'script_type': 'external'},
            dungeon_options=["副本A", "副本B"],
        )
        item.sync_from_script_data(
            {'display_name': 't', 'script_type': 'python', 'script_path': 'C:/y.py'})
        self.assertEqual(item.script_path, 'C:/y.py')
        self.assertEqual(item.script_type, 'python')

    def test_sync_to_python_hides_dungeon_button_and_clears_selection(self):
        """改为 python 后：副本按钮隐藏且已选副本被清除"""
        item = ScriptItem(
            {'display_name': 't', 'script_type': 'external'},
            dungeon_options=["副本A", "副本B"],
        )
        item._on_dungeon_selected("副本A")
        self.assertIsNotNone(item.dungeon_btn)
        self._show(item)
        item.sync_from_script_data(
            {'display_name': 't', 'script_type': 'python', 'script_path': 'C:/y.py'})
        _app.processEvents()
        self.assertFalse(item.dungeon_btn.isVisible())
        self.assertIsNone(item._selected_dungeon)
        self.assertIsNone(item._selected_sequence)

    def test_sync_to_external_creates_dungeon_button(self):
        """改为 external（有副本）后：自动创建并显示副本按钮"""
        item = ScriptItem(
            {'display_name': 't', 'script_type': 'python'},
            dungeon_options=["副本A", "副本B"],
        )
        self.assertIsNone(item.dungeon_btn)
        self._show(item)
        item.sync_from_script_data(
            {'display_name': 't', 'script_type': 'external', 'script_path': 'C:/y.exe'})
        _app.processEvents()
        self.assertIsNotNone(item.dungeon_btn)
        self.assertTrue(item.dungeon_btn.isVisible())


class TestScriptItemOpenButton(unittest.TestCase):
    """测试打开脚本按钮：用 subscript.get_script_path 解析并启动 exe（不依赖交互式消息框）"""

    def test_open_btn_exists_and_is_wired(self):
        """构造后存在打开脚本按钮，且点击触发 _open_script"""
        item = ScriptItem({'display_name': '鸣潮', 'script_type': 'external',
                           'script_path': 'C:/games/run.exe'})
        self.assertTrue(hasattr(item, 'open_btn'))
        called = []
        item._open_script = lambda: called.append(True)
        item.open_btn.clicked.disconnect()
        item.open_btn.clicked.connect(item._open_script)
        item.open_btn.click()
        self.assertEqual(called, [True])

    def test_open_script_launches_exe(self):
        """已解析出 script_path 时，以 startfile 启动该 exe"""
        item = ScriptItem({'display_name': '鸣潮', 'script_type': 'external',
                           'script_path': 'C:/games/run.exe'})
        exe = 'C:/games/run.exe'
        with patch('os.startfile', create=True) as mock_start, \
             patch('src.gui.widgets.get_script_path', return_value=exe):
            item._open_script()
        mock_start.assert_called_once_with(exe)

    def test_open_script_missing_shows_warning(self):
        """get_script_path 因路径缺失/不存在抛错时弹出警告且不调用 startfile"""
        item = ScriptItem({'display_name': '我的自定义脚本', 'script_type': 'external',
                           'script_path': 'C:/games/run.exe'})
        with patch('os.startfile', create=True) as mock_start, \
             patch('src.gui.widgets.get_script_path',
                   side_effect=AssertionError("exe 不存在: C:/x")), \
             patch('src.gui.widgets.QMessageBox.warning') as mock_warn:
            item._open_script()
        mock_start.assert_not_called()
        mock_warn.assert_called_once()


if __name__ == '__main__':
    unittest.main()
