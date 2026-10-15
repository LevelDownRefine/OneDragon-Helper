"""测试 src.link 的链接、资源目标与图标来源查询。

覆盖各脚本官网/B站/GitHub 查询、未知脚本降级。
资源及完整链接在 config/script_resources.yml 声明；格式校验见 test_script_resources。
"""

import inspect
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import link
from src.config import set_config
from src.utils import utils_launcher


class TestLinkDispatch(unittest.TestCase):
    """测试官网/B站/GitHub 链接查询与未知脚本降级。"""

    def test_homepage_known(self):
        self.assertEqual(
            link.get_game_link("MAA", "homepage"), "https://ak.hypergryph.com/"
        )

    def test_bilibili_known(self):
        self.assertEqual(
            link.get_game_link("BetterGI", "bilibili"),
            "https://space.bilibili.com/401742377",
        )

    def test_github_known(self):
        self.assertEqual(
            link.get_game_link("ok-ww", "github"),
            "https://github.com/ok-oldking/ok-wuthering-waves",
        )

    def test_unknown_script_returns_empty(self):
        self.assertEqual(link.get_game_link("不存在", "homepage"), "")
        self.assertEqual(link.get_game_link("不存在", "bilibili"), "")
        self.assertEqual(link.get_game_link("不存在", "github"), "")


class ScriptTargetTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.script = self.root / "中文 script & data.exe"
        self.script.touch()
        self.lookup = self.enterContext(
            patch.object(
                link, "get_script", return_value={"script_path": str(self.script)}
            )
        )

    def test_game_icon_is_lazy_read_only_and_rereads_changed_paths(self):
        with (
            patch.object(link, "get_game_exe_path", side_effect=[None, "game.exe"]),
            patch.object(link, "resolve_script_path", return_value=str(self.script)),
        ):
            self.assertEqual(
                link.game_icon_path("example"),
                {"script_name": "example", "path": None},
            )
            self.assertEqual(
                link.game_icon_path("example"),
                {"script_name": "example", "path": str(self.script)},
            )
        self.lookup.return_value = None
        with patch.object(link, "get_game_exe_path") as resolve:
            self.assertIsNone(link.game_icon_path("removed")["path"])
        resolve.assert_not_called()

    def test_links_use_declaration_and_fallback_without_resolving_paths(self):
        for target, kind, fallback in (
            ("home", "homepage", "https://github.com/LevelDownRefine/OneDragon-Helper"),
            ("bili", "bilibili", "https://www.bilibili.com/"),
            ("github", "github", "https://github.com/LevelDownRefine/OneDragon-Helper"),
        ):
            for declared in ("https://example.org/game", ""):
                with (
                    self.subTest(target=target, declared=declared),
                    patch.object(
                        link, "get_game_link", return_value=declared
                    ) as declared_link,
                    patch.object(link, "resolve_script_path") as resolve,
                ):
                    self.assertEqual(
                        link.resolve_script_target("example", target),
                        {"kind": "url", "value": declared or fallback},
                    )
                    declared_link.assert_called_once_with("example", kind)
                    resolve.assert_not_called()

    def test_folder_and_logs_use_resolved_script_directory(self):
        logs = self.root / "中文 日志"
        logs.mkdir()
        with (
            patch.object(
                link, "resolve_script_path", return_value=str(self.script)
            ) as resolve,
            patch.object(link, "get_log_dir", return_value=str(logs)) as log_dir,
        ):
            self.assertEqual(
                link.resolve_script_target("example", "folder"),
                {"kind": "path", "value": str(self.root)},
            )
            self.assertEqual(
                link.resolve_script_target("example", "log"),
                {"kind": "path", "value": str(logs)},
            )
            log_dir.assert_called_once_with(self.lookup.return_value)
            self.assertEqual(resolve.call_count, 2)

    def test_config_file_preserves_existing_adapter_result(self):
        for path, error in ((str(self.script), None), (None, "配置文件缺失")):
            with (
                self.subTest(error=error),
                patch.object(link, "config_file_path", return_value=(path, error)),
            ):
                actual = link.resolve_script_target("example", "configfile")
                expected = (
                    {"kind": "unavailable", "reason": error}
                    if error
                    else {"kind": "path", "value": path}
                )
                self.assertEqual(actual, expected)

    def test_absent_script_directory_and_log_are_explicit(self):
        self.lookup.return_value = None
        self.assertEqual(
            link.resolve_script_target("missing", "home")["kind"], "unavailable"
        )
        self.lookup.return_value = {"script_path": str(self.script)}
        for path in (None, str(self.root / "missing")):
            with (
                self.subTest(path=path),
                patch.object(link, "get_log_dir", return_value=path),
            ):
                self.assertEqual(
                    link.resolve_script_target("example", "log")["kind"],
                    "unavailable",
                )
        with patch.object(
            link,
            "resolve_script_path",
            return_value=str(self.root / "missing" / "a.exe"),
        ):
            self.assertEqual(
                link.resolve_script_target("example", "folder"),
                {"kind": "unavailable", "reason": "脚本目录不存在"},
            )

    def test_game_launch_is_not_a_navigation_target(self):
        with self.assertRaises(ValueError):
            link.resolve_script_target("example", "game")
        self.lookup.assert_not_called()

    def test_empty_script_path_does_not_open_project_parent(self):
        self.lookup.return_value = {"script_path": ""}
        with patch.object(link, "resolve_script_path") as resolve:
            for target in ("folder", "log"):
                with self.subTest(target=target):
                    self.assertEqual(
                        link.resolve_script_target("example", target),
                        {"kind": "unavailable", "reason": "未找到脚本路径"},
                    )
        resolve.assert_not_called()


