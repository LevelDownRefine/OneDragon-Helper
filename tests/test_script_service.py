"""测试 src/service/script_service.py：单脚本配置读写与 weekly_timeouts 同步。"""

import os
import tempfile
import unittest
from unittest.mock import patch

import yaml

from src.service.script_service import ScriptService


class ScriptServiceTestBase(unittest.TestCase):
    """用临时 config.yml / weekly_timeouts.yml 隔离真实文件。"""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.config_path = os.path.join(self.tmp_dir.name, "config.yml")
        self.weekly_path = os.path.join(self.tmp_dir.name, "weekly_timeouts.yml")
        self.weekly_list_path = os.path.join(self.tmp_dir.name, "weekly_list.yml")
        self.weekly_start_path = os.path.join(self.tmp_dir.name, "weekly_start.yml")
        self._write_config(
            {"script_list": [{"display_name": "原神", "script_path": "C:/a.exe"}]}
        )
        # weekly_timeouts.yml 随包发布、必存在，默认建一个空 {} 文件，
        # 贴近真实部署；缺失→{} 的兜底已移除（改 assert 暴露）。
        self._write_weekly({})
        # weekly_start.yml 同样随包发布、必存在，默认空 {}。
        self._write_weekly_start({})
        patchers = [
            patch(
                "src.service.script_service.require_config_yml_path",
                return_value=self.config_path,
            ),
            patch(
                "src.service.script_service.get_weekly_timeouts_yml_path_under_root",
                return_value=self.weekly_path,
            ),
            patch(
                "src.service.script_service.get_weekly_list_yml_path_under_root",
                return_value=self.weekly_list_path,
            ),
            patch(
                "src.service.script_service.get_weekly_start_yml_path_under_root",
                return_value=self.weekly_start_path,
            ),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)

    def _write_config(self, data):
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, sort_keys=False)

    def _write_weekly(self, data):
        with open(self.weekly_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, sort_keys=False)

    def _write_weekly_start(self, data):
        with open(self.weekly_start_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, sort_keys=False)

    def _read_config(self):
        with open(self.config_path, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _read_weekly(self):
        if not os.path.exists(self.weekly_path):
            return None
        with open(self.weekly_path, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _read_weekly_start(self):
        if not os.path.exists(self.weekly_start_path):
            return None
        with open(self.weekly_start_path, encoding="utf-8") as f:
            return yaml.safe_load(f)


class TestGetScript(ScriptServiceTestBase):
    def test_get_existing_script(self):
        s = ScriptService().get_script("a")
        self.assertEqual(s, {"display_name": "原神", "script_path": "C:/a.exe"})

    def test_get_missing_script_returns_none(self):
        self.assertIsNone(ScriptService().get_script("none"))


class TestSaveWeekly(ScriptServiceTestBase):
    """save_weekly：保存 7 格超时到 weekly_timeouts.yml。"""

    def test_save_weekly_writes_entry(self):
        ScriptService().save_weekly("a", [60] * 7)
        self.assertEqual(self._read_weekly()["a"], [60] * 7)

    def test_none_timeouts_resolved_to_default(self):
        """空输入（None）→ 转默认超时。"""
        ScriptService().save_weekly("a", [None, 60, None, 60, 60, 60, 60])
        self.assertEqual(
            self._read_weekly()["a"],
            [3600, 60, 3600, 60, 60, 60, 60],
        )

    def test_low_timeouts_preserved(self):
        """低于 10 的输入原样保留（由 chain_gen 按「<10 当天不运行」跳过，不再 clamp）。"""
        ScriptService().save_weekly("a", [5, 0, 60, 60, 60, 60, 60])
        self.assertEqual(
            self._read_weekly()["a"],
            [5, 0, 60, 60, 60, 60, 60],
        )


class TestRenameWeeklyInTimeouts(ScriptServiceTestBase):
    """rename_weekly_in_timeouts：改名时迁移 weekly_timeouts.yml 条目。"""

    def test_rename_migrates_entry(self):
        with open(self.weekly_path, "w", encoding="utf-8") as f:
            yaml.dump({"a": [1] * 7}, f, allow_unicode=True)
        ScriptService().rename_weekly_in_timeouts("a", "b")
        weekly = self._read_weekly()
        self.assertNotIn("a", weekly)
        self.assertEqual(weekly["b"], [1] * 7)

    def test_same_name_noop(self):
        """同名的 rename 为 no-op，不影响已有 weekly 条目。"""
        with open(self.weekly_path, "w", encoding="utf-8") as f:
            yaml.dump({"a": [60] * 7}, f, allow_unicode=True)
        ScriptService().rename_weekly_in_timeouts("a", "a")
        self.assertEqual(self._read_weekly()["a"], [60] * 7)

    def test_old_entry_missing_noop(self):
        """旧名无 weekly 条目 → no-op（不报错、不改文件，保持空 {}）。"""
        ScriptService().rename_weekly_in_timeouts("none", "b")
        self.assertEqual(self._read_weekly(), {})


class TestEnsureWeeklyEntry(ScriptServiceTestBase):
    def test_creates_default_entry(self):
        ScriptService().ensure_weekly_entry("a")
        self.assertEqual(self._read_weekly()["a"], [3600] * 7)

    def test_existing_entry_untouched(self):
        with open(self.weekly_path, "w", encoding="utf-8") as f:
            yaml.dump({"a": [60] * 7}, f, allow_unicode=True)
        ScriptService().ensure_weekly_entry("a")
        self.assertEqual(self._read_weekly()["a"], [60] * 7)


class TestWeeklyInputs(ScriptServiceTestBase):
    def test_missing_entry_uses_default(self):
        self.assertEqual(ScriptService().weekly_inputs("a"), [3600] * 7)

    def test_existing_entry_kept(self):
        with open(self.weekly_path, "w", encoding="utf-8") as f:
            yaml.dump({"a": [1, 2, 3, 4, 5, 6, 7]}, f, allow_unicode=True)
        self.assertEqual(ScriptService().weekly_inputs("a"), [1, 2, 3, 4, 5, 6, 7])

    def test_short_entry_padded_with_default(self):
        """不足 7 格 → 用默认超时补齐。"""
        with open(self.weekly_path, "w", encoding="utf-8") as f:
            yaml.dump({"a": [10, 20]}, f, allow_unicode=True)
        self.assertEqual(
            ScriptService().weekly_inputs("a"),
            [10, 20, 3600, 3600, 3600, 3600, 3600],
        )


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


class TestCheckWeekly(ScriptServiceTestBase):
    """check_weekly：weekly_timeouts.yml 与 config 脚本条目的一致性。"""

    def test_ok_when_aligned(self):
        """weekly 有 7 格条目且无孤儿 → status=ok。"""
        with open(self.weekly_path, "w", encoding="utf-8") as f:
            yaml.dump({"a": [3600] * 7}, f, allow_unicode=True)
        result = ScriptService().check_weekly()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["missing_or_short"], [])
        self.assertEqual(result["orphans"], [])

    def test_missing_entry_reported(self):
        """config 有脚本但 weekly 无条目 → 进 missing_or_short。"""
        result = ScriptService().check_weekly()
        self.assertEqual(result["status"], "inconsistent")
        self.assertEqual(result["missing_or_short"], ["a"])

    def test_orphan_key_reported(self):
        """weekly 有 config 已删除的 key → 进 orphans。"""
        with open(self.weekly_path, "w", encoding="utf-8") as f:
            yaml.dump({"a": [3600] * 7, "gone": [3600] * 7}, f, allow_unicode=True)
        result = ScriptService().check_weekly()
        self.assertEqual(result["status"], "inconsistent")
        self.assertEqual(result["orphans"], ["gone"])

    def test_missing_display_name_raises_assertion(self):
        """条目缺 display_name 属数据损坏：_load_config 入口抛 AssertionError。"""
        self._write_config({"script_list": [{"script_path": "C:/x.py"}]})
        with self.assertRaises(AssertionError):
            ScriptService().check_weekly()


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


class TestDeleteWeekly(ScriptServiceTestBase):
    """测试 ScriptService.delete_weekly：仅清理 weekly_timeouts.yml 孤儿（总 config 移除归 ChainService）。"""

    def test_delete_weekly_cleans_orphan(self):
        """删除后 weekly_timeouts.yml 中该脚本的孤儿条目被移除"""
        with open(self.weekly_path, "w", encoding="utf-8") as f:
            yaml.dump({"a": [100] * 7}, f, allow_unicode=True, sort_keys=False)
        ScriptService().delete_weekly("a")
        weekly = self._read_weekly()
        self.assertNotIn("a", weekly)
        self.assertEqual(weekly, {})

    def test_delete_weekly_keeps_others(self):
        """删除单个脚本不影响 weekly_timeouts.yml 中其它条目"""
        with open(self.weekly_path, "w", encoding="utf-8") as f:
            yaml.dump(
                {"a": [100] * 7, "mute": [120] * 7},
                f,
                allow_unicode=True,
                sort_keys=False,
            )
        ScriptService().delete_weekly("a")
        weekly = self._read_weekly()
        self.assertNotIn("a", weekly)
        self.assertEqual(weekly, {"mute": [120] * 7})

    def test_delete_weekly_noop_when_absent(self):
        """脚本无 weekly 条目时清理为 no-op（不报错，文件保持空 {}）"""
        ScriptService().delete_weekly("不存在")
        self.assertEqual(self._read_weekly(), {})


class TestSetWeeklyStart(unittest.TestCase):
    """set_weekly_start / get_weekly_start：读写独立文件 weekly_start.yml（不污染 weekly_list.yml）。"""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.weekly_start_path = os.path.join(self.tmp_dir.name, "weekly_start.yml")
        self.weekly_list_path = os.path.join(self.tmp_dir.name, "weekly_list.yml")
        # weekly_list.yml 必存在（_load_weekly_defs 断言），但本测试不依赖其内容。
        with open(self.weekly_list_path, "w", encoding="utf-8") as f:
            yaml.dump({}, f, allow_unicode=True)
        with open(self.weekly_start_path, "w", encoding="utf-8") as f:
            yaml.dump({}, f, allow_unicode=True)
        patchers = [
            patch(
                "src.service.script_service.get_weekly_start_yml_path_under_root",
                return_value=self.weekly_start_path,
            ),
            patch(
                "src.service.script_service.get_weekly_list_yml_path_under_root",
                return_value=self.weekly_list_path,
            ),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)

    def _read_start(self):
        with open(self.weekly_start_path, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def test_set_writes_to_weekly_start_file_only(self):
        """set_weekly_start 写入 weekly_start.yml，不污染 weekly_list.yml。"""
        ScriptService().set_weekly_start("a", 4)
        self.assertEqual(self._read_start(), {"a": 4})
        with open(self.weekly_list_path, encoding="utf-8") as f:
            self.assertEqual(yaml.safe_load(f), {})

    def test_get_returns_set_value(self):
        ScriptService().set_weekly_start("a", 3)
        self.assertEqual(ScriptService().get_weekly_start("a"), 3)
        self.assertIsNone(ScriptService().get_weekly_start("缺失"))

    def test_set_none_clears_entry(self):
        """start_day=None → 移除该脚本条目。"""
        ScriptService().set_weekly_start("a", 2)
        ScriptService().set_weekly_start("a", None)
        self.assertIsNone(ScriptService().get_weekly_start("a"))
        self.assertEqual(self._read_start(), {})

    def test_invalid_day_raises(self):
        for bad in (0, 8):
            with self.subTest(bad=bad), self.assertRaises(AssertionError):
                ScriptService().set_weekly_start("a", bad)


if __name__ == "__main__":
    unittest.main()
