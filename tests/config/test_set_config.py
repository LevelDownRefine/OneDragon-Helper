"""ScriptConfig 注册表、共享实例、公开分发接口和游戏路径适配。"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.config import daily as daily_mod
from src.config import set_config
from src.config.daily import Daily
from src.config.set_config import ScriptConfig, WutheringWavesConfig
from src.config.task_config import get_daily_configs
from src.utils import utils_sub_config


class TestConfigRelPaths(unittest.TestCase):
    """测试 ScriptConfig 子类路径声明完整性（_CONFIGS 注册表自动收集）"""

    def setUp(self):
        self.enterContext(patch.dict(set_config._CONFIGS))
        for factory in tuple(set_config._CONFIGS.values()):
            set_config.register(factory.__wrapped__)
        self.enterContext(
            patch.object(
                utils_sub_config, "_load_config_yml", return_value={"script_list": []}
            )
        )

    def test_registry_and_public_names_cover_all_scripts(self):
        expected = {
            "ok-ww",
            "BetterGI",
            "ok-ef",
            "OneDragon-Launcher",
            "March7th-Launcher",
            "ok-nte",
            "MAA",
        }
        self.assertEqual(set(set_config._CONFIGS), expected)
        names = set_config.get_registered_script_names()
        self.assertCountEqual(names, expected)

    def test_every_daily_declares_config(self):
        """每个注册脚本的日常声明都带非空 config（load 层强制，此处防回归）"""
        for name in set_config._CONFIGS:
            for declaration in get_daily_configs(name):
                with self.subTest(script=name, daily=declaration["display_name"]):
                    self.assertIn("config", declaration)
                    self.assertTrue(declaration["config"])

    def test_game_config_rel_path_covers_all(self):
        """全部 7 个脚本都声明了 _game_path_keys 与 _game_config_rel_path"""
        for name, factory in set_config._CONFIGS.items():
            cls = factory()
            self.assertTrue(cls._game_path_keys, f"{name} 缺少 _game_path_keys")
            self.assertTrue(
                cls._game_config_rel_path, f"{name} 缺少 _game_config_rel_path"
            )

    def test_init_config_warms_singleton_idempotently(self):
        """init_config 构造单例并触发对齐；重复调用返回同一实例（幂等）。"""
        name = "ok-ww"
        first = set_config._CONFIGS[name]()
        set_config.init_config(name)
        second = set_config._CONFIGS[name]()
        self.assertIs(first, second)

    def test_ensure_config_aligns_once_vs_init_config_twice(self):
        """预热用 ensure_config 仅构造触发一次 _init_config（无重复日志）；

        init_config 对缓存实例额外显式再调一次（强制重对齐，供新增/修改脚本、
        备份恢复）。这是 #64 warmup 重复日志的根因回归点。
        """
        name = "BetterGI"
        set_config._CONFIGS[name].cache_clear()
        with (
            patch.object(set_config.ScriptConfig, "_init_config") as init,
            patch.object(set_config, "load_config", return_value=None),
        ):
            set_config.ensure_config(name)
            self.assertEqual(init.call_count, 1)
        set_config._CONFIGS[name].cache_clear()
        with (
            patch.object(set_config.ScriptConfig, "_init_config") as init2,
            patch.object(set_config, "load_config", return_value=None),
        ):
            set_config.init_config(name)
            self.assertEqual(init2.call_count, 2)

    def test_template_rel_path_only_for_template_scripts(self):
        """模板路径只覆盖走模板初始化的脚本（粥已移除模板，仅 4 个）"""
        with_template = {
            name
            for name, factory in set_config._CONFIGS.items()
            if factory()._template_rel_path
        }
        self.assertEqual(
            with_template,
            {"BetterGI", "OneDragon-Launcher", "March7th-Launcher", "ok-ef"},
        )

    def test_rel_paths_contain_extension(self):
        """每个 config 相对路径应包含 .json 或 .yaml/.yml 扩展名"""
        valid_exts = (".json", ".yaml", ".yml")
        for name in set_config._CONFIGS:
            for declaration in get_daily_configs(name):
                rel = declaration["config"]
                ext = os.path.splitext(rel)[1].lower()
                self.assertIn(
                    ext, valid_exts, f"{name} 的 config 扩展名 {ext} 不在支持范围内"
                )


class TestSharedRegistry(unittest.TestCase):
    def test_first_access_builds_dailies_and_template_once(self):
        with (
            patch.dict(set_config._CONFIGS),
            patch.object(
                set_config, "get_daily_configs", wraps=set_config.get_daily_configs
            ) as declarations,
            patch.object(
                daily_mod, "load_template", wraps=daily_mod.load_template
            ) as template,
            patch.object(set_config, "load_config") as weekly_load,
            patch.object(set_config, "save_config") as weekly_save,
            patch.object(daily_mod, "load_script_config") as daily_load,
            patch.object(daily_mod, "save_script_config") as daily_save,
            patch.object(set_config.ArknightsConfig, "_init_config") as init,
        ):
            cls = set_config.register(set_config.ArknightsConfig)
            self.assertIs(cls, set_config.ArknightsConfig)
            self.assertTrue(set_config.is_adapted("MAA"))
            declarations.assert_not_called()
            template.assert_not_called()

            cfg = set_config._CONFIGS["MAA"]()
            self.assertIsInstance(cfg, cls)
            self.assertEqual(len(cfg._dailies), 3)
            declarations.assert_called_once_with("MAA")
            self.assertEqual(template.call_count, 3)
            dailies = cfg._dailies
            template.reset_mock()

            self.assertIs(set_config._CONFIGS["MAA"](), cfg)
            self.assertIs(set_config._CONFIGS["MAA"]()._dailies, dailies)
            declarations.assert_called_once_with("MAA")
            template.assert_not_called()
        for operation in (weekly_load, weekly_save, daily_load, daily_save):
            operation.assert_not_called()
        # 构造期对齐已收口到 __init__：首次构造调用一次，缓存命中不再调用
        init.assert_called_once()

    def test_menu_and_updates_use_the_same_daily(self):
        cfg = set_config._CONFIGS["ok-ww"]()
        daily = cfg._dispatch_daily("每日任务")
        source = {"path": "options.json"}
        with (
            patch.object(
                set_config,
                "get_daily_configs",
                side_effect=AssertionError("共享实例不应重复解析声明"),
            ),
            patch.object(daily, "update") as update,
            patch.object(daily, "get_task_lists", return_value=["甲"]) as reader,
        ):
            set_config.set_config("ok-ww", "每日任务", "凝素领域", 3)
            self.assertEqual(
                set_config.get_task_lists("ok-ww", "每日任务", source), ["甲"]
            )
        update.assert_called_once_with("凝素领域", 3)
        reader.assert_called_once_with(source)

    def test_shared_adapter_reads_current_script_path_and_contents(self):
        cfg = set_config._CONFIGS["ok-ww"]()
        with tempfile.TemporaryDirectory() as folder:
            roots = [Path(folder) / name for name in ("first", "second")]
            for root, value in zip(roots, (3, 5), strict=True):
                target = root / cfg._daily_config_rel_path()
                target.parent.mkdir(parents=True)
                target.write_text(
                    json.dumps(
                        {
                            "Which to Farm": "Forgery Challenge",
                            "Which Forgery Challenge to Farm": value,
                        }
                    ),
                    encoding="utf-8",
                )
            with patch.object(
                utils_sub_config, "get_script_root_dir", return_value=str(roots[0])
            ) as script_root:
                self.assertEqual(
                    set_config.get_daily_readback("ok-ww")[0]["sequence"], 3
                )
                script_root.return_value = str(roots[1])
                self.assertEqual(
                    set_config.get_daily_readback("ok-ww")[0]["sequence"], 5
                )
        self.assertIs(set_config._CONFIGS["ok-ww"](), cfg)


class TestIsAdapted(unittest.TestCase):
    """is_adapted：脚本是否已注册副本配置适配（GUI 任务卡显隐依据）。"""

    def test_registered_script_true(self):
        """已注册适配的脚本（如 ok-ww 鸣潮）→ True"""
        self.assertTrue(set_config.is_adapted("ok-ww"))

    def test_unregistered_script_false(self):
        """未注册适配的脚本（任意未知标识）→ False，不抛异常"""
        self.assertFalse(set_config.is_adapted("不存在的脚本"))


class TestIterBackupPaths(unittest.TestCase):
    """iter_backup_paths：各脚本声明的备份范围（目录或文件），与读写路径解耦。"""

    def test_game_path_declaration_only_matches_its_config(self):
        self.assertEqual(
            set_config.get_game_path_keys("BetterGI", "User/config.json"),
            ("genshinStartConfig", "installPath"),
        )
        self.assertEqual(
            set_config.get_game_path_keys("BetterGI", "User/other.json"), ()
        )
        self.assertEqual(
            set_config.get_game_path_keys("unknown", "User/config.json"), ()
        )

    def test_dir_style_script_declares_whole_dir(self):
        """整目录都是 config 的脚本（鸣潮 working/configs、原神 User）声明目录。"""
        paths = set_config.iter_backup_paths()
        self.assertEqual(paths["ok-ww"], ("data/apps/ok-ww/working/configs",))
        self.assertEqual(paths["BetterGI"], ("User",))

    def test_loose_file_script_declares_single_file(self):
        """散装单文件脚本（崩铁 config.yaml）声明文件，不声明目录。"""
        paths = set_config.iter_backup_paths()
        self.assertEqual(paths["March7th-Launcher"], ("config.yaml",))

    def test_every_registered_script_declares_backup_paths(self):
        """每个已适配脚本都必须声明非空备份范围（register 断言的对外保证）。"""
        paths = set_config.iter_backup_paths()
        self.assertEqual(set(paths), set(set_config._CONFIGS))
        for script_name, rel_paths in paths.items():
            self.assertTrue(rel_paths, f"{script_name} 未声明 _backup_paths")


class TestScriptConfigBase(unittest.TestCase):
    """测试基类 set_daily_task 的分发和保存行为。"""

    def test_set_daily_task_unknown_daily_raises(self):
        """日常展示名不在声明里 → assert（落点全部由声明推导，认不出即报）。"""
        cfg = WutheringWavesConfig()
        with (
            patch.object(Daily, "_load_daily_config", return_value={}),
            self.assertRaisesRegex(AssertionError, "未知日常"),
        ):
            cfg.set_daily_task("不存在的日常", "凝素领域", 3)

    def test_set_task_changed_saves(self):
        """set_daily_task 有修改时应（按声明落点）落盘"""
        cfg = WutheringWavesConfig()
        with (
            patch.object(
                Daily, "_load_daily_config", return_value={"Which to Farm": "old"}
            ),
            patch.object(Daily, "_save_daily_config") as mock_save,
        ):
            cfg.set_daily_task("每日任务", "凝素领域", 3)
        self.assertEqual(
            mock_save.call_args[0][0],
            {
                "Which to Farm": "Forgery Challenge",
                "Which Forgery Challenge to Farm": 3,
            },
        )

    def test_set_daily_task_unchanged_no_save(self):
        """set_daily_task 无修改时不调用 _save"""
        cfg = WutheringWavesConfig()
        current = {
            "Which to Farm": "Forgery Challenge",
            "Which Forgery Challenge to Farm": 3,
        }
        with (
            patch.object(Daily, "_load_daily_config", return_value=current),
            patch.object(Daily, "_save_daily_config") as mock_save,
        ):
            cfg.set_daily_task("每日任务", "凝素领域", 3)
        mock_save.assert_not_called()

    def test_daily_physical_name_available_on_base(self):
        """日常对象在基类可取（非异环专属）：单日常脚本亦然，物理名回落展示名。"""
        cfg = WutheringWavesConfig()
        self.assertEqual(cfg._dispatch_daily("每日任务").physical_name, "每日任务")
        with self.assertRaisesRegex(AssertionError, "未知日常"):
            cfg._dispatch_daily("不存在的日常")

    def test_set_daily_task_without_daily_raises(self):
        """写路径必须给出日常展示名（单日常脚本也不例外）。"""
        with patch("src.config.set_config.get_daily_configs", return_value=[]):
            cfg = ScriptConfig()
        cfg.display_name = "测试"
        with (
            patch.object(Daily, "_load_daily_config", return_value={"task": "old"}),
            self.assertRaisesRegex(AssertionError, "必须指定日常"),
        ):
            cfg.set_daily_task(None, "new")


class TestGetGameExePath(unittest.TestCase):
    """测试 ScriptConfig.get_game_exe_path：从各脚本游戏配置中提取游戏路径。"""

    def test_unadapted_base_returns_none(self):
        """基类未适配（_game_path_keys 为空）→ None，不触发任何读取"""
        with patch("src.config.set_config.get_daily_configs", return_value=[]):
            cfg = ScriptConfig()
        with patch("src.config.set_config.load_game_config") as mock_load:
            got = cfg.get_game_exe_path()
        self.assertIsNone(got)
        mock_load.assert_not_called()

    def test_ok_series_pc_full_path(self):
        """OK 系（ok-ww/ok-ef）读取 devices.json 的 pc_full_path。

        异环（ok-nte）已重写 get_game_exe_path 返回启动器路径，不在此列（见专项测试）。
        """
        for script_name in ("ok-ww", "ok-ef"):
            with patch(
                "src.config.set_config.load_game_config",
                return_value={
                    "preferred": "pc_1",
                    "pc_full_path": "D:\\Game\\game.exe",
                },
            ):
                got = set_config._CONFIGS[script_name]().get_game_exe_path()
            self.assertEqual(got, "D:\\Game\\game.exe")

    def test_nte_launcher_found_upward(self):
        """异环启动器在游戏安装根目录（从游戏本体逐级上溯）→ 返回 NTELauncher.exe 路径"""
        game_exe = os.path.join(
            "D:/Neverness To Everness",
            "Client",
            "WindowsNoEditor",
            "HT",
            "Binaries",
            "Win64",
            "HTGame.exe",
        )
        launcher = os.path.join("D:/Neverness To Everness", "NTELauncher.exe")
        with (
            patch(
                "src.config.set_config.load_game_config",
                return_value={"pc_full_path": game_exe},
            ),
            patch("os.path.isfile", side_effect=lambda p: p == launcher),
        ):
            got = set_config._CONFIGS["ok-nte"]().get_game_exe_path()
        self.assertEqual(got, launcher)

    def test_nte_launcher_missing_returns_none(self):
        """异环启动器不存在（上溯到盘符根也找不到）→ None，GUI 提示「未找到游戏路径」"""
        game_exe = os.path.join(
            "D:/Neverness To Everness",
            "Client",
            "WindowsNoEditor",
            "HT",
            "Binaries",
            "Win64",
            "HTGame.exe",
        )
        with (
            patch(
                "src.config.set_config.load_game_config",
                return_value={"pc_full_path": game_exe},
            ),
            patch("os.path.isfile", return_value=False),
        ):
            got = set_config._CONFIGS["ok-nte"]().get_game_exe_path()
        self.assertIsNone(got)

    def test_unconfigured_game_path_returns_none(self):
        for script, config in (
            ("ok-nte", None),
            ("ok-ww", None),
            ("ok-ww", {"other": "x"}),
            ("ok-ww", {"pc_full_path": ""}),
        ):
            with (
                self.subTest(script=script, config=config),
                patch("src.config.set_config.load_game_config", return_value=config),
            ):
                self.assertIsNone(set_config._CONFIGS[script]().get_game_exe_path())

    def test_genshin_nested_install_path(self):
        """原神（BetterGI）读取 config.json 的 genshinStartConfig.installPath（嵌套）"""
        with patch(
            "src.config.set_config.load_game_config",
            return_value={
                "genshinStartConfig": {
                    "installPath": "D:\\Genshin\\YuanShen.exe",
                }
            },
        ):
            got = set_config._CONFIGS["BetterGI"]().get_game_exe_path()
        self.assertEqual(got, "D:\\Genshin\\YuanShen.exe")

    def test_game_path_top_level(self):
        """绝区零/崩铁读取顶层 game_path"""
        for script_name in ("OneDragon-Launcher", "March7th-Launcher"):
            with patch(
                "src.config.set_config.load_game_config",
                return_value={"game_path": "D:\\Game\\game.exe"},
            ):
                got = set_config._CONFIGS[script_name]().get_game_exe_path()
            self.assertEqual(got, "D:\\Game\\game.exe")

    def test_arknights_nested_emulator_path(self):
        """粥（MAA）读取 gui.new.json 的 Configurations.Default.Gui.StartUpSettings.EmulatorPath（多级嵌套）"""
        with patch(
            "src.config.set_config.load_game_config",
            return_value={
                "Configurations": {
                    "Default": {
                        "Gui": {
                            "StartUpSettings": {
                                "EmulatorPath": "C:\\MuMu\\#0 MuMu安卓设备.lnk",
                            }
                        }
                    }
                }
            },
        ):
            got = set_config._CONFIGS["MAA"]().get_game_exe_path()
        self.assertEqual(got, "C:\\MuMu\\#0 MuMu安卓设备.lnk")


class TestGetGameExePathAdapter(unittest.TestCase):
    """测试适配器接口 get_game_exe_path 的分发逻辑"""

    def test_unknown_process_returns_none(self):
        """未注册（自定义）进程 → None"""
        got = set_config.get_game_exe_path("不存在")
        self.assertIsNone(got)

    def test_known_process_dispatches(self):
        factory = MagicMock()
        factory.return_value.get_game_exe_path.return_value = "D:/Game/game.exe"
        with patch.dict(set_config._CONFIGS, {"ok-ww": factory}, clear=True):
            self.assertEqual(set_config.get_game_exe_path("ok-ww"), "D:/Game/game.exe")
        factory.assert_called_once_with()
        factory.return_value.get_game_exe_path.assert_called_once_with()

    def test_entry_game_path_then_native(self):
        """config.yml 手填的 game_path 优先（用户显式指定），未填才用脚本原生配置。"""
        native = MagicMock()
        native.return_value.get_game_exe_path.return_value = "D:/native.exe"
        cases = (
            ("手填优先", {"ok-ww": native}, "D:/entry.exe", "D:/entry.exe"),
            ("回退原生", {"ok-ww": native}, "", "D:/native.exe"),
            ("两处皆无", {}, "", None),
        )
        for label, configs, entry, expected in cases:
            with (
                self.subTest(case=label),
                patch.dict(set_config._CONFIGS, configs, clear=True),
                patch.object(set_config, "get_script_game_path", return_value=entry),
            ):
                self.assertEqual(set_config.get_game_exe_path("ok-ww"), expected)


class TestSetConfigAdapter(unittest.TestCase):
    """测试适配器接口 set_config() 的分发逻辑"""

    def test_unselected_tasks_do_not_construct_or_call_an_adapter(self):
        for task in (None, "", "未选择"):
            with self.subTest(task=task):
                factory = MagicMock()
                with patch.dict(set_config._CONFIGS, {"ok-ww": factory}, clear=True):
                    set_config.set_config("ok-ww", task_name=task)
                factory.assert_not_called()
                factory.return_value.set_daily_task.assert_not_called()

    def test_unknown_process_does_not_touch_registry(self):
        for sequence in (None, "序列"):
            with self.subTest(sequence=sequence):
                factory = MagicMock()
                with patch.dict(set_config._CONFIGS, {"ok-ww": factory}, clear=True):
                    set_config.set_config(
                        "自定义脚本", task_name="副本", sequence=sequence
                    )
                factory.assert_not_called()
                factory.return_value.set_daily_task.assert_not_called()

    def test_dispatches_to_correct_subclass(self):
        """验证 set_config 正确分发到对应子类（日常名一并透传，顺序为日常→副本→序列）"""
        mock_instance = MagicMock()
        mock_factory = MagicMock(return_value=mock_instance)
        with patch.dict("src.config.set_config._CONFIGS", {"ok-ww": mock_factory}):
            set_config.set_config(
                "ok-ww",
                daily_display_name="每日任务",
                task_name="无音区",
                sequence="1",
            )
        mock_factory.assert_called_once()
        mock_instance.set_daily_task.assert_called_once_with("每日任务", "无音区", "1")


if __name__ == "__main__":
    unittest.main()
