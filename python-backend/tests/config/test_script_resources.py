"""资源声明的校验、路径基准、适配器消费与发布后定位。"""

import copy
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ruamel.yaml.constructor import DuplicateKeyError

from src import link
from src.config import script_resources as resources
from src.config import set_config
from src.log import monitor
from src.utils.utils_yaml import dump_yaml_str

ROOT = Path(__file__).resolve().parents[3]


class TestScriptResources(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.path = self.root / "config/script_resources.yml"
        self.path.parent.mkdir()
        self.data = {
            "version": 1,
            "scripts": {
                "demo": {
                    "backup_paths": ["配置"],
                    "background": "图片/背景.jpg",
                    "game": {"config": "配置/game.json", "keys": ["nested", "exe"]},
                    "logs": {"root": "script", "path": "日志"},
                    "links": {
                        "homepage": "https://example.com/",
                        "bilibili": "https://space.bilibili.com/1",
                        "github": "https://github.com/example/demo",
                    },
                }
            },
        }
        self.addCleanup(resources.load_resource_manifest.cache_clear)

    def load(self, data=None):
        resources.load_resource_manifest.cache_clear()
        self.path.write_text(
            dump_yaml_str(self.data if data is None else data), encoding="utf-8"
        )
        return resources.load_resource_manifest(str(self.path))

    def test_yaml_changes_reach_existing_consumers(self):
        """自定义声明经真实注册入口改变路径、字段和链接，无需新增硬编码。"""
        self.load()
        with (
            patch.object(resources, "get_root_dir", return_value=str(self.root)),
            patch.dict(set_config._CONFIGS, clear=True),
            patch("src.config.daily.get_daily_configs", return_value=[]),
            patch.object(set_config, "get_script_game_path", return_value=""),
            patch.object(
                set_config,
                "load_game_config",
                return_value={"nested": {"exe": "D:/游戏.exe"}},
            ) as load_game,
        ):

            @set_config.register
            class DemoConfig(set_config.ScriptConfig):
                _script_name = "demo"
                display_name = "演示"

            self.assertEqual(
                set_config.get_background_rel_path("demo"), "图片/背景.jpg"
            )
            self.assertEqual(set_config.iter_backup_paths()["demo"], ("配置",))
            self.assertEqual(set_config.get_game_exe_path("demo"), "D:/游戏.exe")
            self.assertEqual(
                set_config.get_game_path_keys("demo", "配置/game.json"),
                ("nested", "exe"),
            )
            self.assertEqual(
                link.get_game_link("demo", "homepage"), "https://example.com/"
            )
            load_game.assert_called_once_with("demo", "配置/game.json")
            self.assertNotIn("_init_config", set_config.ScriptConfig.__dict__)

    def test_missing_optional_resources_and_unknown_script(self):
        node = self.data["scripts"]["demo"]
        for name in ("game", "background", "logs"):
            del node[name]
        declaration = self.load()["demo"]
        self.assertEqual(declaration, node)
        with (
            patch.object(resources, "get_root_dir", return_value=str(self.root)),
            patch.dict(set_config._CONFIGS, clear=True),
            patch("src.config.daily.get_daily_configs", return_value=[]),
            patch.object(set_config, "load_game_config") as load_game,
        ):

            @set_config.register
            class DemoConfig(set_config.ScriptConfig):
                _script_name = "demo"
                display_name = "演示"

            self.assertIsNone(DemoConfig().get_game_exe_path())
            self.assertEqual(set_config.get_background_rel_path("demo"), "")
            self.assertEqual(set_config.get_game_path_keys("demo", "config.json"), ())
            self.assertEqual(set_config.iter_backup_paths()["demo"], ("配置",))
            load_game.assert_not_called()
            self.assertIsNone(resources.get_script_resources("unknown"))
            self.assertEqual(link.get_game_link("unknown", "github"), "")

    def test_invalid_shapes_fail_before_use(self):
        mutations = [
            (("version",), True),
            (("version",), 2),
            (("scripts",), []),
            (("scripts", "demo", "backups"), ["config"]),
            (("scripts", "demo", "template"), "旧模板.json"),
            (("scripts", "demo", "backup_paths"), []),
            (("scripts", "demo", "backup_paths"), ["config", "CONFIG"]),
            (("scripts", "demo", "game", "keys"), "path"),
            (("scripts", "demo", "game", "keys"), [True]),
            (("scripts", "demo", "game", "keys"), []),
            (("scripts", "demo", "logs", "root"), "cwd"),
            (("scripts", "demo", "links", "github"), "javascript:alert(1)"),
            (
                ("scripts", "demo", "links", "github"),
                "https://user:secret@example.com/",
            ),
        ]
        for keys, invalid in mutations:
            with self.subTest(keys=keys, value=invalid):
                data = copy.deepcopy(self.data)
                node = data
                for key in keys[:-1]:
                    node = node[key]
                node[keys[-1]] = invalid
                with self.assertRaises(AssertionError):
                    self.load(data)
        del self.data["scripts"]["demo"]["game"]["config"]
        with self.assertRaisesRegex(AssertionError, "缺少字段"):
            self.load()

    def test_paths_cannot_escape_their_declared_root(self):
        for path in (
            "/etc/file",
            "C:/game/file",
            "C:file",
            "//server/share",
            "../file",
            "a/../b",
            r"a\b",
            ".",
            "",
            "a//b",
        ):
            with self.subTest(path=path):
                data = copy.deepcopy(self.data)
                data["scripts"]["demo"]["background"] = path
                with self.assertRaises(AssertionError):
                    self.load(data)

    def test_missing_and_duplicate_declarations(self):
        with self.assertRaises(AssertionError):
            resources.load_resource_manifest(str(self.path))
        self.path.write_text("version: 1\nversion: 1\nscripts: {}\n", encoding="utf-8")
        with self.assertRaises(DuplicateKeyError):
            resources.load_resource_manifest(str(self.path))

    def test_yaml_shape_and_cache_until_reload(self):
        with patch.object(resources, "load_yaml", wraps=resources.load_yaml) as read:
            loaded = self.load()
            self.assertIsInstance(loaded["demo"], dict)
            self.assertIsInstance(loaded["demo"]["game"]["keys"], list)
            self.assertEqual(loaded, self.data["scripts"])
            self.data["scripts"]["demo"]["background"] = "changed.jpg"
            self.path.write_text(dump_yaml_str(self.data), encoding="utf-8")
            self.assertIs(resources.load_resource_manifest(str(self.path)), loaded)
            self.assertEqual(loaded["demo"]["background"], "图片/背景.jpg")
            read.assert_called_once_with(str(self.path))
            resources.load_resource_manifest.cache_clear()
            reloaded = resources.load_resource_manifest(str(self.path))
            self.assertEqual(reloaded["demo"]["background"], "changed.jpg")
            self.assertEqual(read.call_count, 2)

    def test_log_paths_preserve_script_and_temp_roots(self):
        expected = {
            "ok-ww": "data/apps/ok-ww/working/logs",
            "ok-nte": "data/apps/ok-nte/working/logs",
            "March7th-Launcher": "logs",
            "BetterGI": "log",
            "OneDragon-Launcher": ".log",
        }
        for name, path in expected.items():
            with self.subTest(script=name):
                self.assertEqual(
                    monitor.get_log_dir(name, str(self.root / "工具.exe")),
                    self.root / path,
                )
        self.assertEqual(
            monitor.get_log_dir("ok-ef", "/unrelated/ok-ef.exe"),
            Path(tempfile.gettempdir()) / "ok-ef/日常任务",
        )
        self.assertIsNone(monitor.get_log_dir("MAA", "MAA.exe"))
        # 声明解析不用当前工作目录，也能处理 Windows 分隔符。
        self.assertEqual(
            monitor.get_log_dir("BetterGI", r"D:\工具\程序.exe"),
            Path("D:/工具/log"),
        )

    def test_repository_manifest_covers_registered_adapters(self):
        manifest = resources.load_resource_manifest(
            str(ROOT / "config/script_resources.yml")
        )
        self.assertEqual(set(manifest), set(set_config.get_registered_script_names()))
        self.assertNotIn("template", manifest["BetterGI"])
        self.assertEqual(manifest["ok-nte"]["game"]["launcher"], "NTELauncher.exe")
        self.assertEqual(
            manifest["OneDragon-Launcher"]["background"],
            "assets/ui/static_background.webp",
        )
        self.assertEqual(
            manifest["March7th-Launcher"]["background"], "assets/app/images/bg37.jpg"
        )

    def test_frozen_resource_location_without_gui(self):
        """模拟冻结入口：仅复制资源，EXE 目录定位；禁止导入 GUI/Qt。"""
        shutil.copyfile(ROOT / "config/script_resources.yml", self.path)
        code = f"""
import importlib.abc
import sys
class NoGui(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        assert not fullname.startswith(("PySide6", "shiboken6", "gui")), fullname
sys.meta_path.insert(0, NoGui())
sys.frozen = True
sys.executable = {str(self.root / "OneDragon-Helper.exe")!r}
from src.config.script_resources import get_script_resources
from src.link import get_game_link
assert get_script_resources("ok-ww")["game"]["keys"] == ["pc_full_path"]
assert get_game_link("MAA", "homepage") == "https://ak.hypergryph.com/"
"""
        env = {
            **os.environ,
            "PYTHONPATH": str(ROOT / "python-backend"),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
