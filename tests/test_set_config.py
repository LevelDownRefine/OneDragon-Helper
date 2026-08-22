"""
测试 set_config.py 中的子脚本 config 读写基础设施。

覆盖函数：
  - _CONFIGS（子类路径声明完整性）
  - _get_script_root_dir
  - get_config_path
  - load_config
  - save_config（mock 文件写入，不真正写回脚本 config）
"""

import json
import os
import tempfile
import unittest
from unittest.mock import mock_open, patch

import yaml

from src.config import set_config, subscript
from src.utils import safe_path_join


class TestConfigRelPaths(unittest.TestCase):
    """测试 ScriptConfig 子类路径声明完整性（_CONFIGS 注册表自动收集）"""

    def test_configs_registry_covers_all_scripts(self):
        """_CONFIGS 覆盖全部 7 个已适配脚本（进程名）"""
        self.assertEqual(
            set(set_config._CONFIGS.keys()),
            {
                "ok-ww",
                "BetterGI",
                "ok-ef",
                "OneDragon-Launcher",
                "March7th-Assistant",
                "ok-nte",
                "MAA",
            },
        )

    def test_every_subclass_has_config_rel_path(self):
        """每个注册子类都声明了非空 _config_rel_path"""
        for name, cls in set_config._CONFIGS.items():
            self.assertIsInstance(
                cls._config_rel_path, str, f"{name} 的 _config_rel_path 不是字符串"
            )
            self.assertTrue(
                len(cls._config_rel_path) > 0, f"{name} 的 _config_rel_path 为空"
            )

    def test_game_config_rel_path_covers_all(self):
        """全部 7 个脚本都声明了 _game_path_keys 与 _game_config_rel_path"""
        for name, cls in set_config._CONFIGS.items():
            self.assertTrue(cls._game_path_keys, f"{name} 缺少 _game_path_keys")
            self.assertTrue(
                cls._game_config_rel_path, f"{name} 缺少 _game_config_rel_path"
            )

    def test_template_rel_path_only_for_template_scripts(self):
        """模板路径只覆盖 5 个走模板初始化的脚本"""
        with_template = {
            name for name, cls in set_config._CONFIGS.items() if cls._template_rel_path
        }
        self.assertEqual(
            with_template,
            {"BetterGI", "OneDragon-Launcher", "MAA", "March7th-Assistant", "ok-ef"},
        )

    def test_weekly_task_name_requires_weekly_write(self):
        """声明 _weekly_task_name 的子类必须在 _write_weekly 或 set_weekly 中落实写入"""
        base = set_config.ScriptConfig
        for name, cls in set_config._CONFIGS.items():
            if cls._weekly_task_name:
                self.assertTrue(
                    cls._write_weekly is not base._write_weekly
                    or cls.set_weekly is not base.set_weekly,
                    f"{name} 声明了 _weekly_task_name 但既未实现 _write_weekly 也未覆写 set_weekly",
                )

    def test_register_rejects_weekly_without_write(self):
        """register 拒绝：声明 _weekly_task_name 但沿用基类 _write_weekly 的子类"""
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
        for name, cls in set_config._CONFIGS.items():
            ext = os.path.splitext(cls._config_rel_path)[1].lower()
            self.assertIn(
                ext, valid_exts, f"{name} 的 config 扩展名 {ext} 不在支持范围内"
            )


