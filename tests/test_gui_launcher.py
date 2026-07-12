"""测试 GUI 状态持久化功能"""
import os
import json
import warnings
import unittest
from unittest.mock import patch, MagicMock

# 在导入 PySide6 之前设置 offscreen 平台插件（CI 无显示器环境）
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication

import gui_launcher


# 全局 QApplication 实例（测试共享）
_app = QApplication.instance() or QApplication([])


class TestLoadUiState(unittest.TestCase):
    """测试 _load_ui_state"""

    def test_returns_empty_when_file_not_exists(self):
        """文件不存在时返回空 dict"""
        with patch('gui_launcher.os.path.exists', return_value=False):
            result = gui_launcher._load_ui_state()
        self.assertEqual(result, {})

    def test_loads_valid_json(self):
        """正常 JSON 文件正确读取"""
        data = {"鸣潮": {"dungeon": "朔雷之鳞", "sequence": 2}}
        with patch('gui_launcher.os.path.exists', return_value=True), \
             patch('builtins.open', mock_open_with_data(data)):
            result = gui_launcher._load_ui_state()
        self.assertEqual(result, data)

    def test_warns_on_invalid_json(self):
        """无效 JSON 抛出警告而非静默"""
        with patch('gui_launcher.os.path.exists', return_value=True), \
             patch('builtins.open', mock_open_with_data_raw('not valid json')), \
             warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')
            result = gui_launcher._load_ui_state()
        self.assertEqual(result, {})
        self.assertEqual(len(w), 1)
        self.assertIn('读取 UI 状态文件失败', str(w[0].message))

    def test_warns_on_os_error(self):
        """OSError 时抛出警告"""
        with patch('gui_launcher.os.path.exists', return_value=True), \
             patch('builtins.open', side_effect=OSError("permission denied")), \
             warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')
            result = gui_launcher._load_ui_state()
        self.assertEqual(result, {})
        self.assertEqual(len(w), 1)
        self.assertIn('读取 UI 状态文件失败', str(w[0].message))


class TestSaveUiState(unittest.TestCase):
    """测试 _save_ui_state"""

    def test_writes_json_file(self):
        """正常写入 JSON"""
        captured = {}

        def fake_open(file, mode, encoding=None):
            from io import StringIO
            buf = StringIO()
            captured['buf'] = buf
            captured['mode'] = mode
            m = MagicMock()
            m.__enter__ = MagicMock(return_value=buf)
            m.__exit__ = MagicMock(return_value=False)
            return m

        state = {"鸣潮": {"dungeon": "A", "sequence": 1}}
        with patch('builtins.open', side_effect=fake_open):
            gui_launcher._save_ui_state(state)

        written = json.loads(captured['buf'].getvalue())
        self.assertEqual(written, state)
        self.assertEqual(captured['mode'], 'w')

    def test_warns_on_os_error(self):
        """写入失败时抛出警告"""
        with patch('builtins.open', side_effect=OSError("disk full")), \
             warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')
            gui_launcher._save_ui_state({"test": 1})
        self.assertEqual(len(w), 1)
        self.assertIn('保存 UI 状态文件失败', str(w[0].message))


class TestScriptItemGetState(unittest.TestCase):
    """测试 ScriptItem.get_state — 不含 enabled"""

    def test_get_state_no_dungeon_no_sequence(self):
        """无副本无序列时返回空 dict"""
        item = gui_launcher.ScriptItem({'display_name': 'test', 'enabled': True})
        state = item.get_state()
        self.assertEqual(state, {})

    def test_get_state_with_dungeon(self):
        """有副本选择时返回 dungeon"""
        item = gui_launcher.ScriptItem(
            {'display_name': 'test', 'script_type': 'external'},
            dungeon_options=["副本A", "副本B"],
        )
        item.dungeon_combo.setCurrentText("副本B")
        state = item.get_state()
        self.assertEqual(state, {'dungeon': '副本B'})

    def test_get_state_with_sequence(self):
        """有序列时返回 sequence"""
        item = gui_launcher.ScriptItem(
            {'display_name': 'test', 'script_type': 'external'},
            dungeon_options=['未选择', '副本A'],
            sequence_options_map={'副本A': ['共鸣者经验', '武器经验', '贝币']},
            show_sequence=True,
        )
        item.dungeon_combo.setCurrentText('副本A')
        item.sequence_combo.setCurrentText('武器经验')
        state = item.get_state()
        self.assertEqual(state, {'dungeon': '副本A', 'sequence': '武器经验'})

    def test_get_state_excludes_enabled(self):
        """get_state 不包含 enabled"""
        item = gui_launcher.ScriptItem({'display_name': 'test', 'enabled': True})
        state = item.get_state()
        self.assertNotIn('enabled', state)


