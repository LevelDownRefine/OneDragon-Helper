"""
测试 set_config.py 中的子脚本 config 读写基础设施。

覆盖函数：
  - _CONFIG_REL_PATHS（数据完整性）
  - _get_script_root_dir
  - get_config_path
  - load_config
  - save_config（mock 文件写入，不真正写回脚本 config）
"""
import os
import json
import yaml
import tempfile
import unittest
from unittest.mock import patch, mock_open, MagicMock

from src.config import set_config
from src.config import subscript


class TestConfigRelPaths(unittest.TestCase):
    """测试 _CONFIG_REL_PATHS 数据完整性"""

    def test_all_scripts_have_rel_path(self):
        """每个已适配脚本都应在 _CONFIG_REL_PATHS 中有记录"""
        scripts = ["鸣潮", "原神", "终末地", "绝区零", "崩铁", "异环", "粥"]
        for name in scripts:
            self.assertIn(name, subscript._CONFIG_REL_PATHS,
                          f"{name} 缺少 config 相对路径")

    def test_rel_paths_are_strings(self):
        for name, rel in subscript._CONFIG_REL_PATHS.items():
            self.assertIsInstance(rel, str, f"{name} 的 rel path 不是字符串")
            self.assertTrue(len(rel) > 0, f"{name} 的 rel path 为空")

    def test_rel_paths_contain_extension(self):
        """每个相对路径应包含 .json 或 .yaml/.yml 扩展名"""
        valid_exts = ('.json', '.yaml', '.yml')
        for name, rel in subscript._CONFIG_REL_PATHS.items():
            ext = os.path.splitext(rel)[1].lower()
            self.assertIn(ext, valid_exts,
                          f"{name} 的 config 扩展名 {ext} 不在支持范围内")


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
        expected_root = os.path.dirname(fake_path.replace('\\', '/'))
        with patch.object(subscript, '_load_config_yml', return_value=fake_config), \
             patch('os.path.exists', return_value=True):
            root = subscript._get_script_root_dir("鸣潮")
        self.assertEqual(root, expected_root)

    def test_handles_windows_path_on_any_platform(self):
        """应正确处理 Windows 风格路径（反斜杠），即使在 Linux 上"""
        fake_config = {
            "script_list": [
                {"display_name": "鸣潮",
                 "script_path": r"C:\Users\test\ok-ww\ok-ww.exe"},
            ]
        }
        with patch.object(subscript, '_load_config_yml', return_value=fake_config), \
             patch('os.path.exists', return_value=True):
            root = subscript._get_script_root_dir("鸣潮")
        self.assertEqual(root, "C:/Users/test/ok-ww")

    def test_raises_for_unknown_script(self):
        """未在 config.yml 中的脚本应触发 AssertionError"""
        fake_config = {"script_list": []}
        with patch.object(subscript, '_load_config_yml', return_value=fake_config):
            with self.assertRaises(AssertionError):
                subscript._get_script_root_dir("不存在的脚本")

    def test_raises_for_empty_script_path(self):
        """script_path 为空时应触发 AssertionError"""
        fake_config = {
            "script_list": [
                {"display_name": "空路径", "script_path": ""},
            ]
        }
        with patch.object(subscript, '_load_config_yml', return_value=fake_config):
            with self.assertRaises(AssertionError):
                subscript._get_script_root_dir("空路径")


class TestGetConfigPath(unittest.TestCase):
    """测试 get_config_path"""

    def test_joins_root_and_rel(self):
        """应正确拼接脚本根目录和 config 相对路径"""
        # mock Windows 风格的 script_path，验证在任意平台上都能推导
        fake_config = {
            "script_list": [
                {"display_name": "鸣潮",
                 "script_path": r"C:\fake\ok-ww\ok-ww.exe"},
            ]
        }
        with patch.object(subscript, '_load_config_yml', return_value=fake_config), \
             patch('os.path.exists', return_value=True):
            path = subscript.get_config_path("鸣潮")

        expected = os.path.join("C:/fake/ok-ww",
                                subscript._CONFIG_REL_PATHS["鸣潮"])
        self.assertEqual(path, expected)

    def test_raises_for_unknown_script(self):
        """未在 _CONFIG_REL_PATHS 中的脚本应触发 AssertionError"""
        with patch.object(subscript, '_load_config_yml',
                          return_value={"script_list": []}):
            with self.assertRaises(AssertionError):
                subscript.get_config_path("不存在")

    def test_all_registered_scripts_resolve_with_mock_config(self):
        """对所有已注册脚本，用 mock 的 config.yml 验证路径推导成功
        （不依赖真实 config.yml，CI 也能跑）"""
        scripts = list(subscript._CONFIG_REL_PATHS.keys())
        # 构造 mock config：每个脚本都有一个假的 script_path
        fake_script_list = [
            {"display_name": name,
             "script_path": r"C:\fake\root\script.exe"}
            for name in scripts
        ]
        with patch.object(subscript, '_load_config_yml',
                          return_value={"script_list": fake_script_list}), \
             patch('os.path.exists', return_value=True):
            for name in scripts:
                path = subscript.get_config_path(name)
                self.assertIsNotNone(path, f"{name} 路径推导失败")
                # 路径中应包含相对路径的各段（不依赖具体分隔符）
                rel = subscript._CONFIG_REL_PATHS[name]
                rel_parts = rel.split("/")
                for part in rel_parts:
                    self.assertIn(part, path,
                                  f"{name} 路径缺少相对路径段 '{part}': {path}")