class TestGetScriptRootDir(unittest.TestCase):
    """测试 _get_script_root_dir"""

    def test_returns_dirname_of_script_path(self):
        """应返回 script_path 的父目录"""
        fake_path = os.path.join("/fake", "ok-ww", "ok-ww.exe")
        fake_config = {
            "script_list": [
                {"display_name": "鸣潮", "script_path": fake_path},
            ]
        }
        # _get_script_root_dir 内部会统一为正斜杠，期望值也要一致
        expected_root = os.path.dirname(fake_path.replace("\\", "/"))
        with (
            patch.object(subscript, "_load_config_yml", return_value=fake_config),
            patch("os.path.exists", return_value=True),
        ):
            root = subscript._get_script_root_dir("ok-ww")
        self.assertEqual(root, expected_root)

    def test_handles_windows_path_on_any_platform(self):
        """应正确处理 Windows 风格路径（反斜杠），即使在 Linux 上"""
        fake_config = {
            "script_list": [
                {
                    "display_name": "鸣潮",
                    "script_path": r"C:\Users\test\ok-ww\ok-ww.exe",
                },
            ]
        }
        with (
            patch.object(subscript, "_load_config_yml", return_value=fake_config),
            patch("os.path.exists", return_value=True),
        ):
            root = subscript._get_script_root_dir("ok-ww")
        self.assertEqual(root, "C:/Users/test/ok-ww")

    def test_raises_for_unknown_script(self):
        """未在 config.yml 中的脚本应触发 AssertionError"""
        fake_config = {"script_list": []}
        with (
            patch.object(subscript, "_load_config_yml", return_value=fake_config),
            self.assertRaises(AssertionError),
        ):
            subscript._get_script_root_dir("none")

    def test_raises_for_empty_script_path(self):
        """script_path 为空时应触发 AssertionError"""
        fake_config = {
            "script_list": [
                {"display_name": "空路径", "script_path": ""},
            ]
        }
        with (
            patch.object(subscript, "_load_config_yml", return_value=fake_config),
            self.assertRaises(AssertionError),
        ):
            subscript._get_script_root_dir("empty")


class TestGetConfigPath(unittest.TestCase):
    """测试 get_config_path"""

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
            patch.object(subscript, "_load_config_yml", return_value=fake_config),
            patch("os.path.exists", return_value=True),
        ):
            path = subscript.get_config_path("ok-ww", rel)

        # get_config_path 内部用 safe_path_join，会归一化为绝对路径（Windows 为反斜杠），
        # 故 expected 需用同一归一化方式，避免分隔符不一致导致断言失败。
        expected = safe_path_join("C:/fake/ok-ww", rel)
        self.assertEqual(path, expected)

    def test_raises_for_unknown_script(self):
        """config.yml 中无此脚本应触发 AssertionError"""
        with (
            patch.object(
                subscript, "_load_config_yml", return_value={"script_list": []}
            ),
            self.assertRaises(AssertionError),
        ):
            subscript.get_config_path("none", "whatever.json")

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
                subscript,
                "_load_config_yml",
                return_value={"script_list": fake_script_list},
            ),
            patch("os.path.exists", return_value=True),
        ):
            for name in scripts:
                rel = set_config._CONFIGS[name]._config_rel_path
                path = subscript.get_config_path(name, rel)
                self.assertIsNotNone(path, f"{name} 路径推导失败")
                # 路径中应包含相对路径的各段（不依赖具体分隔符）
                rel_parts = rel.split("/")
                for part in rel_parts:
                    self.assertIn(
                        part, path, f"{name} 路径缺少相对路径段 '{part}': {path}"
                    )


