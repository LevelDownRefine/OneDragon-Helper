"""资源跳转只解析现有目标，缺失资源可解释且不执行外部动作。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.service import resource_service as resources


class ScriptTargetTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.script = self.root / "中文 script & data.exe"
        self.script.touch()
        self.lookup = self.enterContext(
            patch.object(
                resources, "get_script", return_value={"script_path": str(self.script)}
            )
        )

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
                        resources, "get_game_link", return_value=declared
                    ) as link,
                    patch.object(resources, "resolve_script_path") as resolve,
                ):
                    self.assertEqual(
                        resources.resolve_script_target("example", target),
                        {"kind": "url", "value": declared or fallback},
                    )
                    link.assert_called_once_with("example", kind)
                    resolve.assert_not_called()

    def test_folder_and_logs_use_resolved_script_directory(self):
        logs = self.root / "中文 日志"
        logs.mkdir()
        with (
            patch.object(
                resources, "resolve_script_path", return_value=str(self.script)
            ) as resolve,
            patch.object(resources, "get_log_dir", return_value=str(logs)) as log_dir,
        ):
            self.assertEqual(
                resources.resolve_script_target("example", "folder"),
                {"kind": "path", "value": str(self.root)},
            )
            self.assertEqual(
                resources.resolve_script_target("example", "log"),
                {"kind": "path", "value": str(logs)},
            )
            log_dir.assert_called_once_with("example", str(self.script))
            self.assertEqual(resolve.call_count, 2)

    def test_config_file_preserves_existing_adapter_result(self):
        for path, error in ((str(self.script), None), (None, "配置文件缺失")):
            with (
                self.subTest(error=error),
                patch.object(resources, "config_file_path", return_value=(path, error)),
            ):
                actual = resources.resolve_script_target("example", "configfile")
                expected = (
                    {"kind": "unavailable", "reason": error}
                    if error
                    else {"kind": "path", "value": path}
                )
                self.assertEqual(actual, expected)

    def test_absent_script_directory_and_log_are_explicit(self):
        self.lookup.return_value = None
        self.assertEqual(
            resources.resolve_script_target("missing", "home")["kind"], "unavailable"
        )
        self.lookup.return_value = {"script_path": str(self.script)}
        for path in (None, str(self.root / "missing")):
            with (
                self.subTest(path=path),
                patch.object(resources, "get_log_dir", return_value=path),
            ):
                self.assertEqual(
                    resources.resolve_script_target("example", "log")["kind"],
                    "unavailable",
                )
        with patch.object(
            resources,
            "resolve_script_path",
            return_value=str(self.root / "missing" / "a.exe"),
        ):
            self.assertEqual(
                resources.resolve_script_target("example", "folder"),
                {"kind": "unavailable", "reason": "脚本目录不存在"},
            )

    def test_game_launch_is_not_a_navigation_target(self):
        with self.assertRaises(ValueError):
            resources.resolve_script_target("example", "game")
        self.lookup.assert_not_called()
