"""启动器定位、参数隔离和父进程启动生命周期。"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.utils import utils_launcher


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.settings = {
            "uninstall_id": "test-game-installation",
            "filename": "Launcher.exe",
            "arguments": ("--game=Example", "--reason=4"),
            "process_name": "Games.exe",
            "trusted_signers": frozenset({"TEST-SIGNER"}),
        }
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.game = self.root / "Example.exe"
        self.game.touch()
        self.enterContext(patch.object(utils_launcher.sys, "platform", "win32"))

    def _launch(self, game_path, game_arguments=""):
        return utils_launcher.launch_with_launcher(
            game_path, game_arguments, **self.settings
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
                            utils_launcher, "_verified_parent", return_value=42
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
                            self.assertEqual(self._launch(str(game), arguments), 314)
                        else:
                            with self.assertRaises(OSError):
                                self._launch(str(game), arguments)
                    prepare.assert_called_once_with(
                        kernel, "Games.exe", self.settings["trusted_signers"]
                    )
                    create.assert_called_once_with(kernel, str(game), arguments, 42)
                    kernel.CloseHandle.assert_called_once_with(42)
                    find.assert_not_called()
                    start.assert_not_called()

    def test_parent_mode_validates_input_before_starting_processes(self):
        for game, arguments, platform, error in (
            (None, "", "win32", FileNotFoundError),
            (str(self.root / "missing.exe"), "", "win32", FileNotFoundError),
            (str(self.game), None, "win32", ValueError),
            (str(self.game), "", "linux", OSError),
        ):
            with (
                self.subTest(game=game, arguments=arguments, platform=platform),
                patch.object(utils_launcher.sys, "platform", platform),
                patch.object(utils_launcher, "_kernel32") as kernel,
                patch.object(utils_launcher, "get_installed_launcher") as find,
                patch.object(utils_launcher.subprocess, "Popen") as start,
                self.assertRaises(error),
            ):
                self._launch(game, arguments)
            kernel.assert_not_called()
            find.assert_not_called()
            start.assert_not_called()

    def test_launcher_only_uses_registry_without_game_path_or_game_arguments(self):
        path = str(self.root / "NTELauncher.exe")
        with (
            patch.object(
                utils_launcher, "get_installed_launcher", return_value=path
            ) as find,
            patch.object(utils_launcher, "open_in_explorer") as open_launcher,
            patch.object(utils_launcher, "_kernel32") as kernel,
            patch.object(utils_launcher, "_running_pids") as processes,
        ):
            result = utils_launcher.launch_with_launcher(
                None,
                "--game-only",
                "YH",
                "NTELauncher.exe",
                ("--profile", "中文 空格"),
            )
        self.assertIsNone(result)
        find.assert_called_once_with("NTELauncher.exe", "YH", "NTELauncher.exe")
        open_launcher.assert_called_once_with(path, '--profile "中文 空格"')
        kernel.assert_not_called()
        processes.assert_not_called()

    def test_registry_miss_falls_back_to_game_ancestor_for_both_modes(self):
        game = self.root / "Game" / "Binaries" / "Example.exe"
        game.parent.mkdir(parents=True)
        game.touch()
        launcher = self.root / "Launcher.exe"
        launcher.touch()
        for parent_mode in (False, True):
            with self.subTest(parent_mode=parent_mode):
                kernel = MagicMock()
                with (
                    patch.object(
                        utils_launcher, "get_installed_launcher", return_value=None
                    ) as find,
                    patch.object(utils_launcher, "open_in_explorer") as open_launcher,
                    patch.object(utils_launcher, "_kernel32", return_value=kernel),
                    patch.object(utils_launcher, "_running_pids", return_value=[]),
                    patch.object(
                        utils_launcher, "_verified_parent", side_effect=[None, 42]
                    ),
                    patch.object(utils_launcher, "_verify_signature") as verify,
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
                ):
                    settings = dict(self.settings)
                    if not parent_mode:
                        settings["process_name"] = ""
                    result = utils_launcher.launch_with_launcher(
                        str(game), "--game-only", **settings
                    )
                find.assert_called_once_with(
                    "Launcher.exe", self.settings["uninstall_id"], "Launcher.exe"
                )
                if parent_mode:
                    self.assertEqual(result, 314)
                    verify.assert_called_once_with(
                        str(launcher), self.settings["trusted_signers"]
                    )
                    self.assertEqual(start.call_args.args[0][0], str(launcher))
                    create.assert_called_once_with(kernel, str(game), "--game-only", 42)
                    open_launcher.assert_not_called()
                else:
                    self.assertIsNone(result)
                    open_launcher.assert_called_once_with(
                        str(launcher), "--game=Example --reason=4"
                    )
                    start.assert_not_called()
                    create.assert_not_called()

    def test_missing_launcher_reports_failure_without_opening_game(self):
        with (
            patch.object(utils_launcher, "get_installed_launcher", return_value=None),
            patch.object(utils_launcher, "open_in_explorer") as open_launcher,
            self.assertRaisesRegex(FileNotFoundError, "NTELauncher.exe"),
        ):
            utils_launcher.launch_with_launcher(None, "", "YH", "NTELauncher.exe")
        open_launcher.assert_not_called()

    def test_cold_start_waits_before_creating_game_with_separate_arguments(self):
        path = os.path.abspath(os.path.join("Launcher Folder", "Launcher.exe"))
        kernel = MagicMock()
        with (
            patch.object(utils_launcher, "_kernel32", return_value=kernel),
            patch.object(utils_launcher, "_running_pids", return_value=[]),
            patch.object(
                utils_launcher,
                "_verified_parent",
                side_effect=[None, None, 42],
            ),
            patch.object(
                utils_launcher, "get_installed_launcher", return_value=path
            ) as find,
            patch.object(utils_launcher, "_verify_signature") as verify,
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
            self.assertEqual(self._launch(str(self.game), "--game-only"), 314)
        find.assert_called_once_with(
            "Launcher.exe", self.settings["uninstall_id"], "Launcher.exe"
        )
        verify.assert_called_once_with(path, self.settings["trusted_signers"])
        self.assertEqual(
            start.call_args.args[0], [path, "--game=Example", "--reason=4"]
        )
        sleep.assert_called_once_with(0.25)
        create.assert_called_once_with(kernel, str(self.game), "--game-only", 42)
        kernel.CloseHandle.assert_called_once_with(42)

    def test_launcher_timeout_does_not_start_game(self):
        kernel = MagicMock()
        with (
            patch.object(utils_launcher, "_kernel32", return_value=kernel),
            patch.object(utils_launcher, "_running_pids", return_value=[]),
            patch.object(utils_launcher, "_verified_parent", return_value=None),
            patch.object(
                utils_launcher,
                "get_installed_launcher",
                return_value=str(self.root / "Launcher.exe"),
            ),
            patch.object(utils_launcher, "_verify_signature"),
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
            self._launch(str(self.game))
        create.assert_not_called()
        kernel.CloseHandle.assert_not_called()

    def test_existing_game_is_not_started_twice(self):
        for running in (([123],), ([], [123])):
            with (
                self.subTest(running=running),
                patch.object(utils_launcher, "_running_pids", side_effect=running),
                patch.object(utils_launcher, "_kernel32") as kernel,
                patch.object(utils_launcher, "_verified_parent", return_value=42),
                patch.object(utils_launcher, "_create_game_process") as create,
                patch.object(utils_launcher.subprocess, "Popen") as start,
            ):
                self.assertIsNone(self._launch(str(self.game)))
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
                        utils_launcher,
                        "_verify_signature",
                        side_effect=failure,
                    ),
                    patch.object(utils_launcher, "get_installed_launcher") as find,
                    patch.object(utils_launcher.subprocess, "Popen") as start,
                    self.assertLogs(utils_launcher.logger, level="WARNING"),
                    self.assertRaises(RuntimeError) as raised,
                ):
                    self._launch(str(self.game))
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
