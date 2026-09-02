"""测试 src/service/script_service.py：config.yml 读写与单脚本条目查询。

周常运行期参数（weekly_start.yml / weekly_timeouts.yml）的读写已抽为 src/utils_weekly.py 模块函数，
其测试见 test_utils_weekly.py；本文件只测 config.yml 与单脚本查询/路径解析。
"""

import os
import tempfile
import unittest
from unittest.mock import patch

from src.service.script_service import ScriptService
from src.utils_yaml import dump_yaml_file, load_yaml


class ScriptServiceTestBase(unittest.TestCase):
    """用临时 config.yml 隔离真实文件（weekly 路径已归 WeeklyService 自管）。"""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.config_path = os.path.join(self.tmp_dir.name, "config.yml")
        self.weekly_list_path = os.path.join(self.tmp_dir.name, "weekly_list.yml")
        self._write_config(
            {"script_list": [{"display_name": "原神", "script_path": "C:/a.exe"}]}
        )
        patchers = [
            patch(
                "src.service.script_service.require_config_yml_path",
                return_value=self.config_path,
            ),
            patch(
                "src.service.dungeon_service.get_weekly_list_yml_path_under_root",
                return_value=self.weekly_list_path,
            ),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)

    def _write_config(self, data):
        dump_yaml_file(self.config_path, data)

    def _read_config(self):
        return load_yaml(self.config_path)


class TestGetScript(ScriptServiceTestBase):
    def test_get_existing_script(self):
        s = ScriptService().get_script("a")
        self.assertEqual(s, {"display_name": "原神", "script_path": "C:/a.exe"})

    def test_get_missing_script_returns_none(self):
        self.assertIsNone(ScriptService().get_script("none"))


class TestBuildScriptEntry(unittest.TestCase):
    """build_script_entry：文件名去重命名 + 类型推断 + 默认字段。"""

    def test_python_type_inferred(self):
        entry = ScriptService().build_script_entry("C:/foo/bar.py", set())
        self.assertEqual(entry["script_type"], "python")
        self.assertEqual(entry["display_name"], "bar")

    def test_external_type_inferred(self):
        entry = ScriptService().build_script_entry("C:/foo/bar.exe", set())
        self.assertEqual(entry["script_type"], "external")
        self.assertEqual(entry["display_name"], "bar")

    def test_name_deduplicated_with_suffix(self):
        entry = ScriptService().build_script_entry("C:/foo/bar.exe", {"bar"})
        self.assertEqual(entry["display_name"], "bar_1")

    def test_name_dedup_keeps_incrementing(self):
        entry = ScriptService().build_script_entry("C:/foo/bar.exe", {"bar", "bar_1"})
        self.assertEqual(entry["display_name"], "bar_2")


class TestConfigFilePath(ScriptServiceTestBase):
    """测试 ScriptService.config_file_path：python/external 分支与缺失处理。"""

    def _setup_script(self, display_name, script_type, script_path):
        self._write_config(
            {
                "script_list": [
                    {
                        "display_name": display_name,
                        "script_type": script_type,
                        "script_path": script_path,
                    }
                ]
            }
        )

    def test_missing_script_returns_error(self):
        self._setup_script("原神", "external", "C:/a.exe")
        path, error = ScriptService().config_file_path("none")
        self.assertIsNone(path)
        self.assertIn("找不到脚本", error)

    def test_external_adapted_returns_config_path(self):
        self._setup_script("原神", "external", "C:/a.exe")
        with (
            patch(
                "src.service.script_service.get_config_path",
                return_value="C:/config/DailyTask.json",
            ),
            patch("src.service.script_service.os.path.isfile", return_value=True),
        ):
            path, error = ScriptService().config_file_path("a")
        self.assertEqual(path, "C:/config/DailyTask.json")
        self.assertIsNone(error)

    def test_external_unadapted_returns_error(self):
        self._setup_script("原神", "external", "C:/a.exe")
        with patch(
            "src.service.script_service.get_config_path",
            side_effect=AssertionError("未适配脚本: 原神"),
        ):
            path, error = ScriptService().config_file_path("a")
        self.assertIsNone(path)
        self.assertIn("暂未适配", error)

    def test_python_resolved_returns_py_path(self):
        self._setup_script("静音", "python", "C:/proj/mute.py")
        with (
            patch(
                "src.service.script_service.resolve_script_path",
                return_value="C:/proj/mute.py",
            ),
            patch("src.service.script_service.os.path.isfile", return_value=True),
        ):
            path, error = ScriptService().config_file_path("静音")
        self.assertEqual(path, "C:/proj/mute.py")
        self.assertIsNone(error)

    def test_python_missing_file_returns_error(self):
        self._setup_script("静音", "python", "C:/nope/mute.py")
        with (
            patch(
                "src.service.script_service.resolve_script_path",
                return_value="C:/nope/mute.py",
            ),
            patch("src.service.script_service.os.path.isfile", return_value=False),
        ):
            path, error = ScriptService().config_file_path("静音")
        self.assertIsNone(path)
        self.assertIn("找不到脚本文件", error)


