import os
import tempfile
import unittest
from unittest.mock import patch

from config import init_config
from src.config.subscript import _resolve_relative_script_paths


class TestGenerateInitConfig(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

    @patch('config.init_config.generate_config_from_example')
    @patch('config.init_config.os.path.exists', return_value=False)
    @patch('config.init_config.copy_BGI_User')
    @patch('config.init_config.get_config_yml_path_under_root')
    def test_config_workflow(self, mock_config_path, mock_bgi, mock_exists, mock_generate):
        # 模拟首次运行：config.yml 不存在，触发从模板生成
        mock_config_path.return_value = os.path.join(self.temp_dir.name, "config.yml")
        init_config.config_workflow()

        # BetterGI 用户配置始终复制
        mock_bgi.assert_called_once()
        # config.yml 不存在时，应从模板生成（相对路径解析为绝对）
        mock_generate.assert_called_once()

    def test_need_config_workflow_true_when_missing(self):
        with patch('config.init_config.os.path.exists', return_value=False):
            self.assertTrue(init_config.need_config_workflow())

    def test_need_config_workflow_false_when_present(self):
        with patch('config.init_config.os.path.exists', return_value=True):
            self.assertFalse(init_config.need_config_workflow())

    def test_resolve_relative_script_paths(self):
        from src.utils import get_root_dir
        data = {
            "script_list": [
                {"display_name": "静音", "script_path": "src/python_script/mute.py"},
                {"display_name": "原神", "script_path": "D:\\games\\BetterGI.exe"},
                {"display_name": "无路径", "script_path": ""},
            ]
        }
        _resolve_relative_script_paths(data)
        root = get_root_dir()
        # 相对路径解析为基于项目根目录的绝对路径（分隔符随系统归一）
        self.assertEqual(
            os.path.abspath(data["script_list"][0]["script_path"]),
            os.path.abspath(os.path.join(root, "src/python_script", "mute.py")),
        )
        # 绝对路径原样保留
        self.assertEqual(data["script_list"][1]["script_path"], "D:\\games\\BetterGI.exe")
        # 空路径原样保留
        self.assertEqual(data["script_list"][2]["script_path"], "")


if __name__ == "__main__":
    unittest.main()
