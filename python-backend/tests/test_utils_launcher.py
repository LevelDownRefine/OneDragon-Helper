"""启动器类的生命周期和统一游戏入口的分派。"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.config.set_config import EndfieldConfig
from src.utils import utils_launcher


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.launcher = EndfieldConfig.launcher
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.game = self.root / "Endfield.exe"
        self.game.touch()
        self.enterContext(patch.object(utils_launcher.sys, "platform", "win32"))
        self.enterContext(
            patch.dict(
                utils_launcher.LAUNCHERS,
                {self.launcher.game_exe.casefold(): self.launcher},
                clear=True,
            )
        )

    def test_game_arguments_reach_game_and_parent_handle_is_released(self):
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary) / "ENDFIELD.exe"
            game.touch()
            for failure in (None, OSError("创建进程失败")):
                with self.subTest(failure=failure):
                    kernel = MagicMock()
                    with (
                        patch.object(utils_launcher.sys, "platform", "win32"),
                        patch.object(utils_launcher, "_running_pids", return_value=[]),
                        patch.object(utils_launcher, "_kernel32", return_value=kernel),
                        patch.object(
                            utils_launcher.Launcher, "_verified_parent", return_value=42
                        ) as prepare,
                        patch.object(utils_launcher, "get_installed_launcher") as find,
                        patch.object(utils_launcher.subprocess, "Popen") as start,
                        patch.object(
                            utils_launcher,
                            "_create_game_process",
                            return_value=314,
                            side_effect=failure,
                        ) as create,
                    ):
                        arguments = '-screen-width 1920 -logFile "game log.txt"'
                        if failure is None:
                            self.assertEqual(
                                self.launcher.launch(str(game), arguments), 314
                            )
                        else:
                            with self.assertRaises(OSError):
                                self.launcher.launch(str(game), arguments)
                    prepare.assert_called_once_with(kernel)
                    create.assert_called_once_with(kernel, str(game), arguments, 42)
                    kernel.CloseHandle.assert_called_once_with(42)
                    find.assert_not_called()
                    start.assert_not_called()

    def test_registered_launcher_dispatch_preserves_game_arguments(self):
        game = self.root / "ENDFIELD.exe"
        game.touch()
        arguments = '--profile "中文 空格" --literal "a&b"'
        with patch.object(
            utils_launcher.Launcher, "launch", return_value=314
        ) as launch:
            self.assertEqual(utils_launcher.launch_game(str(game), arguments), 314)
        launch.assert_called_once_with(str(game), arguments)

    def test_launcher_validates_input_before_starting_processes(self):
        for game, arguments, error in (
            (self.root / "missing.exe", "", FileNotFoundError),
            (self.game, None, ValueError),
        ):
            with (
                self.subTest(game=game, arguments=arguments),
                patch.object(utils_launcher, "_kernel32") as kernel,
                patch.object(utils_launcher.subprocess, "Popen") as start,
                self.assertRaises(error),
            ):
                self.launcher.launch(str(game), arguments)
            kernel.assert_not_called()
            start.assert_not_called()

    def test_plain_games_and_shortcuts_use_system_association(self):
        for name, platform in (
            ("游戏.exe", "win32"),
            ("游戏.lnk", "win32"),
            ("game", "linux"),
        ):
            game = self.root / name
            game.touch()
            arguments = (
                '--profile "中文 空格" --literal "a&b"' if platform == "win32" else ""
            )
            with (
                self.subTest(name=name, platform=platform),
                patch.object(utils_launcher.sys, "platform", platform),
                patch.object(utils_launcher, "open_in_explorer") as open_game,
                patch.object(utils_launcher, "_kernel32") as kernel,
                patch.object(utils_launcher, "get_installed_launcher") as find,
                patch.object(utils_launcher, "_running_pids") as processes,
            ):
                self.assertIsNone(utils_launcher.launch_game(str(game), arguments))
                open_game.assert_called_once_with(str(game), arguments)
                kernel.assert_not_called()
                find.assert_not_called()
                processes.assert_not_called()

    def test_cold_start_waits_before_creating_game_with_separate_arguments(self):
        launcher = self.launcher
        path = os.path.abspath(os.path.join("Launcher Folder", "Launcher.exe"))
        kernel = MagicMock()
        with (
            patch.object(utils_launcher, "_kernel32", return_value=kernel),
            patch.object(utils_launcher, "_running_pids", return_value=[]),
            patch.object(
                utils_launcher.Launcher,
                "_verified_parent",
                side_effect=[None, None, 42],
            ),
            patch.object(
                utils_launcher, "get_installed_launcher", return_value=path
            ) as find,
            patch.object(utils_launcher.Launcher, "_verify_signature") as verify,
            patch.object(utils_launcher.subprocess, "Popen") as start,
            patch.object(
                utils_launcher, "_create_game_process", return_value=314
            ) as create,
            patch.multiple(
                utils_launcher.subprocess,
                DETACHED_PROCESS=8,
                CREATE_NEW_PROCESS_GROUP=512,
                create=True,
            ),
            patch.object(utils_launcher.time, "monotonic", side_effect=[0, 1, 2]),
            patch.object(utils_launcher.time, "sleep") as sleep,
        ):
            self.assertEqual(self.launcher.launch(str(self.game), "--game-only"), 314)
        find.assert_called_once_with(
            launcher.process_name, launcher.uninstall_id, launcher.filename
        )
        verify.assert_called_once_with(path)
        self.assertEqual(
            start.call_args.args[0], [path, "--game=Endfield", "--reason=4"]
        )
        sleep.assert_called_once_with(0.25)
        create.assert_called_once_with(kernel, str(self.game), "--game-only", 42)
        kernel.CloseHandle.assert_called_once_with(42)

    def test_launcher_timeout_does_not_start_game(self):
        kernel = MagicMock()
        with (
            patch.object(utils_launcher, "_kernel32", return_value=kernel),
            patch.object(utils_launcher, "_running_pids", return_value=[]),
            patch.object(
                utils_launcher.Launcher, "_verified_parent", return_value=None
            ),
            patch.object(
                utils_launcher,
                "get_installed_launcher",
                return_value=str(self.root / "Launcher.exe"),
            ),
            patch.object(utils_launcher.Launcher, "_verify_signature"),
            patch.object(utils_launcher.subprocess, "Popen"),
            patch.multiple(
                utils_launcher.subprocess,
                DETACHED_PROCESS=8,
                CREATE_NEW_PROCESS_GROUP=512,
                create=True,
            ),
            patch.object(utils_launcher, "_create_game_process") as create,
            patch.object(utils_launcher.time, "monotonic", side_effect=[0, 1, 31]),
            patch.object(utils_launcher.time, "sleep"),
            self.assertRaises(TimeoutError),
        ):
            self.launcher.launch(str(self.game))
        create.assert_not_called()
        kernel.CloseHandle.assert_not_called()

    def test_existing_game_is_not_started_twice(self):
        for running in (([123],), ([], [123])):
            with (
                self.subTest(running=running),
                patch.object(utils_launcher, "_running_pids", side_effect=running),
                patch.object(utils_launcher, "_kernel32") as kernel,
                patch.object(
                    utils_launcher.Launcher, "_verified_parent", return_value=42
                ),
                patch.object(utils_launcher, "_create_game_process") as create,
                patch.object(utils_launcher.subprocess, "Popen") as start,
            ):
                self.assertIsNone(self.launcher.launch(str(self.game)))
                create.assert_not_called()
                start.assert_not_called()
                if len(running) == 1:
                    kernel.assert_not_called()
                else:
                    kernel.return_value.CloseHandle.assert_called_once_with(42)

    def test_rejected_parent_preserves_reason_without_restarting_launcher(self):
        for failure in (PermissionError("拒绝访问"), RuntimeError("签名无效")):
            with self.subTest(failure=failure):
                kernel = MagicMock()
                kernel.OpenProcess.return_value = 42
                if isinstance(failure, PermissionError):
                    kernel.OpenProcess.side_effect = failure

                def query_path(handle, flags, buffer, size):
                    buffer.value = os.path.abspath("Games.exe")
                    return True

                kernel.QueryFullProcessImageNameW.side_effect = query_path
                with (
                    patch.object(utils_launcher, "_kernel32", return_value=kernel),
                    patch.object(
                        utils_launcher, "_running_pids", side_effect=[[], [123]]
                    ),
                    patch.object(
                        utils_launcher.Launcher,
                        "_verify_signature",
                        side_effect=failure,
                    ),
                    patch.object(utils_launcher, "get_installed_launcher") as find,
                    patch.object(utils_launcher.subprocess, "Popen") as start,
                    self.assertLogs(utils_launcher.logger, level="WARNING"),
                    self.assertRaises(RuntimeError) as raised,
                ):
                    self.launcher.launch(str(self.game))
                self.assertIs(raised.exception.__cause__, failure)
                self.assertIn(str(failure), str(raised.exception))
                find.assert_not_called()
                start.assert_not_called()
                if isinstance(failure, PermissionError):
                    kernel.CloseHandle.assert_not_called()
                else:
                    kernel.CloseHandle.assert_called_once_with(42)


if __name__ == "__main__":
    unittest.main()