class TestLoadConfig(unittest.TestCase):
    """测试 load_config"""

    def test_load_json_config(self):
        """应正确解析 JSON 格式的 config"""
        fake_data = {"key": "value", "nested": {"a": 1}}
        fake_path = r"C:\fake\script\config.json"

        with (
            patch.object(subscript, "get_config_path", return_value=fake_path),
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=json.dumps(fake_data))),
        ):
            result = subscript.load_config("ok-ww", "DailyTask.json")

        self.assertEqual(result, fake_data)

    def test_load_yaml_config(self):
        """应正确解析 YAML 格式的 config"""
        fake_data = {"key": "value", "list": [1, 2, 3]}
        fake_path = r"C:\fake\script\config.yaml"
        yaml_str = yaml.dump(fake_data, allow_unicode=True)

        with (
            patch.object(subscript, "get_config_path", return_value=fake_path),
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=yaml_str)),
        ):
            result = subscript.load_config("OneDragon-Launcher", "charge_plan.yml")

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
            rel = set_config._CONFIGS[name]._config_rel_path
            ext = os.path.splitext(rel)[1].lower()
            fake_data = {"test_key": "test_value"}
            if ext == ".json":
                file_content = json.dumps(fake_data, ensure_ascii=False)
            else:
                file_content = yaml.dump(fake_data, allow_unicode=True)

            with (
                patch.object(
                    subscript, "_load_config_yml", return_value=fake_config_yml
                ),
                patch("os.path.exists", return_value=True),
                patch("builtins.open", mock_open(read_data=file_content)),
            ):
                result = subscript.load_config(name, rel)

            self.assertIsNotNone(result, f"{name} config 读取失败")
            self.assertEqual(result, fake_data, f"{name} config 读取内容不匹配")


class TestSaveConfig(unittest.TestCase):
    """测试 save_config —— 全部 mock，不真正写回脚本 config"""

    def test_save_json_config_does_not_write_real_file(self):
        """save JSON 时不应写入真实 config 文件"""
        fake_path = r"C:\fake\script\config.json"
        data = {"Which to Farm": "Tacet"}

        m = mock_open()
        with (
            patch.object(subscript, "get_config_path", return_value=fake_path),
            patch("builtins.open", m),
        ):
            result = subscript.save_config("ok-ww", "DailyTask.json", data)

        self.assertIsNone(result)
        m.assert_called_once_with(fake_path, "w", encoding="utf-8")
        # 验证写入的内容是正确的 JSON
        handle = m()
        written = "".join(call.args[0] for call in handle.write.call_args_list)
        self.assertEqual(json.loads(written), data)

    def test_save_yaml_config_does_not_write_real_file(self):
        """save YAML 时不应写入真实 config 文件"""
        fake_path = r"C:\fake\script\charge_plan.yml"
        data = {"plan_list": [{"category_name": "test"}]}

        m = mock_open()
        with (
            patch.object(subscript, "get_config_path", return_value=fake_path),
            patch("builtins.open", m),
        ):
            result = subscript.save_config(
                "OneDragon-Launcher", "charge_plan.yml", data
            )

        self.assertIsNone(result)
        m.assert_called_once_with(fake_path, "w", encoding="utf-8")
        # 验证写入的内容是有效的 YAML
        handle = m()
        written = "".join(call.args[0] for call in handle.write.call_args_list)
        self.assertEqual(yaml.safe_load(written), data)

    def test_save_raises_when_path_is_none(self):
        """get_config_path 返回 None 时应抛出异常"""
        with (
            patch.object(subscript, "get_config_path", return_value=None),
            self.assertRaises((TypeError, AssertionError)),
        ):
            subscript.save_config("none", "whatever.json", {"key": "val"})

    def test_save_and_reload_roundtrip_json(self):
        """JSON 数据 save 后 load 回来应一致（用 tempdir 替代真实路径）"""
        data = {"test_key": "test_value", "num": 42}

        with tempfile.TemporaryDirectory() as tmp:
            fake_path = os.path.join(tmp, "config.json")
            with patch.object(subscript, "get_config_path", return_value=fake_path):
                # save
                ok = subscript.save_config("ok-ww", "DailyTask.json", data)
                self.assertIsNone(ok)
                # load
                loaded = subscript.load_config("ok-ww", "DailyTask.json")
                self.assertEqual(loaded, data)

    def test_save_and_reload_roundtrip_yaml(self):
        """YAML 数据 save 后 load 回来应一致（用 tempdir 替代真实路径）"""
        data = {"plan_list": [{"category_name": "模拟"}], "enabled": True}

        with tempfile.TemporaryDirectory() as tmp:
            fake_path = os.path.join(tmp, "config.yaml")
            with patch.object(subscript, "get_config_path", return_value=fake_path):
                # save
                ok = subscript.save_config(
                    "OneDragon-Launcher", "charge_plan.yml", data
                )
                self.assertIsNone(ok)
                # load
                loaded = subscript.load_config("OneDragon-Launcher", "charge_plan.yml")
                self.assertEqual(loaded, data)


