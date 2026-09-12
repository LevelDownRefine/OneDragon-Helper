"""日常和周常共用声明规则，不引入运行期多日常接口。"""

import os
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from src.config import task_config as m
from src.utils.utils_yaml import dump_yaml_file


class TestTaskDeclarations(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "tasks.yml"
        m._load_task_map.cache_clear()
        self.addCleanup(m._load_task_map.cache_clear)

    def load(self, data):
        dump_yaml_file(str(self.path), data)
        return m.load_task_map(str(self.path))

    def test_names_and_recursive_options(self):
        data = {
            "script": [
                {
                    "display_name": "任务",
                    "physical_name": "native_task",
                    "key": "enabled",
                    "options": {
                        "values": [
                            {
                                "display_name": "分类",
                                "options": {
                                    "key": "target",
                                    "values": [
                                        {
                                            "display_name": "二级",
                                            "physical_name": 7,
                                            "options": {
                                                "values": [{"display_name": "三级"}]
                                            },
                                        }
                                    ],
                                },
                            }
                        ]
                    },
                }
            ]
        }
        loaded = self.load(data)
        self.assertEqual(loaded, data)
        self.assertEqual(m.get_physical_name(loaded["script"][0]), "native_task")
        self.assertEqual(m.get_physical_name({"display_name": "原样"}), "原样")

    def test_same_schema_in_two_separate_files(self):
        daily = m.load_daily_map()
        weekly = m.load_weekly_map()
        self.assertEqual(len(daily["ok-nte"]), 2)
        self.assertTrue(
            all(
                len(tasks) == 1 for script, tasks in daily.items() if script != "ok-nte"
            )
        )
        self.assertEqual(
            [t["display_name"] for t in weekly["March7th-Launcher"]],
            ["货币战争", "历战余响"],
        )
        for definitions in (*daily.values(), *weekly.values()):
            for task in definitions:
                self.assertNotIn("type", task)
                self.assertNotIn("allow_disable", task)
                self.assertEqual(self.load({"test": [task]})["test"][0], task)

    def test_invalid_nodes_are_rejected(self):
        valid = {
            "display_name": "任务",
            "options": {"values": [{"display_name": "选项", "physical_name": 1}]},
        }
        cases = [
            None,
            [],
            {"s": {}},
            {"s": [{"name": "旧格式"}]},
            {"s": [valid, valid]},
        ]
        for field, value in (
            ("display_name", ""),
            ("physical_name", 1),
            ("type", "daily"),
            ("allow_disable", True),
        ):
            task = deepcopy(valid)
            task[field] = value
            cases.append({"s": [task]})
        for option in (
            {"name": "旧格式"},
            {"display_name": ""},
            {"display_name": "x", "physical_name": True},
        ):
            task = deepcopy(valid)
            task["options"]["values"] = [option]
            cases.append({"s": [task]})
        for group in (
            {},
            {"key": "target"},
            {"values": [], "source": {"path": "a.json"}},
            {"values": "not-list"},
            {"values": [], "field": "x"},
        ):
            task = deepcopy(valid)
            task["options"] = group
            cases.append({"s": [task]})
        for data in cases:
            with self.subTest(data=data), self.assertRaises(AssertionError):
                self.load(data)

    def test_duplicate_physical_names_and_display_names_are_rejected(self):
        for options in (
            [{"display_name": "同名"}, {"display_name": "同名", "physical_name": 2}],
            [
                {"display_name": "甲", "physical_name": 1},
                {"display_name": "乙", "physical_name": 1},
            ],
        ):
            with self.subTest(options=options), self.assertRaises(AssertionError):
                self.load(
                    {"s": [{"display_name": "任务", "options": {"values": options}}]}
                )

    def test_sources_require_script_relative_paths(self):
        for path in (
            "../a.json",
            "C:/a.json",
            "C:a.json",
            "/tmp/a.json",
            "\\\\server\\share\\a.json",
            "",
        ):
            with self.subTest(path=path), self.assertRaises(AssertionError):
                self.load(
                    {
                        "s": [
                            {
                                "display_name": "任务",
                                "options": {"source": {"path": path}},
                            }
                        ]
                    }
                )
        task = {
            "display_name": "任务",
            "options": {"source": {"path": "resource/list.json", "category": "native"}},
        }
        self.assertEqual(self.load({"s": [task]}), {"s": [task]})

    def test_cache_returns_independent_copies_and_reloads_file_change(self):
        data = {
            "s": [
                {
                    "display_name": "初始任务",
                    "options": {"values": [{"display_name": "选项"}]},
                }
            ]
        }
        self.load(data)
        with patch.object(m, "load_yaml_str", wraps=m.load_yaml_str) as read:
            first = m.load_task_map(str(self.path))
            first["s"][0]["options"]["values"].clear()
            self.assertEqual(m.load_task_map(str(self.path)), data)
        read.assert_not_called()
        stat = self.path.stat()
        data["s"][0]["display_name"] = "更新任务"
        dump_yaml_file(str(self.path), data)
        os.utime(self.path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.assertEqual(self.path.stat().st_size, stat.st_size)
        self.assertEqual(m.load_task_map(str(self.path)), data)

    def test_missing_file_is_not_an_empty_declaration(self):
        with self.assertRaisesRegex(AssertionError, "任务声明缺失"):
            m.load_task_map(str(self.path))

    def test_weekly_lookup_uses_name_instead_of_position(self):
        tasks = [
            {"display_name": "另一周常"},
            {"display_name": "指定周常", "physical_name": "native"},
        ]
        with patch.object(m, "load_weekly_map", return_value={"s": tasks}):
            self.assertEqual(m.get_weekly_config("s", "指定周常"), tasks[1])
            with self.assertRaisesRegex(AssertionError, "缺少周常声明"):
                m.get_weekly_config("s", "不存在")


if __name__ == "__main__":
    unittest.main()