class TestLoadConfig(unittest.TestCase):
    """测试 load_config"""

    def test_load_json_config(self):
        """应正确解析 JSON 格式的 config"""
        fake_data = {"key": "value", "nested": {"a": 1}}
        fake_path = r"C:\fake\script\config.json"

        with patch.object(subscript, 'get_config_path', return_value=fake_path), \
             patch('os.path.exists', return_value=True), \
             patch('builtins.open', mock_open(read_data=json.dumps(fake_data))):
            result = subscript.load_config("鸣潮")

        self.assertEqual(result, fake_data)

    def test_load_yaml_config(self):
        """应正确解析 YAML 格式的 config"""
        fake_data = {"key": "value", "list": [1, 2, 3]}
        fake_path = r"C:\fake\script\config.yaml"
        yaml_str = yaml.dump(fake_data, allow_unicode=True)

        with patch.object(subscript, 'get_config_path', return_value=fake_path), \
             patch('os.path.exists', return_value=True), \
             patch('builtins.open', mock_open(read_data=yaml_str)):
            result = subscript.load_config("绝区零")

        self.assertEqual(result, fake_data)

    def test_load_all_registered_configs_with_mock(self):
        """对所有已注册脚本，用 mock config 文件验证读取逻辑
        （不依赖真实 config 文件，CI 也能跑）"""
        scripts = list(subscript._CONFIG_REL_PATHS.keys())
        # 构造 mock config.yml + mock 文件内容
        fake_script_list = [
            {"display_name": name,
             "script_path": r"C:\fake\root\script.exe"}
            for name in scripts
        ]
        fake_config_yml = {"script_list": fake_script_list}

        for name in scripts:
            rel = subscript._CONFIG_REL_PATHS[name]
            ext = os.path.splitext(rel)[1].lower()
            fake_data = {"test_key": "test_value"}
            if ext == '.json':
                file_content = json.dumps(fake_data, ensure_ascii=False)
            else:
                file_content = yaml.dump(fake_data, allow_unicode=True)

            with patch.object(subscript, '_load_config_yml',
                              return_value=fake_config_yml), \
                 patch('os.path.exists', return_value=True), \
                 patch('builtins.open', mock_open(read_data=file_content)):
                result = subscript.load_config(name)

            self.assertIsNotNone(result, f"{name} config 读取失败")
            self.assertEqual(result, fake_data,
                             f"{name} config 读取内容不匹配")


class TestSaveConfig(unittest.TestCase):
    """测试 save_config —— 全部 mock，不真正写回脚本 config"""

    def test_save_json_config_does_not_write_real_file(self):
        """save JSON 时不应写入真实 config 文件"""
        fake_path = r"C:\fake\script\config.json"
        data = {"Which to Farm": "Tacet"}

        m = mock_open()
        with patch.object(subscript, 'get_config_path', return_value=fake_path), \
             patch('builtins.open', m):
            result = subscript.save_config("鸣潮", data)

        self.assertIsNone(result)
        m.assert_called_once_with(fake_path, 'w', encoding='utf-8')
        # 验证写入的内容是正确的 JSON
        handle = m()
        written = ''.join(call.args[0] for call in handle.write.call_args_list)
        self.assertEqual(json.loads(written), data)

    def test_save_yaml_config_does_not_write_real_file(self):
        """save YAML 时不应写入真实 config 文件"""
        fake_path = r"C:\fake\script\charge_plan.yml"
        data = {"plan_list": [{"category_name": "test"}]}

        m = mock_open()
        with patch.object(subscript, 'get_config_path', return_value=fake_path), \
             patch('builtins.open', m):
            result = subscript.save_config("绝区零", data)

        self.assertIsNone(result)
        m.assert_called_once_with(fake_path, 'w', encoding='utf-8')
        # 验证写入的内容是有效的 YAML
        handle = m()
        written = ''.join(call.args[0] for call in handle.write.call_args_list)
        self.assertEqual(yaml.safe_load(written), data)

    def test_save_raises_when_path_is_none(self):
        """get_config_path 返回 None 时应抛出异常"""
        with patch.object(subscript, 'get_config_path', return_value=None):
            with self.assertRaises((TypeError, AssertionError)):
                subscript.save_config("不存在", {"key": "val"})

    def test_save_and_reload_roundtrip_json(self):
        """JSON 数据 save 后 load 回来应一致（用 tempdir 替代真实路径）"""
        data = {"test_key": "test_value", "num": 42}

        with tempfile.TemporaryDirectory() as tmp:
            fake_path = os.path.join(tmp, "config.json")
            with patch.object(subscript, 'get_config_path', return_value=fake_path):
                # save
                ok = subscript.save_config("鸣潮", data)
                self.assertIsNone(ok)
                # load
                loaded = subscript.load_config("鸣潮")
                self.assertEqual(loaded, data)

    def test_save_and_reload_roundtrip_yaml(self):
        """YAML 数据 save 后 load 回来应一致（用 tempdir 替代真实路径）"""
        data = {"plan_list": [{"category_name": "模拟"}], "enabled": True}

        with tempfile.TemporaryDirectory() as tmp:
            fake_path = os.path.join(tmp, "config.yaml")
            with patch.object(subscript, 'get_config_path', return_value=fake_path):
                # save
                ok = subscript.save_config("绝区零", data)
                self.assertIsNone(ok)
                # load
                loaded = subscript.load_config("绝区零")
                self.assertEqual(loaded, data)


if __name__ == "__main__":
    unittest.main()