class TestScriptItemEnabledNotPersisted(unittest.TestCase):
    """测试 enabled 不被持久化"""

    def test_toggle_does_not_trigger_callback(self):
        """toggle 不触发 _on_state_changed"""
        item = gui_launcher.ScriptItem({'display_name': 'test', 'enabled': True})
        callback_called = []
        item.set_state_callback(lambda: callback_called.append(True))
        item._toggle()
        self.assertEqual(len(callback_called), 0)

    def test_enabled_from_script_data_not_saved_state(self):
        """enabled 从 script_data 取，不从 saved_state 恢复"""
        item = gui_launcher.ScriptItem(
            {'display_name': 'test', 'enabled': True},
            saved_state={'enabled': False, 'dungeon': 'A'},
        )
        self.assertTrue(item.enabled)


class TestScriptItemSavedState(unittest.TestCase):
    """测试 saved_state 恢复 dungeon 和 sequence"""

    def test_dungeon_restored_from_saved_state(self):
        """副本选择从 saved_state 恢复"""
        item = gui_launcher.ScriptItem(
            {'display_name': 'test', 'script_type': 'external'},
            dungeon_options=["副本A", "副本B"],
            saved_state={'dungeon': '副本B'},
        )
        self.assertEqual(item.dungeon_combo.currentText(), '副本B')

    def test_sequence_restored_from_saved_state(self):
        """序列从 saved_state 恢复"""
        item = gui_launcher.ScriptItem(
            {'display_name': 'test', 'script_type': 'external'},
            dungeon_options=['未选择', '副本A'],
            sequence_options_map={'副本A': ['共鸣者经验', '武器经验', '贝币']},
            show_sequence=True,
            saved_state={'dungeon': '副本A', 'sequence': '武器经验'},
        )
        self.assertEqual(item.dungeon_combo.currentText(), '副本A')
        self.assertEqual(item.sequence_combo.currentText(), '武器经验')

    def test_dungeon_not_restored_if_not_in_options(self):
        """saved_state 中的副本不在选项中时不恢复"""
        item = gui_launcher.ScriptItem(
            {'display_name': 'test', 'script_type': 'external'},
            dungeon_options=["副本A", "副本B"],
            saved_state={'dungeon': '不存在'},
        )
        # 保持默认（第一个）
        self.assertEqual(item.dungeon_combo.currentText(), '副本A')


class TestScriptItemCallback(unittest.TestCase):
    """测试 dungeon/sequence 变化触发回调"""

    def test_dungeon_change_triggers_callback(self):
        """切换副本触发回调"""
        item = gui_launcher.ScriptItem(
            {'display_name': 'test', 'script_type': 'external'},
            dungeon_options=["副本A", "副本B"],
        )
        called = []
        item.set_state_callback(lambda: called.append(True))
        item.dungeon_combo.setCurrentText("副本B")
        self.assertEqual(len(called), 1)

    def test_sequence_change_triggers_callback(self):
        """修改序列触发回调"""
        item = gui_launcher.ScriptItem(
            {'display_name': 'test', 'script_type': 'external'},
            dungeon_options=['未选择', '副本A'],
            sequence_options_map={'副本A': ['共鸣者经验', '武器经验', '贝币']},
            show_sequence=True,
        )
        called = []
        item.set_state_callback(lambda: called.append(True))
        item.dungeon_combo.setCurrentText('副本A')
        item.sequence_combo.setCurrentText('武器经验')
        # 切换副本触发 1 次，切换序列触发 1 次
        self.assertEqual(len(called), 2)


# ---- helpers ----

def mock_open_with_data(data):
    """返回一个 mock open，读取时返回 JSON 序列化的 data"""
    raw = json.dumps(data, ensure_ascii=False)
    return mock_open_with_data_raw(raw)


def mock_open_with_data_raw(raw_text):
    """返回一个 mock open，读取时返回 raw_text"""
    from io import StringIO

    def fake_open(file, mode='r', encoding=None):
        buf = StringIO(raw_text)
        m = MagicMock()
        m.__enter__ = MagicMock(return_value=buf)
        m.__exit__ = MagicMock(return_value=False)
        return m

    return fake_open


if __name__ == '__main__':
    unittest.main()
