"""官方启动器的参数路由、进程复用和拒绝原因。"""

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
                            utils_launcher, "_prepare_parent", return_value=42
                        ) as prepare,
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
                                utils_launcher.launch_game(str(game), arguments), 314
                            )
                        else:
                            with self.assertRaises(OSError):
                                utils_launcher.launch_game(str(game), arguments)
                    prepare.assert_called_once_with(kernel, self.launcher)
                    create.assert_called_once_with(kernel, str(game), arguments, 42)
                    kernel.CloseHandle.assert_called_once_with(42)

    def test_running_launcher_does_not_require_registry_entry(self):
        with (
            patch.object(utils_launcher, "_verified_parent", return_value=42),
            patch.object(utils_launcher, "get_installed_launcher") as find,
            patch.object(utils_launcher.subprocess, "Popen") as start,
        ):
            self.assertEqual(
                utils_launcher._prepare_parent(MagicMock(), self.launcher),
                42,
            )
        find.assert_not_called()
        start.assert_not_called()

    def test_cold_start_uses_launcher_arguments(self):
        launcher = self.launcher
        path = os.path.abspath(os.path.join("Launcher Folder", "Launcher.exe"))
        with (
            patch.object(utils_launcher, "_verified_parent", side_effect=[None, 42]),
            patch.object(
                utils_launcher, "get_installed_launcher", return_value=path
            ) as find,
            patch.object(utils_launcher, "_verify_official_launcher") as verify,
            patch.object(utils_launcher.subprocess, "Popen") as start,
            patch.multiple(
                utils_launcher.subprocess,
                DETACHED_PROCESS=8,
                CREATE_NEW_PROCESS_GROUP=512,
                create=True,
            ),
            patch.object(utils_launcher.time, "monotonic", side_effect=[0, 1]),
        ):
            self.assertEqual(utils_launcher._prepare_parent(MagicMock(), launcher), 42)
        find.assert_called_once_with(
            launcher.process_name, launcher.uninstall_id, launcher.filename
        )
        verify.assert_called_once_with(path, launcher.trusted_signers)
        self.assertEqual(
            start.call_args.args[0], [path, "--game=Endfield", "--reason=4"]
        )

    def test_rejected_parent_preserves_reason_without_restarting_launcher(self):
        launcher = self.launcher
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
                    patch.object(utils_launcher, "_running_pids", return_value=[123]),
                    patch.object(
                        utils_launcher, "_verify_official_launcher", side_effect=failure
                    ),
                    patch.object(utils_launcher, "get_installed_launcher") as find,
                    patch.object(utils_launcher.subprocess, "Popen") as start,
                    self.assertLogs(utils_launcher.logger, level="WARNING"),
                    self.assertRaises(RuntimeError) as raised,
                ):
                    utils_launcher._prepare_parent(kernel, launcher)
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
