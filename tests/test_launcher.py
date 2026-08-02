"""测试 src/launcher.py：首次初始化流程"""

import os
import tempfile
import unittest
from unittest.mock import patch

# 在导入 PySide6 相关模块之前设置 offscreen 平台插件（CI 无显示器环境）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src import launcher


class TestInitConfig(unittest.TestCase):
    """测试首次初始化流程（config_workflow / need_config_workflow）"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

    @patch("src.launcher.generate_config_from_example")
    @patch("src.launcher.os.path.exists", return_value=False)
    @patch("src.launcher.copy_BGI_User")
    @patch("src.launcher.get_config_yml_path_under_root")
    def test_config_workflow(
        self, mock_config_path, mock_bgi, mock_exists, mock_generate
    ):
        # 模拟首次运行：config.yml 不存在，触发从模板生成
        mock_config_path.return_value = os.path.join(self.temp_dir.name, "config.yml")
        launcher.config_workflow()

        # BetterGI 用户配置始终复制
        mock_bgi.assert_called_once()
        # config.yml 不存在时，应从模板生成（相对路径解析为绝对）
        mock_generate.assert_called_once()

    def test_need_config_workflow_true_when_missing(self):
        with patch("src.launcher.os.path.exists", return_value=False):
            self.assertTrue(launcher.need_config_workflow())

    def test_need_config_workflow_false_when_present(self):
        with patch("src.launcher.os.path.exists", return_value=True):
            self.assertFalse(launcher.need_config_workflow())


if __name__ == "__main__":
    unittest.main()
