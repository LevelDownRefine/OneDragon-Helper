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

from PySide6.QtCore import QMimeData, QPoint, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
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

    def test_enabled_always_true_ignores_config(self):
        """enabled 为纯内存态、硬编码 True，不读 script_data 也不读 saved_state"""
        item = gui_launcher.ScriptItem(
            {'display_name': 'test', 'script_type': 'external', 'enabled': False},
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

    def test_runs_all_and_applies_timeout(self):
        """运行全部脚本，并为有 weekly_timeouts 的脚本写入当日超时（enabled 不过滤）"""
        config_text = (
            "script_list:\n"
            "  - display_name: 鸣潮\n"
            "  - display_name: 原神\n"
        )
        weekly_text = "鸣潮: [10, 20, 30, 40, 50, 60, 70]\n"
        rc, captured, fake_run = self._run_with(config_text, weekly_text)

        self.assertEqual(rc, 0)
        # 只调用一次 subprocess.run，且使用共享命令构造
        fake_run.assert_called_once_with(['echo', 'ok'], cwd='CWD')
        # 输出文件仅一次写入，且包含全部脚本
        self.assertEqual(len(captured), 1)
        written = yaml.safe_load(list(captured.values())[0].getvalue())
        names = [s['display_name'] for s in written['script_list']]
        self.assertEqual(names, ['鸣潮', '原神'])
        # 仅鸣潮有 weekly_timeouts，故只有它被写入 run_timeout_seconds
        self.assertIn('run_timeout_seconds', written['script_list'][0])

    def test_empty_script_list_exits_zero(self):
        """script_list 为空时直接退出且不调用 ScriptChainer"""
        config_text = "script_list: []\n"
        weekly_text = ""
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


class TestReorderScripts(unittest.TestCase):
    """测试 MainWindow._reorder_scripts 顺序同步与持久化"""

    def _make_window(self, disable_persist=False):
        # 跳过真实 _load_scripts（涉及文件 I/O），手动注入状态
        with patch.object(gui_launcher.MainWindow, '_load_scripts', lambda self: None):
            win = gui_launcher.MainWindow()
        win.script_items = [
            gui_launcher.ScriptItem({'display_name': f'脚本{i}', 'script_type': 'external'})
            for i in range(3)
        ]
        win.all_config_data = {
            'script_list': [
                {'display_name': f'脚本{i}', 'script_type': 'external'} for i in range(3)
            ]
        }
        # 默认禁止把测试桩数据写回真实 config.yml（持久化测试会单独 mock 路径与 open）
        if disable_persist:
            win._save_script_order = lambda: None
        return win

    def test_reorder_updates_script_items_order(self):
        """重排后 self.script_items 顺序改变（脚本0 移动到 脚本2 之后）"""
        win = self._make_window(disable_persist=True)
        win._reorder_scripts('脚本0', '脚本2')
        names = [it.display_name for it in win.script_items]
        self.assertEqual(names, ['脚本1', '脚本2', '脚本0'])

    def test_reorder_updates_config_data_order(self):
        """重排后 self.all_config_data['script_list'] 顺序同步改变"""
        win = self._make_window(disable_persist=True)
        win._reorder_scripts('脚本0', '脚本2')
        names = [s['display_name'] for s in win.all_config_data['script_list']]
        self.assertEqual(names, ['脚本1', '脚本2', '脚本0'])

    def test_reorder_persists_to_config_yml(self):
        """重排后写回 config.yml（script_list 顺序一致）"""
        win = self._make_window()
        captured = {}

        def fake_open(file, mode='w', encoding=None):
            m = MagicMock()
            buf = StringIO()
            captured['buf'] = buf
            m.__enter__ = MagicMock(return_value=buf)
            m.__exit__ = MagicMock(return_value=False)
            return m

        with patch('gui_launcher.get_config_yml_path_under_root', return_value='CONFIG.yml'), \
             patch('builtins.open', side_effect=fake_open):
            win._reorder_scripts('脚本0', '脚本2')
        written = yaml.safe_load(captured['buf'].getvalue())
        names = [s['display_name'] for s in written['script_list']]
        self.assertEqual(names, ['脚本1', '脚本2', '脚本0'])

    def test_reorder_noop_when_same_target(self):
        """源与目标相同（src==dst）时顺序不变"""
        win = self._make_window(disable_persist=True)
        win._reorder_scripts('脚本1', '脚本1')
        names = [it.display_name for it in win.script_items]
        self.assertEqual(names, ['脚本0', '脚本1', '脚本2'])


class TestScriptItemDragDrop(unittest.TestCase):
    """测试 ScriptItem 拖拽手柄与 drop 事件"""

    def test_handle_created_and_accepts_drops(self):
        """构造后存在拖拽手柄且接受 drop"""
        item = gui_launcher.ScriptItem({'display_name': 'A', 'script_type': 'external'})
        self.assertIsNotNone(item.handle)
        self.assertTrue(item.acceptDrops())

    def test_dragEnterEvent_accepts_our_mime(self):
        """dragEnterEvent 接受本应用的自定义 MIME"""
        item = gui_launcher.ScriptItem({'display_name': 'A', 'script_type': 'external'})
        item._reorder_callback = lambda src, dst: None
        mime = QMimeData()
        mime.setData(gui_launcher._DRAG_MIME, b'B')
        event = QDragEnterEvent(QPoint(0, 0), Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
        event.ignore()
        item.dragEnterEvent(event)
        self.assertTrue(event.isAccepted())

    def test_dragEnterEvent_ignores_unknown_mime(self):
        """dragEnterEvent 忽略未知 MIME"""
        item = gui_launcher.ScriptItem({'display_name': 'A', 'script_type': 'external'})
        mime = QMimeData()
        mime.setText('B')
        event = QDragEnterEvent(QPoint(0, 0), Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
        event.accept()
        item.dragEnterEvent(event)
        self.assertFalse(event.isAccepted())

    def test_dropEvent_calls_reorder_callback(self):
        """dropEvent 以 (src_name, dst_name) 调用重排回调"""
        item = gui_launcher.ScriptItem({'display_name': 'A', 'script_type': 'external'})
        called = []
        item._reorder_callback = lambda src, dst: called.append((src, dst))
        mime = QMimeData()
        mime.setData(gui_launcher._DRAG_MIME, b'B')
        event = QDropEvent(QPoint(0, 0), Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
        item.dropEvent(event)
        self.assertEqual(called, [('B', 'A')])
        self.assertTrue(event.isAccepted())

    def test_dropEvent_ignores_unknown_mime(self):
        """dropEvent 忽略未知 MIME 且不触发回调"""
        item = gui_launcher.ScriptItem({'display_name': 'A', 'script_type': 'external'})
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
        item = gui_launcher.ScriptItem({'display_name': 'A', 'script_type': 'external'})
        called = []
        item._reorder_callback = lambda src, dst: called.append((src, dst))
        mime = QMimeData()
        mime.setData(gui_launcher._DRAG_MIME, b'A')
        event = QDropEvent(QPoint(0, 0), Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
        item.dropEvent(event)
        self.assertEqual(called, [])
        self.assertTrue(event.isAccepted())


class TestDeleteScript(unittest.TestCase):
    """测试 MainWindow 删除脚本：UI 与 config.yml 同步移除并持久化"""

    def _make_window(self, disable_persist=False):
        with patch.object(gui_launcher.MainWindow, '_load_scripts', lambda self: None):
            win = gui_launcher.MainWindow()
        win.script_items = [
            gui_launcher.ScriptItem({'display_name': f'脚本{i}', 'script_type': 'external'})
            for i in range(3)
        ]
        win.all_config_data = {
            'script_list': [
                {'display_name': f'脚本{i}', 'script_type': 'external'} for i in range(3)
            ]
        }
        if disable_persist:
            win._save_script_order = lambda: None
            win._persist_ui_state = lambda: None
        return win

    def test_delete_removes_from_script_items(self):
        """确认删除后 self.script_items 不再包含该脚本"""
        win = self._make_window(disable_persist=True)
        with patch('gui_launcher.QMessageBox.question',
                   return_value=gui_launcher.QMessageBox.Yes):
            win._delete_script('脚本1')
        names = [it.display_name for it in win.script_items]
        self.assertEqual(names, ['脚本0', '脚本2'])

    def test_delete_removes_from_config_data(self):
        """确认删除后 self.all_config_data['script_list'] 不再包含该脚本"""
        win = self._make_window(disable_persist=True)
        with patch('gui_launcher.QMessageBox.question',
                   return_value=gui_launcher.QMessageBox.Yes):
            win._delete_script('脚本1')
        names = [s['display_name'] for s in win.all_config_data['script_list']]
        self.assertEqual(names, ['脚本0', '脚本2'])

    def test_delete_removes_widget_from_layout(self):
        """确认删除后 widget 从滚动区布局移除"""
        win = self._make_window(disable_persist=True)
        item = win.script_items[1]
        win.scroll_layout.addWidget(item)
        with patch('gui_launcher.QMessageBox.question',
                   return_value=gui_launcher.QMessageBox.Yes):
            win._delete_script('脚本1')
        self.assertEqual(win.scroll_layout.indexOf(item), -1)

    def test_delete_persists_to_config_yml(self):
        """确认删除后写回 config.yml（script_list 不含被删脚本）"""
        win = self._make_window()  # 保留真实 _save_script_order，验证写回
        win._persist_ui_state = lambda: None  # 仅验证 config.yml 写回，隔离 gui_state.json
        captured = {}

        def fake_open(file, mode='w', encoding=None):
            m = MagicMock()
            buf = StringIO()
            captured['buf'] = buf
            m.__enter__ = MagicMock(return_value=buf)
            m.__exit__ = MagicMock(return_value=False)
            return m

        with patch('gui_launcher.QMessageBox.question',
                   return_value=gui_launcher.QMessageBox.Yes), \
             patch('gui_launcher.get_config_yml_path_under_root', return_value='CONFIG.yml'), \
             patch('builtins.open', side_effect=fake_open):
            win._delete_script('脚本1')
        written = yaml.safe_load(captured['buf'].getvalue())
        names = [s['display_name'] for s in written['script_list']]
        self.assertEqual(names, ['脚本0', '脚本2'])

    def test_delete_noop_when_confirm_no(self):
        """确认弹窗选「否」时不删除、不改变任何状态"""
        win = self._make_window(disable_persist=True)
        with patch('gui_launcher.QMessageBox.question',
                   return_value=gui_launcher.QMessageBox.No):
            win._delete_script('脚本1')
        names = [it.display_name for it in win.script_items]
        self.assertEqual(names, ['脚本0', '脚本1', '脚本2'])
        cfg_names = [s['display_name'] for s in win.all_config_data['script_list']]
        self.assertEqual(cfg_names, ['脚本0', '脚本1', '脚本2'])

    def test_script_item_delete_button_wired(self):
        """脚本项的删除按钮点击应触发注入的回调，并传入 display_name"""
        called = []
        item = gui_launcher.ScriptItem(
            {'display_name': 'X', 'script_type': 'external'},
            delete_callback=lambda name: called.append(name),
        )
        self.assertTrue(hasattr(item, 'delete_btn'))
        item._on_delete_clicked()
        self.assertEqual(called, ['X'])


class TestAddScript(unittest.TestCase):
    """测试 MainWindow 添加脚本：UI 与 config.yml 同步追加并持久化"""

    def _make_window(self, disable_persist=False):
        with patch.object(gui_launcher.MainWindow, '_load_scripts', lambda self: None):
            win = gui_launcher.MainWindow()
        win.dungeon_map = {}  # 自定义脚本无副本配置
        win.script_items = [
            gui_launcher.ScriptItem({'display_name': f'脚本{i}', 'script_type': 'external'})
            for i in range(2)
        ]
        win.all_config_data = {
            'script_list': [
                {'display_name': f'脚本{i}', 'script_type': 'external'} for i in range(2)
            ]
        }
        if disable_persist:
            win._save_script_order = lambda: None
            win._persist_ui_state = lambda: None
        return win

    def test_default_script_entry_has_all_fields(self):
        """_default_script_entry 覆盖 config.yml 全部字段，核心字段用参数值"""
        entry = gui_launcher._default_script_entry('崩坏3', 'python', 'C:/a/b.py', 300)
        self.assertEqual(entry['display_name'], '崩坏3')
        self.assertEqual(entry['script_type'], 'python')
        self.assertEqual(entry['script_path'], 'C:/a/b.py')
        self.assertEqual(entry['run_timeout_seconds'], 300)
        # 关键默认字段
        self.assertEqual(entry['script_process_name'], [])
        self.assertEqual(entry['kill_script_after_done'], True)
        self.assertEqual(entry['no_log_max_retries'], 3)
        # 与真实条目字段集合一致
        expected_keys = {
            'display_name', 'game_label', 'script_type', 'script_path',
            'script_process_name', 'game_process_name', 'launcher_mode',
            'run_timeout_seconds', 'check_done', 'kill_script_after_done',
            'kill_game_after_done', 'script_arguments', 'notify_start',
            'notify_done', 'notify_log_interval', 'attach_direction',
            'no_log_timeout_seconds', 'no_log_max_retries',
        }
        self.assertEqual(set(entry.keys()), expected_keys)

    def test_append_adds_to_script_items(self):
        """追加后 self.script_items 末尾出现新脚本"""
        win = self._make_window(disable_persist=True)
        entry = gui_launcher._default_script_entry('新脚本', 'external', 'C:/x.exe', 100)
        win._append_script(entry)
        names = [it.display_name for it in win.script_items]
        self.assertEqual(names, ['脚本0', '脚本1', '新脚本'])

    def test_append_adds_to_config_data(self):
        """追加后 self.all_config_data['script_list'] 末尾出现新脚本条目"""
        win = self._make_window(disable_persist=True)
        entry = gui_launcher._default_script_entry('新脚本', 'external', 'C:/x.exe', 100)
        win._append_script(entry)
        names = [s['display_name'] for s in win.all_config_data['script_list']]
        self.assertEqual(names, ['脚本0', '脚本1', '新脚本'])
        self.assertIs(win.all_config_data['script_list'][-1], entry)

    def test_append_persists_to_config_yml(self):
        """追加后写回 config.yml（末尾含新脚本，字段完整）"""
        win = self._make_window()  # 保留真实 _save_script_order
        win._persist_ui_state = lambda: None  # 隔离 gui_state.json
        captured = {}

        def fake_open(file, mode='w', encoding=None):
            m = MagicMock()
            buf = StringIO()
            captured['buf'] = buf
            m.__enter__ = MagicMock(return_value=buf)
            m.__exit__ = MagicMock(return_value=False)
            return m

        entry = gui_launcher._default_script_entry('新脚本', 'python', 'C:/x.py', 100)
        with patch('gui_launcher.get_config_yml_path_under_root', return_value='CONFIG.yml'), \
             patch('builtins.open', side_effect=fake_open):
            win._append_script(entry)
        written = yaml.safe_load(captured['buf'].getvalue())
        names = [s['display_name'] for s in written['script_list']]
        self.assertEqual(names, ['脚本0', '脚本1', '新脚本'])
        self.assertEqual(written['script_list'][-1]['script_type'], 'python')
        self.assertEqual(written['script_list'][-1]['run_timeout_seconds'], 100)

    def test_append_widget_added_to_layout(self):
        """追加后新脚本 widget 出现在滚动区布局中"""
        win = self._make_window(disable_persist=True)
        entry = gui_launcher._default_script_entry('新脚本', 'external', 'C:/x.exe', 100)
        win._append_script(entry)
        new_item = win.script_items[-1]
        self.assertGreaterEqual(win.scroll_layout.indexOf(new_item), 0)

    def test_add_script_cancel_does_nothing(self):
        """对话框取消（非 Accepted）时不追加任何脚本"""
        win = self._make_window(disable_persist=True)
        fake_dialog = MagicMock()
        fake_dialog.exec.return_value = gui_launcher.QDialog.Rejected
        with patch('gui_launcher.AddScriptDialog', return_value=fake_dialog):
            win._add_script()
        names = [it.display_name for it in win.script_items]
        self.assertEqual(names, ['脚本0', '脚本1'])

    def test_add_script_confirm_appends(self):
        """对话框确认时用 result_data 追加脚本"""
        win = self._make_window(disable_persist=True)
        entry = gui_launcher._default_script_entry('确认脚本', 'external', 'C:/y.exe', 50)
        fake_dialog = MagicMock()
        fake_dialog.exec.return_value = gui_launcher.QDialog.Accepted
        fake_dialog.result_data = entry
        with patch('gui_launcher.AddScriptDialog', return_value=fake_dialog):
            win._add_script()
        names = [it.display_name for it in win.script_items]
        self.assertEqual(names, ['脚本0', '脚本1', '确认脚本'])


class TestAddScriptDialog(unittest.TestCase):
    """测试 AddScriptDialog 表单校验与结果构造"""

    def test_save_builds_result_data(self):
        """填入合法字段后 save_data 构造完整 result_data 并 accept"""
        dlg = gui_launcher.AddScriptDialog(existing_names=['已存在'])
        dlg.name_input.setText('新脚本')
        dlg.type_combo.setCurrentText('python')
        dlg.path_input.setText('C:/foo/bar.py')
        dlg.timeout_input.setText('600')
        with patch.object(dlg, 'accept') as acc:
            dlg.save_data()
        self.assertIsNotNone(dlg.result_data)
        self.assertEqual(dlg.result_data['display_name'], '新脚本')
        self.assertEqual(dlg.result_data['script_type'], 'python')
        self.assertEqual(dlg.result_data['script_path'], 'C:/foo/bar.py')
        self.assertEqual(dlg.result_data['run_timeout_seconds'], 600)
        self.assertEqual(dlg.result_data['script_arguments'], '')
        acc.assert_called_once()

    def test_save_captures_script_arguments(self):
        """填入启动参数后写入 result_data['script_arguments']"""
        dlg = gui_launcher.AddScriptDialog()
        dlg.name_input.setText('带参脚本')
        dlg.path_input.setText('C:/foo/bar.exe')
        dlg.args_input.setText('--task daily --fast')
        with patch.object(dlg, 'accept'):
            dlg.save_data()
        self.assertIsNotNone(dlg.result_data)
        self.assertEqual(dlg.result_data['script_arguments'], '--task daily --fast')

    def test_save_rejects_empty_name(self):
        """名称为空时不构造 result_data"""
        dlg = gui_launcher.AddScriptDialog()
        dlg.name_input.setText('')
        dlg.path_input.setText('C:/x.exe')
        with patch('gui_launcher.QMessageBox.warning'):
            dlg.save_data()
        self.assertIsNone(dlg.result_data)

    def test_save_rejects_duplicate_name(self):
        """名称重复时不构造 result_data"""
        dlg = gui_launcher.AddScriptDialog(existing_names=['原神'])
        dlg.name_input.setText('原神')
        dlg.path_input.setText('C:/x.exe')
        with patch('gui_launcher.QMessageBox.warning'):
            dlg.save_data()
        self.assertIsNone(dlg.result_data)

    def test_save_rejects_empty_path(self):
        """路径为空时不构造 result_data"""
        dlg = gui_launcher.AddScriptDialog()
        dlg.name_input.setText('新脚本')
        dlg.path_input.setText('')
        with patch('gui_launcher.QMessageBox.warning'):
            dlg.save_data()
        self.assertIsNone(dlg.result_data)


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
