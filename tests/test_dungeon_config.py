"""测试 dungeon_config 模块"""
import unittest
from unittest.mock import patch, MagicMock

from src.config.dungeon_config import (
    parse_dungeon_config,
    get_display_name,
    restore_sequence_type,
)


class TestParseDungeonConfig(unittest.TestCase):
    """测试 parse_dungeon_config"""

    def test_empty_dungeons(self):
        """空 dungeons 列表返回空结果"""
        cfg = {"dungeons": []}
        options, seq_map, show_seq = parse_dungeon_config(cfg)
        self.assertEqual(options, [])
        self.assertEqual(seq_map, {})
        self.assertFalse(show_seq)

    def test_none_input(self):
        """None 输入返回空结果"""
        options, seq_map, show_seq = parse_dungeon_config(None)
        self.assertEqual(options, [])
        self.assertEqual(seq_map, {})
        self.assertFalse(show_seq)

    def test_flat_list(self):
        """只有一级选项（无 sequences）"""
        cfg = {
            "dungeons": [
                {"name": "未选择"},
                {"name": "副本A"},
                {"name": "副本B"},
            ]
        }
        options, seq_map, show_seq = parse_dungeon_config(cfg)
        self.assertEqual(options, ["未选择", "副本A", "副本B"])
        self.assertEqual(seq_map, {})
        self.assertFalse(show_seq)

    def test_with_sequences(self):
        """有二级选项"""
        cfg = {
            "dungeons": [
                {"name": "未选择"},
                {
                    "name": "凝素领域",
                    "sequences": [
                        {"display": "第1层", "value": 1},
                        {"display": "第2层", "value": 2},
                    ],
                },
            ]
        }
        options, seq_map, show_seq = parse_dungeon_config(cfg)
        self.assertEqual(options, ["未选择", "凝素领域"])
        self.assertEqual(seq_map["凝素领域"], [("第1层", 1), ("第2层", 2)])
        self.assertTrue(show_seq)

    def test_mixed_formats(self):
        """混合格式：有二级选项和无二级选项"""
        cfg = {
            "dungeons": [
                {"name": "未选择"},
                {
                    "name": "凝素领域",
                    "sequences": [
                        {"display": "第1层", "value": 1},
                        {"display": "第2层", "value": 2},
                    ],
                },
                {
                    "name": "模拟领域",
                    "sequences": [
                        {"display": "共鸣者经验", "value": "共鸣者经验"},
                        {"display": "武器经验", "value": "武器经验"},
                    ],
                },
            ]
        }
        options, seq_map, show_seq = parse_dungeon_config(cfg)
        self.assertEqual(options, ["未选择", "凝素领域", "模拟领域"])
        self.assertEqual(seq_map["凝素领域"], [("第1层", 1), ("第2层", 2)])
        self.assertEqual(seq_map["模拟领域"], [("共鸣者经验", "共鸣者经验"), ("武器经验", "武器经验")])
        self.assertTrue(show_seq)

    def test_invalid_format_no_dungeons_key(self):
        """缺少 dungeons 键返回空结果"""
        cfg = {"not_dungeons": []}
        options, seq_map, show_seq = parse_dungeon_config(cfg)
        self.assertEqual(options, [])
        self.assertEqual(seq_map, {})
        self.assertFalse(show_seq)


class TestGetDisplayName(unittest.TestCase):
    """测试 get_display_name"""

    def test_found_integer_value(self):
        """找到整数类型的实际值"""
        seq_map = {"凝素领域": [("第1层", 1), ("第17层", 17)]}
        result = get_display_name(seq_map, "凝素领域", 17)
        self.assertEqual(result, "第17层")

    def test_found_string_value(self):
        """找到字符串类型的实际值"""
        seq_map = {"模拟领域": [("共鸣者经验", "共鸣者经验"), ("武器经验", "武器经验")]}
        result = get_display_name(seq_map, "模拟领域", "武器经验")
        self.assertEqual(result, "武器经验")

    def test_not_found_returns_string(self):
        """找不到时返回实际值的字符串表示"""
        seq_map = {"凝素领域": [("第1层", 1)]}
        result = get_display_name(seq_map, "凝素领域", 99)
        self.assertEqual(result, "99")

    def test_dungeon_not_in_map(self):
        """副本不在映射中"""
        seq_map = {"凝素领域": [("第1层", 1)]}
        result = get_display_name(seq_map, "不存在", 1)
        self.assertEqual(result, "1")


class TestRestoreSequenceType(unittest.TestCase):
    """测试 restore_sequence_type"""

    def test_no_sequence(self):
        """没有 sequence 时返回原字典"""
        saved = {"dungeon": "凝素领域"}
        seq_map = {"凝素领域": [("第1层", 1), ("第17层", 17)]}
        result = restore_sequence_type(saved, seq_map)
        self.assertIs(result, saved)

    def test_no_dungeon(self):
        """没有 dungeon 时返回原字典"""
        saved = {"sequence": "17"}
        seq_map = {"凝素领域": [("第1层", 1), ("第17层", 17)]}
        result = restore_sequence_type(saved, seq_map)
        self.assertIs(result, saved)

    def test_dungeon_not_in_map(self):
        """副本不在映射中时返回原字典"""
        saved = {"dungeon": "不存在", "sequence": "17"}
        seq_map = {"凝素领域": [("第1层", 1), ("第17层", 17)]}
        result = restore_sequence_type(saved, seq_map)
        self.assertIs(result, saved)

    def test_string_to_integer_conversion(self):
        """字符串 "17" 转换为整数 17"""
        saved = {"dungeon": "凝素领域", "sequence": "17"}
        seq_map = {"凝素领域": [("第1层", 1), ("第17层", 17)]}
        result = restore_sequence_type(saved, seq_map)
        self.assertIsNot(result, saved)
        self.assertEqual(result["sequence"], 17)
        self.assertEqual(type(result["sequence"]), int)

    def test_no_conversion_needed(self):
        """已经是正确类型时不转换"""
        saved = {"dungeon": "凝素领域", "sequence": 17}
        seq_map = {"凝素领域": [("第1层", 1), ("第17层", 17)]}
        result = restore_sequence_type(saved, seq_map)
        self.assertIsNot(result, saved)
        self.assertEqual(result["sequence"], 17)

    def test_string_value_no_conversion(self):
        """字符串类型的值不转换"""
        saved = {"dungeon": "模拟领域", "sequence": "武器经验"}
        seq_map = {"模拟领域": [("共鸣者经验", "共鸣者经验"), ("武器经验", "武器经验")]}
        result = restore_sequence_type(saved, seq_map)
        self.assertIsNot(result, saved)
        self.assertEqual(result["sequence"], "武器经验")


if __name__ == '__main__':
    unittest.main()