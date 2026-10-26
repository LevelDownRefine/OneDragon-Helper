"""冻结包缺少随包后端时，手动运行与窗口自动启动仅提示修复安装包。"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from gui.controllers.launch import LaunchController
from gui.main_window import QmlBridge
from tests.gui.helpers import get_app


class TestMissingCliLaunch(unittest.TestCase):
    def setUp(self):
        get_app()

    def _controller(self, enabled=True):
        service, toast = Mock(), Mock()
        games = SimpleNamespace(games=[{"script_name": "demo"}], enabled=[enabled])
        return LaunchController(games, service, toast), service, toast

    def test_manual_and_unattended_run_never_save_or_spawn_without_cli(self):
        for confirm in (False, True):
            for enabled in (False, True):
                with (
                    self.subTest(confirm=confirm, enabled=enabled),
                    patch("gui.controllers.launch.subprocess.Popen") as spawn,
                ):
                    controller, service, toast = self._controller(enabled)
                    controller.launchAll(confirm=confirm)
                    toast.assert_called_once_with(
                        "未找到独立 CLI，请重新解压完整安装包"
                    )
                    self.assertEqual(service.mock_calls, [])
                    spawn.assert_not_called()

    def test_window_startup_never_reads_options_or_confirms_without_cli(self):
        controller, service, toast = self._controller()
        bridge = SimpleNamespace(
            _cli_session=None, app_service=service, launch=controller
        )
        with (
            patch("gui.startup_dialog.confirm_startup") as confirm,
            patch("gui.controllers.launch.subprocess.Popen") as spawn,
        ):
            QmlBridge.maybe_auto_launch(bridge)
        toast.assert_called_once_with("未找到独立 CLI，请重新解压完整安装包")
        self.assertEqual(service.mock_calls, [])
        confirm.assert_not_called()
        spawn.assert_not_called()