class LaunchTargetTests(unittest.TestCase):
    def test_missing_script_and_path_return_recoverable_reason(self):
        for script in (None, {"script_path": ""}, {"script_path": "missing.py"}):
            with (
                self.subTest(script=script),
                patch.object(link, "get_script", return_value=script),
                patch.object(link.os.path, "isfile", return_value=False),
            ):
                self.assertEqual(
                    link.resolve_launch_target("demo", "script")["kind"],
                    "unavailable",
                )

    def test_python_command_excludes_unchanged_environment_and_preserves_args(self):
        with tempfile.TemporaryDirectory() as temporary:
            file = Path(temporary) / "中文 & demo.py"
            file.touch()
            script = {"script_path": str(file), "script_type": "python"}
            with (
                patch.object(link, "get_script", return_value=script),
                patch.object(
                    link,
                    "build_script_command",
                    return_value=(
                        [
                            "/absolute/python",
                            "/absolute/runner/launcher.py",
                            "--script",
                            str(file),
                        ],
                        temporary,
                        {**os.environ, "ODH_TEST_EXTRA": "changed"},
                    ),
                ) as build,
            ):
                result = link.resolve_launch_target("demo", "script")
            self.assertEqual(result["kind"], "command")
            self.assertEqual(result["env"], {"ODH_TEST_EXTRA": "changed"})
            self.assertEqual(result["args"][-1], str(file))
            self.assertEqual(result["cwd"], temporary)
            build.assert_called_once_with(["--script", str(file)])

    def test_game_arguments_preserve_quotes_and_do_not_reach_script(self):
        with tempfile.TemporaryDirectory() as temporary:
            file = Path(temporary) / "game.exe"
            file.touch()
            arguments = '--profile "中文 空格" --literal "a&b"'
            with (
                patch.object(
                    link,
                    "get_script",
                    return_value={
                        "script_path": str(file),
                        "game_arguments": arguments,
                        "script_arguments": "--script-only",
                    },
                ),
                patch.object(link, "get_game_exe_path", return_value=str(file)),
            ):
                self.assertEqual(
                    link.resolve_launch_target("demo", "game"),
                    {
                        "kind": "association",
                        "path": str(file),
                        "arguments": arguments,
                    },
                )
                self.assertNotIn(
                    "arguments", link.resolve_launch_target("demo", "script")
                )

    def test_external_and_game_use_separate_targets(self):
        with tempfile.TemporaryDirectory() as temporary:
            file = Path(temporary) / "demo.exe"
            game = Path(temporary) / "game.exe"
            file.touch()
            game.touch()
            with (
                patch.object(
                    link,
                    "get_script",
                    return_value={"script_path": str(file)},
                ),
                patch.object(link, "get_game_exe_path", return_value=str(game)),
                patch.object(link, "build_script_command") as build,
            ):
                self.assertEqual(
                    link.resolve_launch_target("demo", "script"),
                    {"kind": "association", "path": str(file)},
                )
                self.assertEqual(
                    link.resolve_launch_target("demo", "game"),
                    {"kind": "association", "path": str(game)},
                )
            build.assert_not_called()


