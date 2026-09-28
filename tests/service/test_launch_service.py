"""启动目标复用路径/命令机制，查询不启动进程。"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.service import launch_service


class LaunchServiceTests(unittest.TestCase):
    def test_missing_script_and_path_return_recoverable_reason(self):
        for script in (None, {"script_path": ""}, {"script_path": "missing.py"}):
            with (
                self.subTest(script=script),
                patch.object(launch_service, "get_script", return_value=script),
                patch.object(launch_service.os.path, "isfile", return_value=False),
            ):
                self.assertEqual(
                    launch_service.resolve_launch_target("demo", "script")["kind"],
                    "unavailable",
                )

    def test_python_command_excludes_unchanged_environment_and_preserves_args(self):
        with tempfile.TemporaryDirectory() as temporary:
            file = Path(temporary) / "中文 & demo.py"
            file.touch()
            script = {"script_path": str(file), "script_type": "python"}
            with (
                patch.object(launch_service, "get_script", return_value=script),
                patch.object(
                    launch_service,
                    "build_script_command",
                    return_value=(
                        [
                            "/absolute/python",
                            "-m",
                            "src.runner.launcher",
                            "--script",
                            str(file),
                        ],
                        temporary,
                        {**os.environ, "ODH_TEST_EXTRA": "changed"},
                    ),
                ) as build,
            ):
                result = launch_service.resolve_launch_target("demo", "script")
            self.assertEqual(result["kind"], "command")
            self.assertEqual(result["env"], {"ODH_TEST_EXTRA": "changed"})
            self.assertEqual(result["args"][-1], str(file))
            self.assertEqual(result["cwd"], temporary)
            build.assert_called_once_with(["--script", str(file)])

    def test_external_and_game_use_separate_targets(self):
        with tempfile.TemporaryDirectory() as temporary:
            file = Path(temporary) / "demo.exe"
            game = Path(temporary) / "game.exe"
            file.touch()
            game.touch()
            with (
                patch.object(
                    launch_service,
                    "get_script",
                    return_value={"script_path": str(file)},
                ),
                patch.object(
                    launch_service, "get_game_exe_path", return_value=str(game)
                ),
                patch.object(launch_service, "build_script_command") as build,
            ):
                self.assertEqual(
                    launch_service.resolve_launch_target("demo", "script"),
                    {"kind": "association", "path": str(file)},
                )
                self.assertEqual(
                    launch_service.resolve_launch_target("demo", "game"),
                    {"kind": "association", "path": str(game)},
                )
            build.assert_not_called()
