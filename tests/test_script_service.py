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
        self._write_config(
            {"script_list": [{"display_name": "原神", "script_path": "C:/a.exe"}]}
        )
        patchers = [
            patch(
                "src.service.script_service.require_config_yml_path",
                return_value=self.config_path,
            ),
            patch(
                "src.service.script_service.get_config_yml_path_under_root",
                return_value=self.config_path,
            ),
            patch(
                "src.service.script_service.get_weekly_timeouts_yml_path_under_root",
                return_value=self.weekly_path,
            ),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)

    def _write_config(self, data):
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, sort_keys=False)

    def _read_config(self):
        with open(self.config_path, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _read_weekly(self):
        if not os.path.exists(self.weekly_path):
            return None
        with open(self.weekly_path, encoding="utf-8") as f:
            return yaml.safe_load(f)


class TestGetScript(ScriptServiceTestBase):
    def test_get_existing_script(self):
        s = ScriptService().get_script("原神")
        self.assertEqual(s, {"display_name": "原神", "script_path": "C:/a.exe"})

    def test_get_missing_script_returns_none(self):
        self.assertIsNone(ScriptService().get_script("不存在"))


class TestUpdateScript(ScriptServiceTestBase):
    def test_update_fields(self):
        ScriptService().update_script(
            "原神", "原神", {"script_path": "C:/new.exe", "block": False}
        )
        data = self._read_config()
        target = data["script_list"][0]
        self.assertEqual(target["script_path"], "C:/new.exe")
        self.assertFalse(target["block"])
        self.assertEqual(target["display_name"], "原神")

    def test_rename_migrates_weekly(self):
        with open(self.weekly_path, "w", encoding="utf-8") as f:
            yaml.dump({"原神": [1] * 7}, f, allow_unicode=True)
        ScriptService().update_script("原神", "原神2", {"script_path": "C:/a.exe"})
        weekly = self._read_weekly()
        self.assertNotIn("原神", weekly)
        self.assertEqual(weekly["原神2"], [1] * 7)
        data = self._read_config()
        self.assertEqual(data["script_list"][0]["display_name"], "原神2")

    def test_update_with_weekly_timeouts(self):
        ScriptService().update_script(
            "原神", "原神", {"script_path": "C:/a.exe"}, weekly_timeouts=[60] * 7
        )
        self.assertEqual(self._read_weekly()["原神"], [60] * 7)

    def test_update_none_timeouts_resolved_to_default(self):
        """空输入（None）→ 落盘前转默认超时。"""
        ScriptService().update_script(
            "原神",
            "原神",
            {"script_path": "C:/a.exe"},
            weekly_timeouts=[None, 60, None, 60, 60, 60, 60],
        )
        self.assertEqual(self._read_weekly()["原神"], [3600, 60, 3600, 60, 60, 60, 60])

    def test_update_low_timeouts_clamped_to_10(self):
        """低于 10 的输入 → clamp 到 10。"""
        ScriptService().update_script(
            "原神",
            "原神",
            {"script_path": "C:/a.exe"},
            weekly_timeouts=[5, 0, 60, 60, 60, 60, 60],
        )
        self.assertEqual(self._read_weekly()["原神"], [10, 10, 60, 60, 60, 60, 60])

    def test_update_missing_script_raises(self):
        with self.assertRaises(AssertionError):
            ScriptService().update_script("不存在", "不存在", {})

    def test_empty_new_name_raises(self):
        with self.assertRaises(AssertionError):
            ScriptService().update_script("原神", "", {})


class TestEnsureWeeklyEntry(ScriptServiceTestBase):
    def test_creates_default_entry(self):
        ScriptService().ensure_weekly_entry("原神")
        self.assertEqual(self._read_weekly()["原神"], [3600] * 7)

    def test_existing_entry_untouched(self):
        with open(self.weekly_path, "w", encoding="utf-8") as f:
            yaml.dump({"原神": [60] * 7}, f, allow_unicode=True)
        ScriptService().ensure_weekly_entry("原神")
        self.assertEqual(self._read_weekly()["原神"], [60] * 7)


class TestWeeklyInputs(ScriptServiceTestBase):
    def test_missing_entry_uses_default(self):
        self.assertEqual(ScriptService().weekly_inputs("原神"), [3600] * 7)

    def test_existing_entry_kept(self):
        with open(self.weekly_path, "w", encoding="utf-8") as f:
            yaml.dump({"原神": [1, 2, 3, 4, 5, 6, 7]}, f, allow_unicode=True)
        self.assertEqual(ScriptService().weekly_inputs("原神"), [1, 2, 3, 4, 5, 6, 7])

    def test_short_entry_padded_with_default(self):
        """不足 7 格 → 用默认超时补齐。"""
        with open(self.weekly_path, "w", encoding="utf-8") as f:
            yaml.dump({"原神": [10, 20]}, f, allow_unicode=True)
        self.assertEqual(
            ScriptService().weekly_inputs("原神"),
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
            yaml.dump({"原神": [3600] * 7}, f, allow_unicode=True)
        result = ScriptService().check_weekly()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["missing_or_short"], [])
        self.assertEqual(result["orphans"], [])

    def test_missing_entry_reported(self):
        """config 有脚本但 weekly 无条目 → 进 missing_or_short。"""
        result = ScriptService().check_weekly()
        self.assertEqual(result["status"], "inconsistent")
        self.assertEqual(result["missing_or_short"], ["原神"])

    def test_orphan_key_reported(self):
        """weekly 有 config 已删除的 key → 进 orphans。"""
        with open(self.weekly_path, "w", encoding="utf-8") as f:
            yaml.dump(
                {"原神": [3600] * 7, "已删除脚本": [3600] * 7}, f, allow_unicode=True
            )
        result = ScriptService().check_weekly()
        self.assertEqual(result["status"], "inconsistent")
        self.assertEqual(result["orphans"], ["已删除脚本"])

    def test_missing_display_name_raises_keyerror(self):
        """条目缺 display_name 属数据损坏：显式 KeyError，而非静默按 None 处理。"""
        self._write_config({"script_list": [{"script_path": "C:/x.py"}]})
        with self.assertRaises(KeyError):
            ScriptService().check_weekly()


if __name__ == "__main__":
    unittest.main()
