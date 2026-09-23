"""在新进程验证启动依赖，避免测试套件已导入的模块掩盖回归。"""

import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path


class TestStartupImports(unittest.TestCase):
    def test_cli_and_gui_defer_optional_dependencies(self):
        code = textwrap.dedent(
            """
            import sys
            from src import launcher

            launcher.build_parser().parse_args(["--version"])
            assert "PySide6" not in sys.modules, "CLI imported Qt"
            assert "requests" not in sys.modules, "CLI imported HTTP client"

            from src.gui.main_window import QmlBridge
            from src.service.app_service import AppService

            AppService()
            for module in (
                "requests",
                "src.gui.dialogs",
                "src.gui.config_dialog",
                "src.gui.daily_plan_dialog",
                "src.gui.run_confirm_dialog",
                "src.gui.update_dialog",
            ):
                assert module not in sys.modules, module
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=Path(__file__).resolve().parents[1],
            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