class TestGenshinSetDungeon(unittest.TestCase):
    """测试 GenshinConfig.set_dungeon：目录→副本两级组织，DomainName 存副本名"""

    def setUp(self):
        from src.config.set_config import GenshinConfig

        self.config = GenshinConfig.__new__(GenshinConfig)
        self.config.display_name = "原神"
        self.config._task_key = "DomainName"
        self.config._enabled = True
        self.config._config_data = {"DomainName": "旧副本", "TaskEnabledList": []}
        self.config._verify_saved = lambda *a: None
        # 统一注入 mock IO：load 返回内存态，save 不落盘
        self.mock_save = self.enterContext(
            patch("src.config.set_config.save_config", return_value=None)
        )
        self.enterContext(
            patch(
                "src.config.set_config.load_config",
                side_effect=lambda *a: self.config._config_data,
            )
        )

    def test_has_sequence_writes_secondary_name(self):
        """有二级（目录 → 副本）时 DomainName 写入二级副本名"""
        self.config.set_dungeon("1", "霜凝的机枢")
        self.assertEqual(self.config._config_data["DomainName"], "霜凝的机枢")

    def test_no_sequence_writes_dungeon_name(self):
        """无二级（兼容旧单层配置）时 DomainName 写入一级名"""
        self.config.set_dungeon("山风的荆冕")
        self.assertEqual(self.config._config_data["DomainName"], "山风的荆冕")

    def test_same_value_no_save(self):
        """DomainName 未变化时不落盘"""
        self.config._config_data["DomainName"] = "霜凝的机枢"
        self.config.set_dungeon("1", "霜凝的机枢")
        self.mock_save.assert_not_called()


class TestSafeUpdate(unittest.TestCase):
    """测试 safe_update"""

    def test_update_changes_value(self):
        """值不同时更新并返回 True"""
        from src.config.set_config import safe_update

        config = {"key": "old"}
        result = safe_update(config, "key", "new", "test")
        self.assertTrue(result)
        self.assertEqual(config["key"], "new")

    def test_no_change_when_same_value(self):
        """值相同时不更新并返回 False"""
        from src.config.set_config import safe_update

        config = {"key": "same"}
        result = safe_update(config, "key", "same", "test")
        self.assertFalse(result)
        self.assertEqual(config["key"], "same")

    def test_key_not_exists_raises(self):
        """key 不存在时 assert（默认）"""
        from src.config.set_config import safe_update

        config = {}
        with self.assertRaises(AssertionError):
            safe_update(config, "missing", "value", "test")

    def test_key_not_exists_adds_with_flag(self):
        """assert_key_exists=False 时允许添加新 key"""
        from src.config.set_config import safe_update

        config = {"a": 1}
        result = safe_update(config, "b", "new", "test", assert_key_exists=False)
        self.assertTrue(result)
        self.assertEqual(config, {"a": 1, "b": "new"})

    def test_type_mismatch_raises(self):
        """类型不一致时 assert"""
        from src.config.set_config import safe_update

        config = {"a": 1}
        with self.assertRaises(AssertionError):
            safe_update(config, "a", "string", "test")


