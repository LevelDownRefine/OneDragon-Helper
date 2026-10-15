"""专用游戏启动：路径反读、只读命令解析及上游模块交接。"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import link, utils
from src.cli import build_parser, run_cli
from src.config import set_config
from src.service import app_service
from src.service.app_service import AppService


class TestEndfieldLaunch(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.module = (
            self.root / "data/apps/ok-ef/working/src/core/official_launcher.py"
        )
        self.module.parent.mkdir(parents=True)
        self.game = self.root / "中文 game" / "Endfield.exe"
        self.game.parent.mkdir()
        self.game.touch()
        self.result = self.root / "launched.json"
        self.module.write_text(
            "import json\nfrom pathlib import Path\n"
            "def launch_game(path, arguments, logger):\n"
            f"    Path({str(self.result)!r}).write_text(json.dumps([path, arguments]), encoding='utf-8')\n"
            "    return True\n",
            encoding="utf-8",
        )
        self.manual = self.enterContext(
            patch.object(set_config, "get_script_game_path", return_value="")
        )
        self.enterContext(
            patch.object(set_config, "get_script_root_dir", return_value=str(self.root))
        )
        self.enterContext(
            patch.object(
                set_config,
                "load_game_config",
                return_value={"pc_full_path": str(self.game)},
            )
        )
        self.script = {"script_path": "ok-ef.exe", "game_arguments": "-dx11"}
        self.enterContext(patch.object(link, "get_script", return_value=self.script))
        self.enterContext(
            patch.object(app_service, "get_script", return_value=self.script)
        )

        self.enterContext(patch.dict(sys.modules))
        self.service = AppService()
        self.addCleanup(self.service.close)

    def test_open_without_launcher_keeps_existing_system_association(self):
        with (
            patch.object(sys, "platform", "win32"),
            patch.object(os, "startfile", create=True) as start,
        ):
            utils.open_in_explorer(str(self.game), "-dx11")
        start.assert_called_once_with(
            str(self.game), arguments="-dx11", cwd=str(self.game.parent)
        )
        self.assertFalse(self.result.exists())

    def test_target_is_read_only_and_uses_existing_cli_in_source_and_frozen_layouts(
        self,
    ):
        for frozen in (False, True):
            with (
                self.subTest(frozen=frozen),
                patch.object(sys, "frozen", frozen, create=True),
                patch.object(link, "get_root_dir", return_value=str(self.root)),
            ):
                target = link.resolve_launch_target("ok-ef", "game")
                self.assertEqual(target["kind"], "command")
                self.assertEqual(target["program"], sys.executable)
                self.assertEqual(
                    target["args"],
                    ([] if frozen else ["-m", "src.headless"])
                    + ["--launch-game", "ok-ef"],
                )
                self.assertEqual(
                    target["cwd"],
                    str(self.root) if frozen else str(self.root / "python-backend"),
                )
                self.assertFalse(self.result.exists())

    def test_invalid_game_arguments_are_rejected_before_spawning(self):
        self.script["game_arguments"] = ["-dx11"]
        self.assertEqual(
            link.resolve_launch_target("ok-ef", "game"),
            {"kind": "unavailable", "reason": "游戏启动参数无效"},
        )
        self.assertFalse(self.result.exists())

    def test_missing_game_or_module_reports_actionable_unavailable_target(self):
        self.game.unlink()
        self.assertIn("游戏路径", link.resolve_launch_target("ok-ef", "game")["reason"])
        self.game.touch()
        self.module.unlink()
        self.assertIn("更新", link.resolve_launch_target("ok-ef", "game")["reason"])

    def test_manual_game_path_overrides_native_but_other_programs_stay_direct(self):
        for path in (str(self.game), r"D:\游戏\Endfield.exe"):
            with self.subTest(path=path):
                self.manual.return_value = path
                self.assertEqual(set_config.get_game_launch_info("ok-ef")[1], path)
        self.manual.return_value = str(self.root / "Launcher.exe")
        self.assertIsNone(set_config.get_game_launch_info("ok-ef"))
        self.assertIsNone(set_config.get_game_launch_info("ok-nte"))

    def test_upstream_module_receives_game_arguments_without_old_launcher_flags(self):
        for arguments, expected in (
            ('--profile "中文 空格" -dx11', '--profile "中文 空格" -dx11'),
            ("--game=Endfield --reason=4", ""),
        ):
            with (
                self.subTest(arguments=arguments),
                patch.object(sys, "platform", "win32"),
            ):
                self.script["game_arguments"] = arguments
                self.service.launch_game("ok-ef")
                self.assertEqual(
                    json.loads(self.result.read_text(encoding="utf-8")),
                    [os.path.abspath(self.game), expected],
                )

    def test_startup_failures_are_not_reported_as_success(self):
        for body, error in (
            ("raise RuntimeError('launcher timeout')", RuntimeError),
            ("return False", RuntimeError),
        ):
            with self.subTest(body=body), patch.object(sys, "platform", "win32"):
                self.module.write_text(
                    f"def launch_game(path, arguments, logger):\n    {body}\n",
                    encoding="utf-8",
                )
                with self.assertRaises(error):
                    self.service.launch_game("ok-ef")

    def test_module_import_registration_and_failure_cleanup(self):
        with patch.object(sys, "platform", "win32"):
            self.module.write_text(
                "import sys\nassert sys.modules[__name__] is not None\n"
                "raise ImportError('dependency missing')\n",
                encoding="utf-8",
            )
            with self.assertRaises(ImportError):
                self.service.launch_game("ok-ef")
            self.assertNotIn("_odh_game_launcher", sys.modules)
            self.module.write_text("# no launch function\n", encoding="utf-8")
            with self.assertRaises(ImportError):
                self.service.launch_game("ok-ef")

    def test_cli_failure_writes_result_and_returns_nonzero(self):
        with (
            patch("src.cli.AppService") as service,
            patch("src.cli._emit_cli") as emit,
            patch("src.cli.logger"),
        ):
            service.return_value.launch_game.side_effect = RuntimeError("timeout")
            self.assertEqual(
                run_cli(build_parser().parse_args(["--launch-game", "ok-ef"])), 1
            )
            emit.assert_called_once_with("launch_game", "启动游戏失败: timeout")

    def test_ordinary_game_queries_do_not_initialize_native_configuration(self):
        with (
            patch.dict(set_config._CONFIGS),
            patch.object(
                set_config.ArknightsConfig,
                "__init__",
                side_effect=AssertionError("no writes"),
            ),
        ):
            set_config.register(set_config.ArknightsConfig)
            self.assertIsNone(set_config.get_game_launch_info("MAA"))
            self.assertIsNone(set_config.get_game_launch_info("unknown"))

    def test_cli_uses_service_without_starting_script_chain(self):
        with patch("src.cli.AppService") as service:
            self.assertEqual(
                run_cli(build_parser().parse_args(["--launch-game", "ok-ef"])), 0
            )
            service.return_value.launch_game.assert_called_once_with("ok-ef")
            service.return_value.run_batch.assert_not_called()
