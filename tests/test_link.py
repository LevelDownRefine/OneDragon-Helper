"""测试 src.link 的链接、资源目标与图标来源查询。

覆盖各脚本官网/B站/GitHub 查询、未知脚本降级。
资源及完整链接在 config/script_resources.yml 声明；格式校验见 test_script_resources。
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import link


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
            log_dir.assert_called_once_with("example", str(self.script))
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


if __name__ == "__main__":
    unittest.main()
