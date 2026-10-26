"""新进程验证正常窗口启动不导入业务服务或网络客户端。"""

import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path


class TestStartupImports(unittest.TestCase):
    def test_launcher_and_cli_bridge_never_import_business_service_or_network(self):
        code = textwrap.dedent(
            """
            import importlib.abc
            import sys

            class RejectBusinessService(importlib.abc.MetaPathFinder):
                def find_spec(self, fullname, path=None, target=None):
                    if fullname == "src.service.app_service":
                        raise AssertionError("GUI imported AppService")
                    return None

            assert "src.service.app_service" not in sys.modules
            sys.meta_path.insert(0, RejectBusinessService())

            from unittest.mock import patch
            import gui.launcher
            from tests.gui.helpers import make_bridge

            bridges = []
            def open_window(**kwargs):
                bridges.append(make_bridge())

            with (
                patch.object(sys, "argv", ["gui"]),
                patch.object(gui.launcher, "setup_logging"),
                patch.object(gui.launcher, "install_crash_hooks"),
                patch.object(gui.launcher, "_launch_qml", side_effect=open_window),
            ):
                gui.launcher.main()
            assert len(bridges) == 1
            bridge = bridges[0]
            assert not hasattr(bridge, "app_service")
            for controller in (
                bridge.game_list, bridge.task_card, bridge.background,
                bridge.links, bridge.backup, bridge.launch,
            ):
                assert not hasattr(controller, "_app_service")
            assert "src.service.app_service" not in sys.modules
            assert "requests" not in sys.modules, "GUI imported HTTP client"
            bridge.test_client.close()
            """
        )
        gui_root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=gui_root.parent,
            env={
                **os.environ,
                "PYTHONPATH": str(gui_root),
                "PYTHONUTF8": "1",
                "PYTHONFAULTHANDLER": "1",
                "QT_QPA_PLATFORM": "offscreen",
            },
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