class TestConfirmSave(unittest.TestCase):
    """测试 _confirm_save：类属性回调经类访问调用，避免实例描述符绑定多传 self"""

    def setUp(self):
        from src.config.set_config import ScriptConfig

        self.original = ScriptConfig.confirm_before_save
        self.addCleanup(self._restore_callback)
        self.original_enabled = ScriptConfig._enabled
        self.addCleanup(self._restore_enabled)

    def _restore_callback(self):
        from src.config.set_config import ScriptConfig

        ScriptConfig.confirm_before_save = self.original

    def _restore_enabled(self):
        from src.config.set_config import ScriptConfig

        ScriptConfig._enabled = self.original_enabled

    def _make_config(self):
        from src.config.set_config import ScriptConfig

        config = ScriptConfig()
        config.display_name = "测试"
        return config

    def test_no_callback_defaults_to_true(self):
        """未注入回调时默认放行"""
        config = self._make_config()
        with patch.object(type(config), "confirm_before_save", None):
            self.assertTrue(config._confirm_save())
            self.assertTrue(config._enabled)

    def test_callback_called_with_display_name(self):
        """注入普通函数回调时只传 display_name（回归：曾因描述符绑定多传 self 报 TypeError）"""
        from src.config.set_config import ScriptConfig

        calls = []

        def callback(display_name: str) -> bool:
            calls.append(display_name)
            return False

        ScriptConfig.confirm_before_save = callback
        config = self._make_config()
        config.display_name = "终末地"
        result = config._confirm_save()
        self.assertFalse(result)
        self.assertEqual(calls, ["终末地"])

    def test_accept_keeps_enabled(self):
        """回调返回 True（用户确认保存）时不改动 enabled"""
        from src.config.set_config import ScriptConfig

        ScriptConfig.confirm_before_save = lambda name: True
        config = self._make_config()
        self.assertTrue(config._confirm_save())
        self.assertTrue(config._enabled)

    def test_reject_disables(self):
        """回调返回 False（用户拒绝）时 enabled 置 False，_save 跳过"""
        from src.config.set_config import ScriptConfig

        ScriptConfig.confirm_before_save = lambda name: False
        config = self._make_config()
        self.assertFalse(config._confirm_save())
        self.assertFalse(config._enabled)

        with (
            patch.object(
                type(config), "_verify_saved", side_effect=AssertionError("不应落盘")
            ) as mock_verify,
            patch("src.config.set_config.save_config") as mock_save,
        ):
            config._save({})
        mock_save.assert_not_called()
        mock_verify.assert_not_called()

    def test_rejected_instance_skips_set_dungeon(self):
        """enabled=False 时 set_dungeon 整体短路：不 _load、不 _update_task、不落盘"""
        from src.config.set_config import ScriptConfig

        ScriptConfig.confirm_before_save = lambda name: False
        config = self._make_config()
        self.assertFalse(config._confirm_save())

        with (
            patch.object(
                type(config), "_load", side_effect=AssertionError("不应 _load")
            ),
            patch.object(
                type(config),
                "_update_task",
                side_effect=AssertionError("不应 _update_task"),
            ),
            patch(
                "src.config.set_config.save_config",
                side_effect=AssertionError("不应落盘"),
            ),
        ):
            config.set_dungeon("武陵城")

    def test_new_instance_defaults_enabled(self):
        """每次新建实例 _enabled 默认为 True（类初始化重置）"""
        config = self._make_config()
        self.assertTrue(config._enabled)
        config._enabled = False
        self.assertFalse(config._enabled)
        # 新实例不受旧实例影响
        self.assertTrue(self._make_config()._enabled)


class TestIsAdapted(unittest.TestCase):
    """is_adapted：脚本是否已注册副本配置适配（GUI 任务卡显隐依据）。"""

    def test_registered_script_true(self):
        """已注册适配的脚本（如 ok-ww 鸣潮）→ True"""
        self.assertTrue(set_config.is_adapted("ok-ww"))

    def test_unregistered_script_false(self):
        """未注册适配的脚本（任意未知标识）→ False，不抛异常"""
        self.assertFalse(set_config.is_adapted("不存在的脚本"))


if __name__ == "__main__":
    unittest.main()
