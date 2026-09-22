"""测试 src/utils_weekly.py：周常起始日与每周超时的读写与迁移。

weekly_start（周几起）与 weekly_timeouts（每周 7 格超时）合并存于单一 weekly.yml（双顶层段），
读写由模块函数负责，写回任一段时保留另一段。
**不含周本声明**——各游戏「有哪些周常、可选哪些副本」由 src.config.daily_config
模块函数读 weekly_list.yml 提供，见 test_daily_config.py。
"""

import os
import tempfile
import unittest
from unittest.mock import patch

from src.utils.utils_weekly import (
    DISABLED_START_DAY,
    check_weekly,
    delete_weekly,
    ensure_weekly_entry,
    get_weekly_start_map,
    rename_weekly,
    save_weekly,
    set_weekly_start,
    weekly_inputs,
)
from src.utils.utils_yaml import dump_yaml_file, load_yaml


class UtilsWeeklyTestBase(unittest.TestCase):
    """用临时 weekly.yml（含 weekly_start / weekly_timeouts 两段）隔离真实文件。"""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.weekly_path = os.path.join(self.tmp_dir.name, "weekly.yml")
        # 合并后随包发布、默认建空 {weekly_start: {}, weekly_timeouts: {}} 贴近真实部署。
        # 注意：weekly.yml 是运行期生成的用户文件（CI 干净 checkout 可能不存在），
        # 读取器缺失时回退空结构而非崩溃（见 TestMissingWeeklyFile）。
        self._write_weekly({"weekly_start": {}, "weekly_timeouts": {}})
        patcher = patch(
            "src.utils.utils_weekly.get_weekly_yml_path_under_root",
            return_value=self.weekly_path,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _write_weekly(self, data):
        dump_yaml_file(self.weekly_path, data)

    def _read_weekly(self):
        if not os.path.exists(self.weekly_path):
            return None
        return load_yaml(self.weekly_path)


class TestSaveWeekly(UtilsWeeklyTestBase):
    """save_weekly：保存 7 格超时到 weekly.yml 的 weekly_timeouts 段。"""

    def test_save_weekly_writes_entry(self):
        save_weekly("a", [60] * 7)
        self.assertEqual(self._read_weekly()["weekly_timeouts"]["a"], [60] * 7)
        # 不污染 weekly_start 段
        self.assertEqual(self._read_weekly()["weekly_start"], {})

    def test_none_timeouts_resolved_to_default(self):
        """空输入（None）→ 转默认超时。"""
        save_weekly("a", [None, 60, None, 60, 60, 60, 60])
        self.assertEqual(
            self._read_weekly()["weekly_timeouts"]["a"],
            [3600, 60, 3600, 60, 60, 60, 60],
        )

    def test_low_timeouts_preserved(self):
        """低于 10 的输入原样保留（由 chain_gen 按「<10 当天不运行」跳过，不再 clamp）。"""
        save_weekly("a", [5, 0, 60, 60, 60, 60, 60])
        self.assertEqual(
            self._read_weekly()["weekly_timeouts"]["a"],
            [5, 0, 60, 60, 60, 60, 60],
        )


class TestRenameWeekly(UtilsWeeklyTestBase):
    """rename_weekly：改名时迁移 weekly.yml 两段（weekly_timeouts / weekly_start）条目。"""

    def _seed(self, timeouts):
        self._write_weekly({"weekly_start": {}, "weekly_timeouts": timeouts})

    def test_rename_migrates_entry(self):
        self._seed({"a": [1] * 7})
        rename_weekly("a", "b")
        weekly = self._read_weekly()["weekly_timeouts"]
        self.assertNotIn("a", weekly)
        self.assertEqual(weekly["b"], [1] * 7)

    def test_rename_migrates_weekly_start_too(self):
        """weekly_start 段条目一并迁移，避免改名后周几起成孤儿。"""
        self._write_weekly(
            {
                "weekly_start": {"a": {"周常甲": 3}},
                "weekly_timeouts": {"a": [1] * 7},
            }
        )
        rename_weekly("a", "b")
        weekly = self._read_weekly()
        self.assertNotIn("a", weekly["weekly_start"])
        self.assertEqual(weekly["weekly_start"]["b"], {"周常甲": 3})
        self.assertNotIn("a", weekly["weekly_timeouts"])
        self.assertEqual(weekly["weekly_timeouts"]["b"], [1] * 7)

    def test_rename_start_only_entry(self):
        """只迁 weekly_start 段条目（weekly_timeouts 无旧条目）也能落盘。"""
        self._write_weekly(
            {"weekly_start": {"a": {"周常甲": 5}}, "weekly_timeouts": {}}
        )
        rename_weekly("a", "b")
        weekly = self._read_weekly()
        self.assertEqual(weekly["weekly_start"], {"b": {"周常甲": 5}})
        self.assertEqual(weekly["weekly_timeouts"], {})

    def test_same_name_noop(self):
        """同名的 rename 为 no-op，不影响已有 weekly 条目。"""
        self._seed({"a": [60] * 7})
        rename_weekly("a", "a")
        self.assertEqual(self._read_weekly()["weekly_timeouts"]["a"], [60] * 7)

    def test_old_entry_missing_noop(self):
        """无对应 weekly 条目 → no-op（不报错、不改文件，保持空 {}）。"""
        rename_weekly("none", "b")
        self.assertEqual(self._read_weekly()["weekly_timeouts"], {})


class TestEnsureWeeklyEntry(UtilsWeeklyTestBase):
    def test_creates_default_entry(self):
        ensure_weekly_entry("a")
        self.assertEqual(self._read_weekly()["weekly_timeouts"]["a"], [3600] * 7)

    def test_existing_entry_untouched(self):
        self._write_weekly({"weekly_start": {}, "weekly_timeouts": {"a": [60] * 7}})
        ensure_weekly_entry("a")
        self.assertEqual(self._read_weekly()["weekly_timeouts"]["a"], [60] * 7)


class TestWeeklyInputs(UtilsWeeklyTestBase):
    def test_missing_entry_uses_default(self):
        self.assertEqual(weekly_inputs("a"), [3600] * 7)

    def test_existing_entry_kept(self):
        self._write_weekly(
            {"weekly_start": {}, "weekly_timeouts": {"a": [1, 2, 3, 4, 5, 6, 7]}}
        )
        self.assertEqual(weekly_inputs("a"), [1, 2, 3, 4, 5, 6, 7])

    def test_short_entry_padded_with_default(self):
        """不足 7 格 → 用默认超时补齐。"""
        self._write_weekly({"weekly_start": {}, "weekly_timeouts": {"a": [10, 20]}})
        self.assertEqual(
            weekly_inputs("a"),
            [10, 20, 3600, 3600, 3600, 3600, 3600],
        )


class TestCheckWeekly(UtilsWeeklyTestBase):
    """check_weekly：weekly.yml 的 weekly_timeouts 段与传入 config 脚本条目的一致性。

    config 由调用方（组合根 AppService）读入后传入，本模块不反向依赖 utils_config，
    故此处直接构造 config，不读盘。
    """

    CONFIG = {"script_list": [{"display_name": "原神", "script_path": "C:/a.exe"}]}

    def test_ok_when_aligned(self):
        """weekly 有 7 格条目且无孤儿 → status=ok。"""
        self._write_weekly({"weekly_start": {}, "weekly_timeouts": {"a": [3600] * 7}})
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
        self._write_weekly(
            {
                "weekly_start": {},
                "weekly_timeouts": {"a": [3600] * 7, "gone": [3600] * 7},
            }
        )
        result = check_weekly(self.CONFIG)
        self.assertEqual(result["status"], "inconsistent")
        self.assertEqual(result["orphans"], ["gone"])

    def test_empty_script_list_marks_all_orphans(self):
        """config 无脚本：weekly 中全部条目均视为孤儿。"""
        self._write_weekly({"weekly_start": {}, "weekly_timeouts": {"a": [3600] * 7}})
        result = check_weekly({"script_list": []})
        self.assertEqual(result["status"], "inconsistent")
        self.assertEqual(result["orphans"], ["a"])


class TestDeleteWeekly(UtilsWeeklyTestBase):
    """delete_weekly：仅清理 weekly.yml 的 weekly_timeouts 段孤儿（总 config 移除归 AppService / utils_config）。"""

    def test_delete_weekly_cleans_orphan(self):
        """删除后 weekly_timeouts 段中该脚本的孤儿条目被移除。"""
        self._write_weekly({"weekly_start": {}, "weekly_timeouts": {"a": [100] * 7}})
        delete_weekly("a")
        weekly = self._read_weekly()["weekly_timeouts"]
        self.assertNotIn("a", weekly)
        self.assertEqual(weekly, {})

    def test_delete_weekly_keeps_others(self):
        """删除单个脚本不影响 weekly_timeouts 段中其它条目。"""
        self._write_weekly(
            {"weekly_start": {}, "weekly_timeouts": {"a": [100] * 7, "mute": [120] * 7}}
        )
        delete_weekly("a")
        weekly = self._read_weekly()["weekly_timeouts"]
        self.assertNotIn("a", weekly)
        self.assertEqual(weekly, {"mute": [120] * 7})

    def test_delete_weekly_noop_when_absent(self):
        """脚本无 weekly 条目时清理为 no-op（不报错，文件保持空 {}）。"""
        delete_weekly("不存在")
        self.assertEqual(self._read_weekly()["weekly_timeouts"], {})


class TestSetWeeklyStart(UtilsWeeklyTestBase):
    """set_weekly_start / get_weekly_start_map：读写 weekly.yml 的 weekly_start 段（条目级）。"""

    def test_set_writes_to_weekly_start_file_only(self):
        set_weekly_start("a", {"周常甲": 4})
        self.assertEqual(self._read_weekly()["weekly_start"], {"a": {"周常甲": 4}})
        # 不污染 weekly_timeouts 段
        self.assertEqual(self._read_weekly()["weekly_timeouts"], {})

    def test_get_map_returns_entries(self):
        set_weekly_start("a", {"周常甲": 3, "周常乙": 5})
        self.assertEqual(get_weekly_start_map(), {"a": {"周常甲": 3, "周常乙": 5}})

    def test_set_empty_clears_entry(self):
        """空 dict → 移除该脚本条目（对应界面「不设置」）。"""
        set_weekly_start("a", {"周常甲": 2})
        set_weekly_start("a", {})
        self.assertEqual(get_weekly_start_map(), {})

    def test_disabled_sentinel_is_accepted(self):
        """0 = 不启用，是合法取值（区别于「未设置」）。"""
        set_weekly_start("a", {"周常甲": DISABLED_START_DAY})
        self.assertEqual(get_weekly_start_map(), {"a": {"周常甲": DISABLED_START_DAY}})

    def test_invalid_day_raises(self):
        for bad in (8, -1):
            with self.subTest(bad=bad), self.assertRaises(AssertionError):
                set_weekly_start("a", {"周常甲": bad})

    def test_non_int_day_raises(self):
        with self.assertRaises(AssertionError):
            set_weekly_start("a", {"周常甲": "3"})


class TestLegacyWeeklyStartMigration(UtilsWeeklyTestBase):
    """旧版脚本级单值（{脚本: 1~7}）读到时就地迁移为条目级，并按当前周常声明展开。

    周几起改为条目级后，历史 weekly.yml 的脚本级单值语义等价于「该脚本全部周常同一天」，
    故读路径直接展开并写回（一次性）；不可展开的条目告警后丢弃，不卡住读路径。
    """

    def test_legacy_scalar_expanded_per_declared_weeklies(self):
        """单值按该脚本声明的周常逐条展开；weekly_timeouts 段原样保留。"""
        self._write_weekly(
            {
                "weekly_start": {"ok-ww": 2, "March7th-Launcher": 3},
                "weekly_timeouts": {"ok-ww": [60] * 7},
            }
        )
        with self.assertLogs("src.utils.utils_weekly", level="WARNING"):
            start_map = get_weekly_start_map()
        self.assertEqual(
            start_map,
            {
                "ok-ww": {"幻梦游园": 2},
                "March7th-Launcher": {"货币战争": 3, "历战余响": 3, "模拟宇宙": 3},
            },
        )
        # 已落盘为条目级；另一段不受影响
        weekly = self._read_weekly()
        self.assertEqual(weekly["weekly_start"], start_map)
        self.assertEqual(weekly["weekly_timeouts"], {"ok-ww": [60] * 7})

    def test_migration_is_idempotent(self):
        """迁移后已是条目级 → 再读不写盘（不产生重复写入）。"""
        self._write_weekly({"weekly_start": {"ok-ww": 2}, "weekly_timeouts": {}})
        with self.assertLogs("src.utils.utils_weekly", level="WARNING"):
            get_weekly_start_map()
        with patch("src.utils.utils_weekly._dump_weekly_start") as dump:
            self.assertEqual(get_weekly_start_map(), {"ok-ww": {"幻梦游园": 2}})
        dump.assert_not_called()

    def test_unmigratable_entries_dropped_with_warning(self):
        """起始日越界 / 脚本已无周常声明的条目丢弃，其余照常迁移。"""
        self._write_weekly(
            {
                "weekly_start": {"ok-ww": 9, "不存在的脚本": 3, "ok-ef": 6},
                "weekly_timeouts": {},
            }
        )
        with self.assertLogs("src.utils.utils_weekly", level="WARNING") as logs:
            start_map = get_weekly_start_map()
        self.assertEqual(start_map, {"ok-ef": {"卖出物资": 6}})
        self.assertEqual(len(logs.records), 3)  # 两条丢弃告警 + 一条迁移告警
        for script_name in ("ok-ww", "不存在的脚本"):
            self.assertNotIn(script_name, self._read_weekly()["weekly_start"])

    def test_entry_level_data_untouched(self):
        """已是条目级（含空 dict）→ 原样返回、不写盘、不告警。"""
        set_weekly_start("ok-ww", {"幻梦游园": 4})
        with patch("src.utils.utils_weekly._dump_weekly_start") as dump:
            self.assertEqual(get_weekly_start_map(), {"ok-ww": {"幻梦游园": 4}})
        dump.assert_not_called()


class TestMissingWeeklyFile(unittest.TestCase):
    """weekly.yml 缺失（用户文件、CI 干净 checkout 尚未生成）时读取不崩，回退空结构。

    与 schedule.yml 一致：用户文件可能不存在，读取器用 load_yaml_optional 回退空 {}，
    而非 assert 崩溃（这正是 CI test_chain_service 崩溃的根因修复）。
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.missing_path = os.path.join(self.tmp.name, "does_not_exist.yml")
        patcher = patch(
            "src.utils.utils_weekly.get_weekly_yml_path_under_root",
            return_value=self.missing_path,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_reads_return_empty_without_file(self):
        self.assertEqual(get_weekly_start_map(), {})
        self.assertEqual(weekly_inputs("a"), [3600] * 7)

    def test_save_creates_file_with_both_sections(self):
        """缺失时首次写回会创建文件，且 weekly_start / weekly_timeouts 两段都在。"""
        save_weekly("a", [60] * 7)
        data = load_yaml(self.missing_path)
        self.assertEqual(data["weekly_timeouts"]["a"], [60] * 7)
        self.assertEqual(data["weekly_start"], {})


if __name__ == "__main__":
    unittest.main()
