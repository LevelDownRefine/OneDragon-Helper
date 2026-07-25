"""测试 GUI 状态持久化功能"""
import json
import os
import sys
import unittest
from io import StringIO
from unittest.mock import MagicMock, patch

import yaml

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


class TestScriptItemGetState(unittest.TestCase):
    """测试 ScriptItem.get_state — 不含 enabled"""

    def test_get_state_no_dungeon_no_sequence(self):
        """无副本无序列时返回空 dict"""
        item = gui_launcher.ScriptItem({'display_name': 'test', 'script_type': 'external', 'enabled': True})
        state = item.get_state()
        self.assertEqual(state, {})

    def test_get_state_with_dungeon(self):
        """有副本选择时返回 dungeon"""
        item = gui_launcher.ScriptItem(
            {'display_name': 'test', 'script_type': 'external'},
            dungeon_options=["副本A", "副本B"],
        )
        item._on_dungeon_selected("副本B")
        state = item.get_state()
        self.assertEqual(state, {'dungeon': '副本B'})

    def test_get_state_with_sequence(self):
        """有序列时返回 sequence"""
        item = gui_launcher.ScriptItem(
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
        item = gui_launcher.ScriptItem({'display_name': 'test', 'script_type': 'external', 'enabled': True})
        state = item.get_state()
        self.assertNotIn('enabled', state)


class TestScriptItemEnabledNotPersisted(unittest.TestCase):
    """测试 enabled 不被持久化"""

    def test_toggle_does_not_trigger_callback(self):
        """toggle 不触发 _on_state_changed"""
        item = gui_launcher.ScriptItem({'display_name': 'test', 'script_type': 'external', 'enabled': True})
        callback_called = []
        item.set_state_callback(lambda: callback_called.append(True))
        item._toggle()
        self.assertEqual(len(callback_called), 0)

    def test_enabled_from_script_data_not_saved_state(self):
        """enabled 从 script_data 取，不从 saved_state 恢复"""
        item = gui_launcher.ScriptItem(
            {'display_name': 'test', 'script_type': 'external', 'enabled': True},
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
        self.assertEqual(item._selected_dungeon, '副本B')

    def test_sequence_restored_from_saved_state(self):
        """序列从 saved_state 恢复"""
        item = gui_launcher.ScriptItem(
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
        item = gui_launcher.ScriptItem(
            {'display_name': 'test', 'script_type': 'external'},
            dungeon_options=["副本A", "副本B"],
            saved_state={'dungeon': '不存在'},
        )
        # 不在选项中，不恢复
        self.assertIsNone(item._selected_dungeon)


class TestParseArgs(unittest.TestCase):
    """测试 parse_args"""

    def test_no_set_config_flag_parsed(self):
        """--no-set-config 被解析为 True"""
        with patch.object(sys, 'argv', ['gui_launcher', '--no-set-config']):
            args = gui_launcher.parse_args()
        self.assertTrue(args.no_set_config)

    def test_no_flag_defaults_false(self):
        """无参数时 no_set_config 为 False"""
        with patch.object(sys, 'argv', ['gui_launcher']):
            args = gui_launcher.parse_args()
        self.assertFalse(args.no_set_config)


class TestRunDirect(unittest.TestCase):
    """测试 run_direct（计划任务无界面模式）"""

    CONFIG_YML = "CONFIG_YML"
    WEEKLY_YML = "WEEKLY_YML"
    OUT_DIR = "OUT_DIR"

    def _fake_open(self, read_data, captured):
        def fake_open(file, mode='r', encoding=None):
            m = MagicMock()
            if mode == 'w':
                buf = StringIO()
                captured[file] = buf
                m.__enter__ = MagicMock(return_value=buf)
                m.__exit__ = MagicMock(return_value=False)
                return m
            buf = StringIO(read_data[file])
            m.__enter__ = MagicMock(return_value=buf)
            m.__exit__ = MagicMock(return_value=False)
            return m
        return fake_open

    def _run_with(self, config_text, weekly_text):
        captured = {}
        read_data = {
            self.CONFIG_YML: config_text,
            self.WEEKLY_YML: weekly_text,
        }
        fake_run = MagicMock()
        fake_run.return_value.returncode = 0
        with patch('gui_launcher.get_config_yml_path_under_root', return_value=self.CONFIG_YML), \
             patch('gui_launcher.get_weekly_timeouts_yml_path_under_root', return_value=self.WEEKLY_YML), \
             patch('gui_launcher.get_path_under_onedragon', return_value=self.OUT_DIR), \
             patch('gui_launcher.os.path.exists', side_effect=lambda p: p == self.WEEKLY_YML), \
             patch('gui_launcher._build_chain_command', return_value=(['echo', 'ok'], 'CWD')), \
             patch('gui_launcher.subprocess.run', fake_run), \
             patch('builtins.open', self._fake_open(read_data, captured)):
            rc = gui_launcher.run_direct("88")
        return rc, captured, fake_run

    def test_filters_enabled_and_applies_timeout(self):
        """只保留 enabled 脚本，并写入当日超时"""
        config_text = (
            "script_list:\n"
            "  - display_name: 鸣潮\n"
            "    enabled: true\n"
            "  - display_name: 原神\n"
            "    enabled: false\n"
        )
        weekly_text = "鸣潮: [10, 20, 30, 40, 50, 60, 70]\n"
        rc, captured, fake_run = self._run_with(config_text, weekly_text)

        self.assertEqual(rc, 0)
        # 只调用一次 subprocess.run，且使用共享命令构造
        fake_run.assert_called_once_with(['echo', 'ok'], cwd='CWD')
        # 输出文件仅一次写入，且只含启用的脚本
        self.assertEqual(len(captured), 1)
        written = yaml.safe_load(list(captured.values())[0].getvalue())
        names = [s['display_name'] for s in written['script_list']]
        self.assertEqual(names, ['鸣潮'])
        self.assertIn('run_timeout_seconds', written['script_list'][0])

    def test_empty_enabled_exits_zero(self):
        """无启用脚本时直接退出且不调用 ScriptChainer"""
        config_text = (
            "script_list:\n"
            "  - display_name: 鸣潮\n"
            "    enabled: false\n"
        )
        weekly_text = "鸣潮: [10, 20, 30, 40, 50, 60, 70]\n"
        rc, captured, fake_run = self._run_with(config_text, weekly_text)

        self.assertEqual(rc, 0)
        fake_run.assert_not_called()
        self.assertEqual(len(captured), 0)

    def test_propagates_return_code(self):
        """透传 ScriptChainer 退出码"""
        config_text = (
            "script_list:\n"
            "  - display_name: 鸣潮\n"
            "    enabled: true\n"
        )
        weekly_text = "鸣潮: [10, 20, 30, 40, 50, 60, 70]\n"
        captured = {}
        read_data = {self.CONFIG_YML: config_text, self.WEEKLY_YML: weekly_text}
        fake_run = MagicMock()
        fake_run.return_value.returncode = 3
        with patch('gui_launcher.get_config_yml_path_under_root', return_value=self.CONFIG_YML), \
             patch('gui_launcher.get_weekly_timeouts_yml_path_under_root', return_value=self.WEEKLY_YML), \
             patch('gui_launcher.get_path_under_onedragon', return_value=self.OUT_DIR), \
             patch('gui_launcher.os.path.exists', side_effect=lambda p: p == self.WEEKLY_YML), \
             patch('gui_launcher._build_chain_command', return_value=(['echo', 'ok'], 'CWD')), \
             patch('gui_launcher.subprocess.run', fake_run), \
             patch('builtins.open', self._fake_open(read_data, captured)):
            rc = gui_launcher.run_direct("88")
        self.assertEqual(rc, 3)


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
        item._on_dungeon_selected("副本B")
        self.assertEqual(len(called), 1)

    def test_sequence_change_triggers_callback(self):
        """修改序列触发回调"""
        item = gui_launcher.ScriptItem(
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
