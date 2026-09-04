"""测试 src/launcher.py：首次初始化流程"""

import os
import tempfile
import unittest
from unittest.mock import patch

# 在导入 PySide6 相关模块之前设置 offscreen 平台插件（CI 无显示器环境）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src import launcher


class TestInitConfig(unittest.TestCase):
    """测试首次初始化流程（config_workflow）"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

    @patch("src.launcher.generate_weekly_from_example")
    @patch("src.launcher.generate_schedule_from_example")
    @patch("src.launcher.generate_config_from_example")
    @patch("src.launcher.os.path.exists", return_value=False)
    @patch("src.launcher.get_config_yml_path_under_root")
    @patch("src.launcher.get_schedule_yml_path_under_root")
    @patch("src.launcher.get_weekly_yml_path_under_root")
    def test_config_workflow(
        self,
        mock_weekly_path,
        mock_schedule_path,
        mock_config_path,
        mock_exists,
        mock_generate_config,
        mock_generate_schedule,
        mock_generate_weekly,
    ):
        # 模拟首次运行：config.yml / schedule.yml / weekly.yml 均不存在，触发从模板生成
        mock_config_path.return_value = os.path.join(self.temp_dir.name, "config.yml")
        mock_schedule_path.return_value = os.path.join(
            self.temp_dir.name, "schedule.yml"
        )
        mock_weekly_path.return_value = os.path.join(self.temp_dir.name, "weekly.yml")
        launcher.config_workflow()

        # 首次运行时，config.yml / schedule.yml / weekly.yml 均应从模板生成
        mock_generate_config.assert_called_once()
        mock_generate_schedule.assert_called_once()
        mock_generate_weekly.assert_called_once()


if __name__ == "__main__":
    unittest.main()