class TestLoadSaveConfig(unittest.TestCase):
    """config.yml 读写（ScriptService 实现）：结构断言（用临时文件，不碰真实 config）"""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.config_path = os.path.join(self.tmp_dir.name, "config.yml")

    def test_load_config_reads_yaml(self):
        fake_data = {
            "script_list": [
                {"display_name": "测试", "script_path": "C:/x.exe"},
            ]
        }
        dump_yaml_file(self.config_path, fake_data)
        with patch(
            "src.service.script_service.require_config_yml_path",
            return_value=self.config_path,
        ):
            data = ScriptService().load_config()
        self.assertEqual(data, fake_data)

    def test_load_config_asserts_script_list(self):
        dump_yaml_file(self.config_path, {"a": 1})
        with (
            patch(
                "src.service.script_service.require_config_yml_path",
                return_value=self.config_path,
            ),
            self.assertRaises(AssertionError),
        ):
            ScriptService().load_config()

    def test_save_config_writes_yaml(self):
        with patch(
            "src.service.script_service.get_config_yml_path_under_root",
            return_value=self.config_path,
        ):
            ScriptService().save_config({"script_list": [{"display_name": "测试"}]})
        saved = load_yaml(self.config_path)
        self.assertEqual(saved["script_list"][0]["display_name"], "测试")

    def test_save_config_asserts_script_list(self):
        with self.assertRaises(AssertionError):
            ScriptService().save_config({"a": 1})


class TestAddRemoveScript(unittest.TestCase):
    """add_script / remove_script：操作 config.yml 并协作 WeeklyService 同步 weekly。"""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.config_path = os.path.join(self.tmp_dir.name, "config.yml")
        dump_yaml_file(
            self.config_path,
            {"script_list": [{"display_name": "原神", "script_path": "C:/a.exe"}]},
        )

    def _read(self):
        return load_yaml(self.config_path)

    def test_add_script_appends(self):
        """add_script 在 script_list 末尾追加条目、落盘，并协作 WeeklyService 建默认条目。"""
        with (
            patch(
                "src.service.script_service.require_config_yml_path",
                return_value=self.config_path,
            ),
            patch(
                "src.service.script_service.get_config_yml_path_under_root",
                return_value=self.config_path,
            ),
            patch("src.service.script_service.ensure_weekly_entry") as mock_ensure,
            patch("src.service.script_service.init_config") as mock_init,
        ):
            ScriptService().add_script(
                {"display_name": "鸣潮", "script_path": "C:/b.exe"}
            )
        names = [s["display_name"] for s in self._read()["script_list"]]
        self.assertEqual(names, ["原神", "鸣潮"])
        mock_ensure.assert_called_once_with("b")
        mock_init.assert_called_once_with("b")

    def test_remove_script_removes(self):
        """remove_script 从 script_list 移除指定进程条目、落盘，并协作清理 weekly 孤儿。"""
        with (
            patch(
                "src.service.script_service.require_config_yml_path",
                return_value=self.config_path,
            ),
            patch(
                "src.service.script_service.get_config_yml_path_under_root",
                return_value=self.config_path,
            ),
            patch("src.service.script_service.delete_weekly") as mock_del,
        ):
            ScriptService().remove_script("a")
        self.assertEqual(self._read()["script_list"], [])
        mock_del.assert_called_once_with("a")

    def test_remove_script_missing_raises(self):
        """remove_script 移除不存在的脚本属非法调用：assert 表达不该发生"""
        with (
            patch(
                "src.service.script_service.require_config_yml_path",
                return_value=self.config_path,
            ),
            patch(
                "src.service.script_service.get_config_yml_path_under_root",
                return_value=self.config_path,
            ),
            self.assertRaises(AssertionError),
        ):
            ScriptService().remove_script("不存在")


if __name__ == "__main__":
    unittest.main()
