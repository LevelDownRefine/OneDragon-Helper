"""测试 src/config/dungeon_config.py：副本与周常声明读取（get_dungeon_map / get_weekly_map）。"""

import os
import tempfile
import unittest
from unittest.mock import patch

from src.config.dungeon_config import get_dungeon_map, get_weekly_map
from src.utils_yaml import dump_yaml_file


class TestGetWeeklyDefs(unittest.TestCase):
    """get_weekly_map：静态 dungeons 保持，dungeons_source 运行期从外部读取/降级。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.weekly_list_path = os.path.join(self.tmp.name, "weekly_list.yml")
        patcher = patch(
            "src.config.dungeon_config.get_weekly_list_yml_path_under_root",
            return_value=self.weekly_list_path,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _write(self, data):
        dump_yaml_file(self.weekly_list_path, data)

    def test_static_dungeons_untouched(self):
        """带 dungeons（无 dungeons_source）的项保持原样，不触发外部读取。"""
        self._write(
            {
                "March7th-Launcher": [
                    {"name": "历战余响", "dungeons": ["无", "铁骸的锈冢"]}
                ]
            }
        )
        with patch("src.config.dungeon_config.get_dungeon_lists") as mock_ext:
            defs = get_weekly_map("March7th-Launcher")
        self.assertEqual(defs[0]["dungeons"], ["无", "铁骸的锈冢"])
        mock_ext.assert_not_called()  # 无 dungeons_source 不读外部

    def test_external_source_filled_when_reachable(self):
        """dungeons_source=assets/config/instance_names.json 且外部可读 → 用外部副本清单填充。"""
        self._write(
            {
                "March7th-Launcher": [
                    {
                        "name": "历战余响",
                        "dungeons_source": "assets/config/instance_names.json",
                    }
                ]
            }
        )
        names = ["无", "铁骸的锈冢", "晨昏的回眸"]
        with patch(
            "src.config.dungeon_config.get_dungeon_lists", return_value=names
        ) as mock_ext:
            defs = get_weekly_map("March7th-Launcher")
        mock_ext.assert_called_once_with(
            "March7th-Launcher", "历战余响", "assets/config/instance_names.json"
        )
        self.assertEqual(defs[0]["dungeons"], names)
        self.assertTrue(defs[0]["dungeons"])  # 供 GUI 推导 has_dungeon

    def test_external_source_empty_when_unreachable(self):
        """外部读不到（返回 None）→ 降级 dungeons=[]，该周常无需选副本。"""
        self._write(
            {
                "March7th-Launcher": [
                    {
                        "name": "历战余响",
                        "dungeons_source": "assets/config/instance_names.json",
                    }
                ]
            }
        )
        with patch("src.config.dungeon_config.get_dungeon_lists", return_value=None):
            defs = get_weekly_map("March7th-Launcher")
        self.assertEqual(defs[0]["dungeons"], [])

    def test_unknown_script_returns_empty(self):
        """未知脚本 → get_weekly_map 返回空列表（不抛错、不读外部）。"""
        self._write({"March7th-Launcher": [{"name": "货币战争"}]})
        self.assertEqual(get_weekly_map("不存在"), [])


class TestGetDungeonMap(unittest.TestCase):
    """get_dungeon_map：静态 sequences 保持，dungeons_source 运行期从外部读取/降级。"""

    def test_static_sequences_untouched(self):
        """带 dungeons（无 dungeons_source）的项保持原样，不触发外部读取。"""
        raw = {
            "ok-ef": {
                "dungeons": [
                    {
                        "name": "干员养成",
                        "sequences": [{"display": "干员经验", "value": "干员经验"}],
                    }
                ]
            }
        }
        with (
            patch("src.config.dungeon_config.load_dungeon_map", return_value=raw),
            patch("src.config.dungeon_config.get_dungeon_lists") as mock_ext,
        ):
            result = get_dungeon_map()
        self.assertEqual(
            result["ok-ef"]["dungeons"][0]["sequences"],
            [{"display": "干员经验", "value": "干员经验"}],
        )
        mock_ext.assert_not_called()  # 无 dungeons_source 不读外部

    def test_fills_sequences_from_dungeons_source(self):
        """带 dungeons_source 的声明项，其二级序列由 get_dungeon_lists 运行期填充。"""
        raw = {
            "ok-ef": {
                "dungeons": [
                    {"name": "培养目标"},
                    {
                        "name": "能量淤积点",
                        "dungeons_source": "data/apps/ok-ef/working/assets/data/world_map.json",
                    },
                ]
            }
        }
        with (
            patch("src.config.dungeon_config.load_dungeon_map", return_value=raw),
            patch(
                "src.config.dungeon_config.get_dungeon_lists",
                return_value=["枢纽区", "武陵城"],
            ) as mock_ext,
        ):
            result = get_dungeon_map()
        # 培养目标（无 dungeons_source）保持无序列
        self.assertEqual(result["ok-ef"]["dungeons"][0].get("sequences"), None)
        # 带 dungeons_source 的项被填充为 {display,value} 序列
        seqs = result["ok-ef"]["dungeons"][1]["sequences"]
        self.assertEqual(
            seqs,
            [
                {"display": "枢纽区", "value": "枢纽区"},
                {"display": "武陵城", "value": "武陵城"},
            ],
        )
        mock_ext.assert_called_once_with(
            "ok-ef", "能量淤积点", "data/apps/ok-ef/working/assets/data/world_map.json"
        )

    def test_dungeons_source_unreachable_degrades_to_empty(self):
        """dungeons_source 读不到（get_dungeon_lists 返回 []）→ 降级为空序列。"""
        raw = {
            "ok-ef": {
                "dungeons": [
                    {
                        "name": "能量淤积点",
                        "dungeons_source": "data/apps/ok-ef/working/assets/data/world_map.json",
                    }
                ]
            }
        }
        with (
            patch("src.config.dungeon_config.load_dungeon_map", return_value=raw),
            patch("src.config.dungeon_config.get_dungeon_lists", return_value=[]),
        ):
            result = get_dungeon_map()
        self.assertEqual(result["ok-ef"]["dungeons"][0]["sequences"], [])


if __name__ == "__main__":
    unittest.main()
