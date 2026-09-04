"""测试 src/utils_weekly.py：周常起始日与每周超时的读写与迁移。

weekly_start.yml（周几起）与 weekly_timeouts.yml（每周 7 格超时）的读写由模块函数负责。
**不含周本声明**——各游戏「有哪些周常、可选哪些副本」由 src.config.dungeon_config
模块函数读 weekly_list.yml 提供，见 test_dungeon_config.py。
"""

import os
import tempfile
import unittest
from unittest.mock import patch

from src.utils.utils_weekly import (
    check_weekly,
    delete_weekly,
    ensure_weekly_entry,
    get_weekly_start,
    rename_weekly_in_timeouts,
    save_weekly,
    set_weekly_start,
    weekly_inputs,
)
from src.utils.utils_yaml import dump_yaml_file, load_yaml


class UtilsWeeklyTestBase(unittest.TestCase):
    """用临时 weekly_timeouts.yml / weekly_start.yml 隔离真实文件。"""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.weekly_path = os.path.join(self.tmp_dir.name, "weekly_timeouts.yml")
        self.weekly_start_path = os.path.join(self.tmp_dir.name, "weekly_start.yml")
        # 两份配置均随包发布、必存在，默认建空 {} 文件贴近真实部署
        # （缺失→{} 的兜底已移除，改 assert 暴露）。
        self._write_weekly({})
        self._write_weekly_start({})
        patchers = [
            patch(
                "src.utils.utils_weekly.get_weekly_timeouts_yml_path_under_root",
                return_value=self.weekly_path,
            ),
            patch(
                "src.utils.utils_weekly.get_weekly_start_yml_path_under_root",
                return_value=self.weekly_start_path,
            ),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)

    def _write_weekly(self, data):
        dump_yaml_file(self.weekly_path, data)

    def _write_weekly_start(self, data):
        dump_yaml_file(self.weekly_start_path, data)

    def _read_weekly(self):
        if not os.path.exists(self.weekly_path):
            return None
        return load_yaml(self.weekly_path)

    def _read_weekly_start(self):
        if not os.path.exists(self.weekly_start_path):
            return None
        return load_yaml(self.weekly_start_path)


class TestSaveWeekly(UtilsWeeklyTestBase):
    """save_weekly：保存 7 格超时到 weekly_timeouts.yml。"""

    def test_save_weekly_writes_entry(self):
        save_weekly("a", [60] * 7)
        self.assertEqual(self._read_weekly()["a"], [60] * 7)

    def test_none_timeouts_resolved_to_default(self):
        """空输入（None）→ 转默认超时。"""
        save_weekly("a", [None, 60, None, 60, 60, 60, 60])
        self.assertEqual(
            self._read_weekly()["a"],
            [3600, 60, 3600, 60, 60, 60, 60],
        )

    def test_low_timeouts_preserved(self):
        """低于 10 的输入原样保留（由 chain_gen 按「<10 当天不运行」跳过，不再 clamp）。"""
        save_weekly("a", [5, 0, 60, 60, 60, 60, 60])
        self.assertEqual(
            self._read_weekly()["a"],
            [5, 0, 60, 60, 60, 60, 60],
        )


class TestRenameWeeklyInTimeouts(UtilsWeeklyTestBase):
    """rename_weekly_in_timeouts：改名时迁移 weekly_timeouts.yml 条目。"""

    def test_rename_migrates_entry(self):
        dump_yaml_file(self.weekly_path, {"a": [1] * 7})
        rename_weekly_in_timeouts("a", "b")
        weekly = self._read_weekly()
        self.assertNotIn("a", weekly)
        self.assertEqual(weekly["b"], [1] * 7)

    def test_same_name_noop(self):
        """同名的 rename 为 no-op，不影响已有 weekly 条目。"""
        dump_yaml_file(self.weekly_path, {"a": [60] * 7})
        rename_weekly_in_timeouts("a", "a")
        self.assertEqual(self._read_weekly()["a"], [60] * 7)

    def test_old_entry_missing_noop(self):
        """无对应 weekly 条目 → no-op（不报错、不改文件，保持空 {}）。"""
        rename_weekly_in_timeouts("none", "b")
        self.assertEqual(self._read_weekly(), {})


class TestEnsureWeeklyEntry(UtilsWeeklyTestBase):
    def test_creates_default_entry(self):
        ensure_weekly_entry("a")
        self.assertEqual(self._read_weekly()["a"], [3600] * 7)

    def test_existing_entry_untouched(self):
        dump_yaml_file(self.weekly_path, {"a": [60] * 7})
        ensure_weekly_entry("a")
        self.assertEqual(self._read_weekly()["a"], [60] * 7)


