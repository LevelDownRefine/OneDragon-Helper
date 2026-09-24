"""在新进程验证启动依赖，避免测试套件已导入的模块掩盖回归。"""

import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path


class TestStartupImports(unittest.TestCase):
    def test_gui_startup_defers_network(self):
        code = textwrap.dedent(
            """
            import sys
            import src.launcher
            from src.service.app_service import AppService

            AppService()
            assert "requests" not in sys.modules, "GUI imported HTTP client"
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
