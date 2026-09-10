"""持久化脚本勾选：重启/重排按脚本身份回显，保存失败不更改界面。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.gui.controllers.game_list import GameListController
from src.service.app_service import AppService
from src.utils.utils_config import load_config, script_enabled, set_script_enabled
from src.utils.utils_yaml import dump_yaml


class TestScriptEnabled(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = str(Path(directory.name, "config.yml"))
        self.scripts = [
            {"display_name": "A", "script_path": "a.py", "block": True},
            {"display_name": "B", "script_path": "b.py", "enabled": False},
        ]
        dump_yaml(self.path, {"script_list": self.scripts})
        for name in ("require_config_yml_path", "get_config_yml_path_under_root"):
            patcher = patch(f"src.utils.utils_config.{name}", return_value=self.path)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_default_enabled_and_invalid_value_disabled(self):
        self.assertTrue(script_enabled(self.scripts[0]))
        with self.assertLogs("src.utils.utils_config", level="WARNING"):
            self.assertFalse(script_enabled({"display_name": "A", "enabled": "false"}))

    def test_selection_persists_and_preserves_other_fields(self):
        AppService().set_script_enabled({"A": False, "B": True})
        expected = [
            dict(self.scripts[0], enabled=False),
            dict(self.scripts[1], enabled=True),
        ]
        self.assertEqual(AppService().load_config()["script_list"], expected)

    def test_unknown_script_never_partially_saves(self):
        with self.assertRaises(ValueError):
            set_script_enabled({"A": False, "missing": True})
        self.assertEqual(load_config()["script_list"], self.scripts)

    def _controller(self):
        controller = GameListController(AppService(), Mock(), Mock())
        with patch.object(controller.icon_provider, "refresh"):
            controller.reload_games()
        return controller

    def test_reopen_and_reorder_restore_by_script_identity(self):
        controller = self._controller()
        controller.toggleMode()
        controller.selectGame(0)
        self.assertEqual(controller.enabled, [False, False])
        self.assertEqual(self._controller().enabled, [False, False])
        controller.selectAll()
        controller.selectGame(0)
        controller.reorderGames(0, 1)
        reopened = self._controller()
        self.assertEqual([g["script_name"] for g in reopened.games], ["B", "A"])
        self.assertEqual(reopened.enabled, [True, False])
        reopened.deselectAll()
        self.assertEqual(self._controller().enabled, [False, False])

    def test_failed_save_keeps_previous_ui_selection(self):
        controller = self._controller()
        controller.toggleMode()
        with (
            patch.object(
                controller._app_service,
                "set_script_enabled",
                side_effect=OSError("locked"),
            ),
            self.assertLogs("src.gui.controllers.game_list", level="ERROR"),
        ):
            controller.selectGame(0)
        self.assertEqual(controller.enabled, [True, False])
        self.assertIn("保存脚本勾选失败", controller._toast.call_args.args[0])
