"""测试 src/launcher.py：命令行解析与无界面直跑（计划任务模式）"""
import os
import sys
import tempfile
import unittest
from io import StringIO
from unittest.mock import MagicMock, patch

import yaml

# 在导入 PySide6 相关模块之前设置 offscreen 平台插件（CI 无显示器环境）
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from src import launcher


class TestParseArgs(unittest.TestCase):
    """测试 parse_args"""

    def test_no_set_config_flag_parsed(self):
        """--no-set-config 被解析为 True"""
        with patch.object(sys, 'argv', ['launcher', '--no-set-config']):
            args = launcher.parse_args()
        self.assertTrue(args.no_set_config)

    def test_no_flag_defaults_false(self):
        """无参数时 no_set_config 为 False"""
        with patch.object(sys, 'argv', ['launcher']):
            args = launcher.parse_args()
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
        fake_run = MagicMock(return_value=0)
        with patch('src.launcher.get_config_yml_path_under_root', return_value=self.CONFIG_YML), \
             patch('src.launcher.get_weekly_timeouts_yml_path_under_root', return_value=self.WEEKLY_YML), \
             patch('src.launcher.get_path_under_onedragon', return_value=self.OUT_DIR), \
             patch('src.launcher.os.path.exists', side_effect=lambda p: p == self.WEEKLY_YML), \
             patch('src.launcher.run_chain_command', fake_run), \
             patch('builtins.open', self._fake_open(read_data, captured)):
            rc = launcher.run_direct("88")
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
        # 只调用一次 run_chain_command，且透传 chain_name
        fake_run.assert_called_once_with("88")
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
        fake_run = MagicMock(return_value=3)
        with patch('src.launcher.get_config_yml_path_under_root', return_value=self.CONFIG_YML), \
             patch('src.launcher.get_weekly_timeouts_yml_path_under_root', return_value=self.WEEKLY_YML), \
             patch('src.launcher.get_path_under_onedragon', return_value=self.OUT_DIR), \
             patch('src.launcher.os.path.exists', side_effect=lambda p: p == self.WEEKLY_YML), \
             patch('src.launcher.run_chain_command', fake_run), \
             patch('builtins.open', self._fake_open(read_data, captured)):
            rc = launcher.run_direct("88")
        self.assertEqual(rc, 3)


class TestInitConfig(unittest.TestCase):
    """测试首次初始化流程（config_workflow / need_config_workflow）"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

    @patch('src.launcher.generate_config_from_example')
    @patch('src.launcher.os.path.exists', return_value=False)
    @patch('src.launcher.copy_BGI_User')
    @patch('src.launcher.get_config_yml_path_under_root')
    def test_config_workflow(self, mock_config_path, mock_bgi, mock_exists, mock_generate):
        # 模拟首次运行：config.yml 不存在，触发从模板生成
        mock_config_path.return_value = os.path.join(self.temp_dir.name, "config.yml")
        launcher.config_workflow()

        # BetterGI 用户配置始终复制
        mock_bgi.assert_called_once()
        # config.yml 不存在时，应从模板生成（相对路径解析为绝对）
        mock_generate.assert_called_once()

    def test_need_config_workflow_true_when_missing(self):
        with patch('src.launcher.os.path.exists', return_value=False):
            self.assertTrue(launcher.need_config_workflow())

    def test_need_config_workflow_false_when_present(self):
        with patch('src.launcher.os.path.exists', return_value=True):
            self.assertFalse(launcher.need_config_workflow())


if __name__ == '__main__':
    unittest.main()
