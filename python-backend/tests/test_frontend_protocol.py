"""前端无关的关机命令、每日计划和更新发行版选择。"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.headless import _daily_task, _installed_frontend, _run_target
from src.service.schedule import RunOptions
from src.utils import utils_shutdown


class FrontendProtocolTests(unittest.TestCase):
    def test_confirmation_accepts_python_arguments_and_preserves_run_and_plan(self):
        with tempfile.TemporaryDirectory() as temporary:
            program = Path(temporary) / "python.exe"
            program.touch()
            environment = {
                utils_shutdown.SHUTDOWN_UI_ENV: str(program),
                utils_shutdown.SHUTDOWN_UI_ARGS_ENV: json.dumps(["-m", "gui.launcher"]),
            }
            with (
                patch.dict(os.environ, environment, clear=True),
                patch("sys.platform", "win32"),
                patch(
                    "src.utils.utils_shutdown.subprocess.run",
                    return_value=Mock(returncode=42),
                ) as run,
                patch("src.service.daily_plan.WindowsDailyTask") as task,
            ):
                self.assertTrue(utils_shutdown.shutdown_ui_supported())
                self.assertTrue(utils_shutdown._confirm_shutdown(45))
                self.assertEqual(
                    run.call_args.args[0],
                    [str(program), "-m", "gui.launcher", "--shutdown-confirm", "45"],
                )
                self.assertEqual(_run_target([], RunOptions())["env"], environment)
                _daily_task()
                arguments = task.call_args.kwargs["entry"][1]
                index = arguments.index("--shutdown-ui-args")
                self.assertEqual(
                    json.loads(arguments[index + 1]), ["-m", "gui.launcher"]
                )

    def test_invalid_confirmation_arguments_are_not_executed(self):
        with tempfile.TemporaryDirectory() as temporary:
            program = Path(temporary) / "gui.exe"
            program.touch()
            for arguments in ('{"shell": true}', "[3]", "null", "bad json"):
                with (
                    self.subTest(arguments=arguments),
                    patch.dict(
                        os.environ,
                        {
                            utils_shutdown.SHUTDOWN_UI_ENV: str(program),
                            utils_shutdown.SHUTDOWN_UI_ARGS_ENV: arguments,
                        },
                        clear=True,
                    ),
                    patch("sys.platform", "win32"),
                    patch("src.utils.utils_shutdown.subprocess.run") as run,
                    self.assertLogs(utils_shutdown.logger, level="ERROR"),
                ):
                    self.assertFalse(utils_shutdown._confirm_shutdown(1))
                    run.assert_not_called()

    def test_update_variant_comes_from_installation_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch("src.utils.get_root_dir", return_value=str(root)):
                self.assertEqual(_installed_frontend(), "qt")
                (root / "update-manifest.json").touch()
                for frontend in ("qt", "rust"):
                    with (
                        self.subTest(frontend=frontend),
                        patch(
                            "src.update.package.load_manifest",
                            return_value={"frontend": frontend},
                        ),
                    ):
                        self.assertEqual(_installed_frontend(), frontend)