class LauncherTargetTests(unittest.TestCase):
    def test_endfield_adapter_provides_a_reusable_launcher_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary) / "Endfield.exe"
            launcher = Path(temporary) / "Launcher.exe"
            game.touch()
            launcher.touch()
            with (
                patch.object(
                    set_config, "get_script_game_path", return_value=str(game)
                ),
                patch.object(
                    set_config.EndfieldConfig,
                    "get_game_exe_path",
                    return_value=str(launcher),
                ),
            ):
                profile = object.__new__(
                    set_config.EndfieldConfig
                ).get_game_launch_info()
            self.assertEqual(profile["launcher_path"], str(launcher))
            self.assertEqual(profile["game_path"], str(game))
            self.assertEqual(profile["launcher_process_name"], "Games.exe")
            self.assertEqual(profile["game_process_name"], "Endfield.exe")
            self.assertTrue(profile["trusted_signers"])

    def test_launch_and_icon_use_adapter_path_and_user_arguments(self):
        with tempfile.TemporaryDirectory() as temporary:
            launcher = Path(temporary) / "launcher.exe"
            launcher.touch()
            for name, arguments in (("ok-nte", "--user-option"),):
                with (
                    self.subTest(script=name),
                    patch.object(
                        link,
                        "get_script",
                        return_value={
                            "script_path": str(launcher),
                            "game_arguments": arguments,
                        },
                    ),
                    patch.object(set_config, "get_script_game_path", return_value=""),
                    patch.object(
                        utils_launcher,
                        "get_installed_launcher",
                        return_value=str(launcher),
                    ),
                ):
                    self.assertEqual(
                        link.resolve_launch_target(name, "game"),
                        {
                            "kind": "association",
                            "path": str(launcher),
                            "arguments": arguments,
                        },
                    )
                    self.assertEqual(
                        link.resolve_launch_target(name, "script"),
                        {"kind": "association", "path": str(launcher)},
                    )
                    self.assertEqual(
                        link.game_icon_path(name),
                        {"script_name": name, "path": str(launcher)},
                    )

    def test_manual_endfield_path_keeps_user_arguments(self):
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "custom.exe"
            executable.touch()
            with (
                patch.object(
                    link,
                    "get_script",
                    return_value={
                        "script_path": "script.exe",
                        "game_arguments": "--custom",
                    },
                ),
                patch.object(
                    set_config, "get_script_game_path", return_value=str(executable)
                ),
                patch.object(utils_launcher, "get_installed_launcher") as find,
            ):
                self.assertEqual(
                    link.resolve_launch_target("ok-ef", "game"),
                    {
                        "kind": "association",
                        "path": str(executable),
                        "arguments": "--custom",
                    },
                )
                find.assert_not_called()

    def test_endfield_launch_uses_local_launcher_helper(self):
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary) / "Endfield.exe"
            launcher = Path(temporary) / "Launcher.exe"
            game.touch()
            launcher.touch()
            kernel = unittest.mock.MagicMock()
            create_process = unittest.mock.MagicMock(return_value=314)
            prepare_parent = unittest.mock.MagicMock(return_value=42)
            with (
                patch.object(utils_launcher.sys, "platform", "win32"),
                patch.object(utils_launcher, "_running_pids", side_effect=[[], []]),
                patch.object(utils_launcher, "_kernel32", return_value=kernel),
                patch.object(utils_launcher, "_prepare_parent", prepare_parent),
                patch.object(utils_launcher, "_create_game_process", create_process),
            ):
                self.assertEqual(
                    utils_launcher.launch_game(
                        str(game),
                        str(launcher),
                        "--game=Demo --reason=4",
                        "DemoLauncher.exe",
                        "Demo.exe",
                        {"AABB"},
                    ),
                    314,
                )
            create_process.assert_called_once_with(kernel, str(game), "", 42)
            prepare_parent.assert_called_once_with(
                kernel,
                str(launcher),
                "--game=Demo --reason=4",
                "DemoLauncher.exe",
                {"AABB"},
                30,
            )
            kernel.CloseHandle.assert_called_once_with(42)
            self.assertTrue(
                all(
                    parameter.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
                    for parameter in inspect.signature(
                        utils_launcher.launch_game
                    ).parameters.values()
                )
            )

    def test_launcher_arguments_are_appended_to_the_launcher_command_line(self):
        with tempfile.TemporaryDirectory() as temporary:
            launcher = Path(temporary) / "Launcher.exe"
            launcher.touch()
            kernel = unittest.mock.MagicMock()
            with (
                patch.object(
                    utils_launcher, "_verified_parent", side_effect=[None, 42]
                ),
                patch.object(utils_launcher, "_verify_official_launcher"),
                patch.object(utils_launcher.subprocess, "Popen") as start_launcher,
                patch.object(utils_launcher.time, "monotonic", side_effect=[0, 1]),
                patch.object(utils_launcher.time, "sleep"),
            ):
                self.assertEqual(
                    utils_launcher._prepare_parent(
                        kernel,
                        str(launcher),
                        "--game=Endfield --reason=4",
                        "Games.exe",
                        {"AABB"},
                        2,
                    ),
                    42,
                )
            self.assertTrue(
                start_launcher.call_args.args[0].endswith(" --game=Endfield --reason=4")
            )
            self.assertEqual(
                start_launcher.call_args.kwargs["executable"], str(launcher)
            )

    def test_endfield_launch_rejects_non_windows_and_missing_files(self):
        with (
            patch.object(utils_launcher.sys, "platform", "linux"),
            self.assertRaisesRegex(OSError, "仅支持 Windows"),
        ):
            utils_launcher.launch_game(
                "game.exe", "Launcher.exe", "", "Launcher.exe", "Game.exe", {"AABB"}
            )
        with (
            patch.object(utils_launcher.sys, "platform", "win32"),
            patch.object(utils_launcher.os.path, "isfile", return_value=False),
            self.assertRaises(FileNotFoundError),
        ):
            utils_launcher.launch_game(
                "game.exe", "Launcher.exe", "", "Launcher.exe", "Game.exe", {"AABB"}
            )


if __name__ == "__main__":
    unittest.main()
