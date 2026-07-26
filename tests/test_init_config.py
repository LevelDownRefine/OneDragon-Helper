import os
import tempfile
import unittest
from unittest.mock import patch

from config import init_config


class TestGenerateInitConfig(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

    @patch('config.init_config.shutil.copy')
    @patch('config.init_config.os.path.exists', return_value=False)
    @patch('config.init_config.copy_BGI_User')
    @patch('config.init_config.get_config_yml_path_under_root')
    def test_config_workflow(self, mock_config_path, mock_bgi, mock_exists, mock_shutil_copy):
        # 模拟首次运行：config.yml 不存在，触发从模板复制
        mock_config_path.return_value = os.path.join(self.temp_dir.name, "config.yml")
        init_config.config_workflow()

        # BetterGI 用户配置始终复制
        mock_bgi.assert_called_once()
        # config.yml 不存在时，应从模板复制
        mock_shutil_copy.assert_called_once()

    def test_need_config_workflow_true_when_missing(self):
        with patch('config.init_config.os.path.exists', return_value=False):
            self.assertTrue(init_config.need_config_workflow())

    def test_need_config_workflow_false_when_present(self):
        with patch('config.init_config.os.path.exists', return_value=True):
            self.assertFalse(init_config.need_config_workflow())


if __name__ == "__main__":
    unittest.main()
