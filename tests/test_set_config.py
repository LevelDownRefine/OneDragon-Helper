"""
测试 set_config.py 中的子脚本 config 读写基础设施。

覆盖函数：
  - _CONFIGS（子类路径声明完整性）
  - iter_backup_paths（备份范围声明）
  - get_sub_config_path
  - load_config
  - save_config（mock 文件写入，不真正写回脚本 config）
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import mock_open, patch

from src.config import daily as daily_mod
from src.config import set_config
from src.config.task_config import get_daily_configs
from src.utils import safe_path_join, utils_sub_config
from src.utils.utils_yaml import dump_yaml_str, load_yaml_str


class TestConfigRelPaths(unittest.TestCase):
    """测试 ScriptConfig 子类路径声明完整性（_CONFIGS 注册表自动收集）"""

    def test_configs_registry_covers_all_scripts(self):
        """_CONFIGS 覆盖全部 8 个已适配脚本（进程名）"""
        self.assertEqual(
            set(set_config._CONFIGS.keys()),
            {
                "ok-ww",
                "BetterGI",
                "ok-ef",
                "OneDragon-Launcher",
                "March7th-Launcher",
                "ok-nte",
                "MAA",
                "MaaEnd",
            },
        )

    def test_every_daily_declares_config(self):
        """每个注册脚本的日常声明都带非空 config（load 层强制，此处防回归）"""
        for name in set_config._CONFIGS:
            for declaration in get_daily_configs(name):
                self.assertTrue(
                    declaration.get("config"),
                    f"{name} 的 {declaration['display_name']} 未声明 config",
                )

    def test_game_config_rel_path_covers_all(self):
        """声明了 _game_path_keys 的脚本都补全 _game_config_rel_path（MaaEnd 两者皆空）。"""
        for name, factory in set_config._CONFIGS.items():
            cls = factory()
            if not cls._game_path_keys:
                self.assertFalse(
                    cls._game_config_rel_path, f"{name} 无游戏路径却声明了配置文件"
                )
                continue
            self.assertTrue(
                cls._game_config_rel_path, f"{name} 缺少 _game_config_rel_path"
            )

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

    def test_weekly_task_name_requires_prepare_weekly_start_day(self):
        """声明 _weekly_task_name 的子类必须覆写 prepare_weekly_start_day（register 完整性校验）"""
        for name, factory in set_config._CONFIGS.items():
            cls = factory()
            if cls._weekly_task_name:
                self.assertTrue(
                    type(cls).prepare_weekly_start_day
                    is not set_config.ScriptConfig.prepare_weekly_start_day,
                    f"{name} 声明了 _weekly_task_name 但未覆写 prepare_weekly_start_day",
                )

    def test_register_rejects_weekly_without_write(self):
        """register 拒绝：声明 _weekly_task_name 但沿用基类 prepare_weekly_start_day 的子类"""
        bogus = type(
            "BogusWeekly",
            (set_config.ScriptConfig,),
            {
                "_script_name": "bogus-weekly",
                "_config_rel_path": "config.json",
                "_weekly_task_name": "weekly",
            },
        )
        with self.assertRaises(AssertionError):
            set_config.register(bogus)

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
            patch.object(daily_mod, "load_config") as daily_load,
            patch.object(daily_mod, "save_config") as daily_save,
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
        for operation in (weekly_load, weekly_save, daily_load, daily_save, init):
            operation.assert_not_called()

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


class TestGetConfigPath(unittest.TestCase):
    """测试 get_sub_config_path"""

    def test_joins_root_and_rel(self):
        """应正确拼接脚本根目录和 config 相对路径"""
        # mock Windows 风格的 script_path，验证在任意平台上都能推导
        fake_config = {
            "script_list": [
                {"display_name": "鸣潮", "script_path": r"C:\fake\ok-ww\ok-ww.exe"},
            ]
        }
        rel = "data/apps/ok-ww/working/configs/DailyTask.json"
        with (
            patch.object(
                utils_sub_config, "_load_config_yml", return_value=fake_config
            ),
            patch("os.path.exists", return_value=True),
        ):
            path = utils_sub_config.get_sub_config_path("ok-ww", rel)

        # get_sub_config_path 内部用 safe_path_join，会归一化为绝对路径（Windows 为反斜杠），
        # 故 expected 需用同一归一化方式，避免分隔符不一致导致断言失败。
        expected = safe_path_join("C:/fake/ok-ww", rel)
        self.assertEqual(path, expected)

    def test_raises_for_unknown_script(self):
        """config.yml 中无此脚本应触发 AssertionError"""
        with (
            patch.object(
                utils_sub_config, "_load_config_yml", return_value={"script_list": []}
            ),
            self.assertRaises(AssertionError),
        ):
            utils_sub_config.get_sub_config_path("none", "whatever.json")

    def test_all_registered_scripts_resolve_with_mock_config(self):
        """对所有已注册脚本，用 mock 的 config.yml 验证路径推导成功
        （不依赖真实 config.yml，CI 也能跑）"""
        scripts = list(set_config._CONFIGS.keys())
        # 构造 mock config：每个脚本一个唯一的 script_path（key 即进程名）
        fake_script_list = [
            {
                "display_name": name,
                "script_path": rf"C:\fake\root\{name}.exe",
            }
            for name in scripts
        ]
        with (
            patch.object(
                utils_sub_config,
                "_load_config_yml",
                return_value={"script_list": fake_script_list},
            ),
            patch("os.path.exists", return_value=True),
        ):
            for name in scripts:
                declarations = get_daily_configs(name)
                if not declarations:
                    continue  # 无日常声明的脚本（MaaEnd）：没有 config 落点
                rel = declarations[0]["config"]
                path = utils_sub_config.get_sub_config_path(name, rel)
                self.assertIsNotNone(path, f"{name} 路径推导失败")
                # 路径中应包含相对路径的各段（不依赖具体分隔符）
                rel_parts = rel.split("/")
                for part in rel_parts:
                    self.assertIn(
                        part, path, f"{name} 路径缺少相对路径段 '{part}': {path}"
                    )

    def test_does_not_require_exe_to_exist(self):
        """回归：get_sub_config_path 不应校验游戏 exe 是否存在。

        旧实现经 _get_script_root_dir → get_script_path 断言 exe 存在，
        当用户正要修正失效的旧路径时，任何保存（含周起始日同步）都会崩溃。
        新实现用 soft 解析，exe 是否存在与 config 文件位置无关。
        """
        fake_config = {
            "script_list": [
                {
                    "display_name": "崩铁",
                    "script_path": r"D:\game_helper\March7thAssistant\March7th Launcher.exe",
                },
            ]
        }
        rel = get_daily_configs("March7th-Launcher")[0]["config"]
        with (
            patch.object(
                utils_sub_config, "_load_config_yml", return_value=fake_config
            ),
            patch("os.path.exists", return_value=False),  # 模拟 exe 不存在
        ):
            # 旧实现此处会因 get_script_path 的 assert os.path.exists(exe) 崩溃；
            # 新实现应正常返回路径（不依赖 exe 是否存在）。
            path = utils_sub_config.get_sub_config_path("March7th-Launcher", rel)
        self.assertIn("config.yaml", path)


class TestStarRailWeeklyStartDayRobustness(unittest.TestCase):
    """回归：崩铁 set_weekly_start_day 的读路径不应因 exe 路径失效而崩溃（soft 解析）。

    旧实现 get_sub_config_path → get_script_path 断言 exe 存在；用户正要修正失效的旧路径时
    保存即崩。修复后 get_sub_config_path 用 soft 解析（不校验 exe），读路径不再因路径失效
    而断言。写游戏侧 config 视为前置条件（游戏已安装、路径有效，由 GUI 保证），不再做
    存在性兜底盘；非法周起始日仍由 assert 拦截。
    """

    def test_invalid_day_still_asserted(self):
        """非法周起始日（非 1~7）仍应被系统拦截。"""
        cfg = set_config.StarRailConfig()
        with self.assertRaises(AssertionError):
            cfg.set_weekly_start_day(99)


class TestArknightsWeeklyStartDayRobustness(unittest.TestCase):
    """回归：MAA(明日方舟) set_weekly_start_day 的读路径不再因 exe 路径失效而崩溃。

    与 TestStarRailWeeklyStartDayRobustness 同源修复（get_sub_config_path soft 解析）。
    写游戏侧 config 视为前置条件（游戏已安装、路径有效，由 GUI 保证），原生 config
    缺失即断言失败，不再 best-effort 跳过；非法周起始日仍由 assert 拦截。
    """

    def test_invalid_day_still_asserted(self):
        cfg = set_config.ArknightsConfig()
        with self.assertRaises(AssertionError):
            cfg.set_weekly_start_day(0)


class TestLoadConfig(unittest.TestCase):
    """测试 load_config"""

    def test_load_json_config(self):
        """应正确解析 JSON 格式的 config"""
        fake_data = {"key": "value", "nested": {"a": 1}}
        fake_path = r"C:\fake\script\config.json"

        with (
            patch.object(
                utils_sub_config, "get_sub_config_path", return_value=fake_path
            ),
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=json.dumps(fake_data))),
        ):
            result = utils_sub_config.load_config("ok-ww", "DailyTask.json")

        self.assertEqual(result, fake_data)

    def test_load_yaml_config(self):
        """应正确解析 YAML 格式的 config"""
        fake_data = {"key": "value", "list": [1, 2, 3]}
        fake_path = r"C:\fake\script\config.yaml"
        yaml_str = dump_yaml_str(fake_data)

        with (
            patch.object(
                utils_sub_config, "get_sub_config_path", return_value=fake_path
            ),
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=yaml_str)),
        ):
            result = utils_sub_config.load_config(
                "OneDragon-Launcher", "charge_plan.yml"
            )

        self.assertEqual(result, fake_data)

    def test_load_all_registered_configs_with_mock(self):
        """对所有已注册脚本，用 mock config 文件验证读取逻辑
        （不依赖真实 config 文件，CI 也能跑）"""
        scripts = list(set_config._CONFIGS.keys())
        # 构造 mock config.yml + mock 文件内容
        fake_script_list = [
            {
                "display_name": name,
                "script_path": rf"C:\fake\root\{name}.exe",
            }
            for name in scripts
        ]
        fake_config_yml = {"script_list": fake_script_list}

        for name in scripts:
            declarations = get_daily_configs(name)
            if not declarations:
                continue  # 无日常声明的脚本（MaaEnd）：没有 config 落点
            rel = declarations[0]["config"]
            ext = os.path.splitext(rel)[1].lower()
            fake_data = {"test_key": "test_value"}
            if ext == ".json":
                file_content = json.dumps(fake_data, ensure_ascii=False)
            else:
                file_content = dump_yaml_str(fake_data)

            with (
                patch.object(
                    utils_sub_config, "_load_config_yml", return_value=fake_config_yml
                ),
                patch("os.path.exists", return_value=True),
                patch("builtins.open", mock_open(read_data=file_content)),
            ):
                result = utils_sub_config.load_config(name, rel)

            self.assertIsNotNone(result, f"{name} config 读取失败")
            self.assertEqual(result, fake_data, f"{name} config 读取内容不匹配")


class TestLoadReadPathTolerance(unittest.TestCase):
    """Daily 读路径的失败处理：未安装/缺失静默按未设置，内容损坏留痕后仍按未设置。"""

    def _daily(self):
        return set_config._CONFIGS["ok-ww"]()._dispatch_daily("每日任务")

    def test_missing_config_returns_none_without_warning(self):
        """config 缺失（以断言表达）属正常状态 → None 且不告警。"""
        with (
            patch.object(
                daily_mod,
                "load_config",
                side_effect=AssertionError("config 文件不存在"),
            ),
            self.assertNoLogs("src.config.daily", level="WARNING"),
        ):
            self.assertIsNone(self._daily()._load_daily_config(allow_missing=True))

    def test_corrupt_config_warns_and_returns_none(self):
        """文件存在但解析失败 → None 且留下 warning（不静默把损坏当未设置）。"""
        with (
            patch.object(
                daily_mod,
                "load_config",
                side_effect=json.JSONDecodeError("bad json", "{", 0),
            ),
            self.assertLogs("src.config.daily", level="WARNING"),
        ):
            self.assertIsNone(self._daily()._load_daily_config(allow_missing=True))

    def test_write_path_raises_on_corrupt_config(self):
        """写路径（allow_missing=False）读取失败一律抛出，不降级为 None。"""
        with (
            patch.object(
                daily_mod,
                "load_config",
                side_effect=json.JSONDecodeError("bad json", "{", 0),
            ),
            self.assertRaises(json.JSONDecodeError),
        ):
            self._daily()._load_daily_config()


class TestSaveConfig(unittest.TestCase):
    """测试 save_config —— 全部 mock，不真正写回脚本 config"""

    def test_save_json_config_does_not_write_real_file(self):
        """save JSON 时不应写入真实 config 文件"""
        fake_path = r"C:\fake\script\config.json"
        data = {"Which to Farm": "Tacet"}

        m = mock_open()
        with (
            patch.object(
                utils_sub_config, "get_sub_config_path", return_value=fake_path
            ),
            patch("builtins.open", m),
        ):
            result = utils_sub_config.save_config("ok-ww", "DailyTask.json", data)

        self.assertIsNone(result)
        m.assert_called_once_with(fake_path, "w", encoding="utf-8")
        # 验证写入的内容是正确的 JSON
        handle = m()
        written = "".join(call.args[0] for call in handle.write.call_args_list)
        self.assertEqual(json.loads(written), data)

    def test_save_yaml_config_does_not_write_real_file(self):
        """save YAML 时不应写入真实 config 文件

        dump_yaml 为原子写：先写同目录 .tmp，再 os.replace 到目标路径。
        """
        fake_path = r"C:\fake\script\charge_plan.yml"
        data = {"plan_list": [{"category_name": "test"}]}

        m = mock_open()
        with (
            patch.object(
                utils_sub_config, "get_sub_config_path", return_value=fake_path
            ),
            patch("builtins.open", m),
            patch("src.utils.utils_yaml.os.replace") as mock_replace,
        ):
            result = utils_sub_config.save_config(
                "OneDragon-Launcher", "charge_plan.yml", data
            )

        self.assertIsNone(result)
        # 原子写：写入目标是 .tmp，随后原子替换到目标路径
        m.assert_called_once_with(fake_path + ".tmp", "w", encoding="utf-8")
        mock_replace.assert_called_once_with(fake_path + ".tmp", fake_path)
        # 验证写入的内容是有效的 YAML
        handle = m()
        written = "".join(call.args[0] for call in handle.write.call_args_list)
        self.assertEqual(load_yaml_str(written), data)

    def test_save_raises_when_path_is_none(self):
        """get_sub_config_path 返回 None 时应抛出异常"""
        with (
            patch.object(utils_sub_config, "get_sub_config_path", return_value=None),
            self.assertRaises((TypeError, AssertionError)),
        ):
            utils_sub_config.save_config("none", "whatever.json", {"key": "val"})

    def test_save_and_reload_roundtrip_json(self):
        """JSON 数据 save 后 load 回来应一致（用 tempdir 替代真实路径）"""
        data = {"test_key": "test_value", "num": 42}

        with tempfile.TemporaryDirectory() as tmp:
            fake_path = os.path.join(tmp, "config.json")
            with patch.object(
                utils_sub_config, "get_sub_config_path", return_value=fake_path
            ):
                # save
                ok = utils_sub_config.save_config("ok-ww", "DailyTask.json", data)
                self.assertIsNone(ok)
                # load
                loaded = utils_sub_config.load_config("ok-ww", "DailyTask.json")
                self.assertEqual(loaded, data)

    def test_save_and_reload_roundtrip_yaml(self):
        """YAML 数据 save 后 load 回来应一致（用 tempdir 替代真实路径）"""
        data = {"plan_list": [{"category_name": "模拟"}], "enabled": True}

        with tempfile.TemporaryDirectory() as tmp:
            fake_path = os.path.join(tmp, "config.yaml")
            with patch.object(
                utils_sub_config, "get_sub_config_path", return_value=fake_path
            ):
                # save
                ok = utils_sub_config.save_config(
                    "OneDragon-Launcher", "charge_plan.yml", data
                )
                self.assertIsNone(ok)
                # load
                loaded = utils_sub_config.load_config(
                    "OneDragon-Launcher", "charge_plan.yml"
                )
                self.assertEqual(loaded, data)


class TestSafeUpdate(unittest.TestCase):
    """测试 safe_update"""

    def test_update_changes_value(self):
        """值不同时更新并返回 True"""
        from src.utils.utils_dict import safe_update

        config = {"key": "old"}
        result = safe_update(config, "key", "new", "test")
        self.assertTrue(result)
        self.assertEqual(config["key"], "new")

    def test_no_change_when_same_value(self):
        """值相同时不更新并返回 False"""
        from src.utils.utils_dict import safe_update

        config = {"key": "same"}
        result = safe_update(config, "key", "same", "test")
        self.assertFalse(result)
        self.assertEqual(config["key"], "same")

    def test_key_not_exists_raises(self):
        """key 不存在时 assert（默认）"""
        from src.utils.utils_dict import safe_update

        config = {}
        with self.assertRaises(AssertionError):
            safe_update(config, "missing", "value", "test")

    def test_key_not_exists_adds_with_flag(self):
        """assert_key_exists=False 时允许添加新 key"""
        from src.utils.utils_dict import safe_update

        config = {"a": 1}
        result = safe_update(config, "b", "new", "test", assert_key_exists=False)
        self.assertTrue(result)
        self.assertEqual(config, {"a": 1, "b": "new"})

    def test_type_mismatch_raises(self):
        """类型不一致时 assert"""
        from src.utils.utils_dict import safe_update

        config = {"a": 1}
        with self.assertRaises(AssertionError):
            safe_update(config, "a", "string", "test")


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


if __name__ == "__main__":
    unittest.main()
