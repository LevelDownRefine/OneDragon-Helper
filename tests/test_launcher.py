"""测试 src/launcher.py：首次初始化流程"""

import os
import sys
import tempfile
import time
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

    @patch("src.config.generate_config.generate_weekly_from_example")
    @patch("src.config.generate_config.generate_schedule_from_example")
    @patch("src.config.generate_config.generate_config_from_example")
    @patch("src.config.generate_config.os.path.exists", return_value=False)
    @patch("src.config.generate_config.get_config_yml_path_under_root")
    @patch("src.config.generate_config.get_schedule_yml_path_under_root")
    @patch("src.config.generate_config.get_weekly_yml_path_under_root")
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
        with patch("src.config.set_config.init_config_all") as init:
            launcher.config_workflow()

        # 首次运行时，config.yml / schedule.yml / weekly.yml 均应从模板生成
        mock_generate_config.assert_called_once()
        mock_generate_schedule.assert_called_once()
        mock_generate_weekly.assert_called_once()
        # 启动不再急切对齐各脚本 config；对齐收口到 ScriptConfig 构造时（懒加载）
        init.assert_not_called()


class TestMainStartupOrder(unittest.TestCase):
    """main() 初始化顺序：日志必须先于 config_workflow。"""

    def test_setup_logging_precedes_config_workflow(self):
        """config_workflow 的 init 对齐会产生 WARNING（如补缺失字段），
        若晚于 setup_logging 则进日志文件可追溯；顺序回归即本测试红。"""
        order = []
        with (
            patch.object(
                launcher,
                "setup_logging",
                side_effect=lambda: order.append("setup_logging"),
            ),
            patch.object(
                launcher,
                "install_crash_hooks",
                side_effect=lambda: order.append("install_crash_hooks"),
            ),
            patch.object(
                launcher,
                "config_workflow",
                side_effect=lambda: order.append("config_workflow"),
            ),
            patch.object(launcher, "run_cli", return_value=0),
            patch.object(sys, "argv", ["OneDragon-Helper"]),
            self.assertRaises(SystemExit),
        ):
            launcher.main()
        self.assertEqual(
            order, ["setup_logging", "install_crash_hooks", "config_workflow"]
        )


class TestStartupTimer(unittest.TestCase):
    """启动打点基准按调用复位。

    基准若停在模块导入时刻，同一进程内多次调用 main()（如 tests/test_cli.py 逐个 CLI
    出口）会把上一次的耗时累加进来，日志里打出十几万毫秒的假数字。
    """

    def test_main_resets_baseline(self):
        launcher._STARTUP_T0 -= 3600.0  # 模拟上一次调用已过去一小时
        with (
            patch.object(launcher, "setup_logging"),
            patch.object(launcher, "install_crash_hooks"),
            patch.object(launcher, "config_workflow"),
            patch.object(launcher, "run_cli", return_value=0),
            patch.object(sys, "argv", ["OneDragon-Helper"]),
            self.assertRaises(SystemExit),
        ):
            launcher.main()
        self.assertLess(time.perf_counter() - launcher._STARTUP_T0, 1.0)


class TestQtMessageLogger(unittest.TestCase):
    """_install_qt_message_logger：Qt/QML 告警路由到 logging（windowed exe 无 stderr）。"""

    def test_qt_warning_routed_to_logger(self):
        from PySide6.QtCore import qInstallMessageHandler, qWarning

        previous = qInstallMessageHandler(None)
        self.addCleanup(qInstallMessageHandler, previous)
        launcher._install_qt_message_logger()
        with self.assertLogs("src.launcher", level="WARNING") as captured:
            qWarning("test-qml-warning")
        self.assertTrue(
            any("[qt] test-qml-warning" in line for line in captured.output)
        )


if __name__ == "__main__":
    unittest.main()