class TestWeeklyInputs(UtilsWeeklyTestBase):
    def test_missing_entry_uses_default(self):
        self.assertEqual(weekly_inputs("a"), [3600] * 7)

    def test_existing_entry_kept(self):
        dump_yaml_file(self.weekly_path, {"a": [1, 2, 3, 4, 5, 6, 7]})
        self.assertEqual(weekly_inputs("a"), [1, 2, 3, 4, 5, 6, 7])

    def test_short_entry_padded_with_default(self):
        """不足 7 格 → 用默认超时补齐。"""
        dump_yaml_file(self.weekly_path, {"a": [10, 20]})
        self.assertEqual(
            weekly_inputs("a"),
            [10, 20, 3600, 3600, 3600, 3600, 3600],
        )


class TestCheckWeekly(UtilsWeeklyTestBase):
    """check_weekly：weekly_timeouts.yml 与传入 config 脚本条目的一致性。

    config 由调用方（组合根 AppService）读入后传入，本模块不反向依赖 utils_config，
    故此处直接构造 config，不读盘。
    """

    CONFIG = {"script_list": [{"display_name": "原神", "script_path": "C:/a.exe"}]}

    def test_ok_when_aligned(self):
        """weekly 有 7 格条目且无孤儿 → status=ok。"""
        dump_yaml_file(self.weekly_path, {"a": [3600] * 7})
        result = check_weekly(self.CONFIG)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["missing_or_short"], [])
        self.assertEqual(result["orphans"], [])

    def test_missing_entry_reported(self):
        """config 有脚本但 weekly 无条目 → 进 missing_or_short。"""
        result = check_weekly(self.CONFIG)
        self.assertEqual(result["status"], "inconsistent")
        self.assertEqual(result["missing_or_short"], ["a"])

    def test_orphan_key_reported(self):
        """weekly 有 config 已删除的 key → 进 orphans。"""
        dump_yaml_file(self.weekly_path, {"a": [3600] * 7, "gone": [3600] * 7})
        result = check_weekly(self.CONFIG)
        self.assertEqual(result["status"], "inconsistent")
        self.assertEqual(result["orphans"], ["gone"])

    def test_empty_script_list_marks_all_orphans(self):
        """config 无脚本：weekly 中全部条目均视为孤儿。"""
        dump_yaml_file(self.weekly_path, {"a": [3600] * 7})
        result = check_weekly({"script_list": []})
        self.assertEqual(result["status"], "inconsistent")
        self.assertEqual(result["orphans"], ["a"])


class TestDeleteWeekly(UtilsWeeklyTestBase):
    """delete_weekly：仅清理 weekly_timeouts.yml 孤儿（总 config 移除归 AppService / utils_config）。"""

    def test_delete_weekly_cleans_orphan(self):
        """删除后 weekly_timeouts.yml 中该脚本的孤儿条目被移除。"""
        dump_yaml_file(self.weekly_path, {"a": [100] * 7})
        delete_weekly("a")
        weekly = self._read_weekly()
        self.assertNotIn("a", weekly)
        self.assertEqual(weekly, {})

    def test_delete_weekly_keeps_others(self):
        """删除单个脚本不影响 weekly_timeouts.yml 中其它条目。"""
        dump_yaml_file(self.weekly_path, {"a": [100] * 7, "mute": [120] * 7})
        delete_weekly("a")
        weekly = self._read_weekly()
        self.assertNotIn("a", weekly)
        self.assertEqual(weekly, {"mute": [120] * 7})

    def test_delete_weekly_noop_when_absent(self):
        """脚本无 weekly 条目时清理为 no-op（不报错，文件保持空 {}）。"""
        delete_weekly("不存在")
        self.assertEqual(self._read_weekly(), {})


class TestSetWeeklyStart(UtilsWeeklyTestBase):
    """set_weekly_start / get_weekly_start：读写独立文件 weekly_start.yml。"""

    def test_set_writes_to_weekly_start_file_only(self):
        set_weekly_start("a", 4)
        self.assertEqual(self._read_weekly_start(), {"a": 4})
        # 不污染 weekly_timeouts.yml
        self.assertEqual(self._read_weekly(), {})

    def test_get_returns_set_value(self):
        set_weekly_start("a", 3)
        self.assertEqual(get_weekly_start("a"), 3)
        self.assertIsNone(get_weekly_start("缺失"))

    def test_set_none_clears_entry(self):
        """start_day=None → 移除该脚本条目。"""
        set_weekly_start("a", 2)
        set_weekly_start("a", None)
        self.assertIsNone(get_weekly_start("a"))
        self.assertEqual(self._read_weekly_start(), {})

    def test_invalid_day_raises(self):
        for bad in (0, 8):
            with self.subTest(bad=bad), self.assertRaises(AssertionError):
                set_weekly_start("a", bad)


if __name__ == "__main__":
    unittest.main()
