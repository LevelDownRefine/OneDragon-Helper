"""任务声明及候选资源的独立解析测试。"""

import unittest
from copy import deepcopy

from src.config import task_parser as parser


class TestTaskParser(unittest.TestCase):
    def test_task_result_does_not_share_nested_options_with_input(self):
        raw = {
            "script": [
                {
                    "display_name": "日常",
                    "class": "Daily",
                    "config": "config/task.yml",
                    "options": {"values": [{"display_name": "副本"}]},
                }
            ]
        }
        result = parser.parse_task_map(raw, require_class=True)
        result["script"][0]["options"]["values"][0]["display_name"] = "修改"
        self.assertEqual(
            raw["script"][0]["options"]["values"][0]["display_name"], "副本"
        )

    def test_daily_and_weekly_require_relative_configuration_paths(self):
        for path in ["/outside.yml", "C:/outside.yml", "../outside.yml"]:
            with self.subTest(path=path), self.assertRaises(AssertionError):
                parser.parse_task_map(
                    {
                        "script": [
                            {"display_name": "任务", "class": "Daily", "config": path}
                        ]
                    },
                    require_class=True,
                )

    def test_static_and_resource_options_expand_without_mutating_declaration(self):
        raw = {
            "display_name": "日常",
            "options": {
                "values": [
                    {
                        "display_name": "副本",
                        "physical_name": "native",
                        "options": {"source": {"path": "stages.json"}},
                    }
                ]
            },
        }
        before = deepcopy(raw)
        sources = []

        def read_source(source):
            sources.append(source)
            return ["甲", "乙"]

        result = parser.materialize_options(raw, read_source)
        self.assertEqual(raw, before)
        self.assertEqual(sources, [{"path": "stages.json"}])
        self.assertEqual(result["values"][0]["physical_name"], "native")
        self.assertEqual(
            parser.get_value_map(result["values"][0]), {"甲": "甲", "乙": "乙"}
        )

    def test_key_path_resources_return_list_values_or_dictionary_keys(self):
        source = {"path": "stages.json", "key": ["stages"]}
        for stages in [["甲", "乙"], {"甲": 1, "乙": 2}]:
            with self.subTest(stages=stages):
                self.assertEqual(
                    parser.parse_source_names({"stages": stages}, source, "script"),
                    ["甲", "乙"],
                )
        self.assertEqual(parser.parse_source_names(None, source, "script"), [])

    def test_recursive_parser_preserves_levels_beyond_current_menu_limit(self):
        node = {"display_name": "最内层"}
        for name in ["二级", "一级", "日常"]:
            node = {"display_name": name, "options": {"values": [node]}}
        result = parser.materialize_options(node, lambda source: [])
        leaf = result["values"][0]["options"]["values"][0]["options"]["values"][0]
        self.assertEqual(leaf["physical_name"], "最内层")

    def test_switch_default_path_and_name_mapping_are_independent(self):
        raw = {
            "script": {
                "config": "config.json",
                "segments": [{"list_key": "tasks", "names": {"id": "任务"}}],
            }
        }
        result = parser.parse_task_switch_map(raw)
        self.assertEqual(result["script"][0]["config"], "config.json")
        self.assertEqual(parser.switch_form(result["script"][0]), "multi_select")
        result["script"][0]["names"]["id"] = "修改"
        self.assertEqual(raw["script"]["segments"][0]["names"]["id"], "任务")

    def test_option_declaration_errors_are_found_before_reading_native_config(self):
        field = {
            "id": "targets",
            "display_name": "目标",
            "keys": ["targets"],
            "type": "multi",
            "values": ["甲", "乙"],
        }
        group = {
            "display_name": "任务",
            "config": "config.json",
            "tasks": ["任务"],
            "fields": [field],
        }
        for change in [
            {"values": "甲"},
            {"values": ["甲", "甲"]},
            {"values": [""]},
            {"min_items": True},
            {"min_items": -1},
        ]:
            with self.subTest(change=change), self.assertRaises(AssertionError):
                parser.parse_task_options(
                    {
                        "script": {
                            "options": [{**group, "fields": [{**field, **change}]}]
                        }
                    }
                )

    def test_options_ignore_switch_fields_and_return_independent_groups(self):
        raw = {
            "script": {
                "config": "native.json",
                "task_pattern": "(.+)",
                "options": [
                    {
                        "display_name": "任务",
                        "config": "native.json",
                        "tasks": [],
                        "fields": [
                            {
                                "id": "choice",
                                "display_name": "选择",
                                "keys": ["choice"],
                                "type": "choice",
                                "values": ["甲"],
                            }
                        ],
                    }
                ],
            }
        }
        result = parser.parse_task_options(raw)
        result["script"][0]["fields"][0]["values"].append("乙")
        self.assertEqual(raw["script"]["options"][0]["fields"][0]["values"], ["甲"])
        self.assertNotIn("options", parser.parse_task_switch_map(raw)["script"][0])

    def test_enum_resource_is_parsed_without_executing_external_code(self):
        content = """raise RuntimeError("must not execute")
class Agents:
    A = Agent(1, "甲")
    B = Agent(2, "乙")
"""
        names = parser.parse_enum_names(content, {"enum": "Agents", "argument": 1})
        choices = parser.parse_resource_choices(names, {"prepend": ["随机"]})
        self.assertEqual(
            [item["physical_name"] for item in choices], ["随机", "甲", "乙"]
        )

    def test_changed_resource_names_raise_recoverable_errors(self):
        source = {"field": "name"}
        for records in [[], {"id": {}}, {"id": {"name": 1}}]:
            with self.subTest(records=records), self.assertRaises(ValueError):
                names = parser.parse_record_names(records, source)
                parser.parse_resource_choices(names, source)

    def test_map_resources_filter_categories_and_omit_unnamed_points(self):
        data = {
            "data": [
                {},
                {
                    "points": [
                        {"type": "domain", "name": "秘境"},
                        {"type": "boss", "name": "首领"},
                        {"type": "domain"},
                        {"type": "domain", "name": ""},
                    ]
                },
            ]
        }
        source = {"path": "tp.json", "category": "domain"}
        self.assertEqual(parser.parse_map_point_names(data, source, "日常"), ["秘境"])
        self.assertEqual(parser.parse_map_point_names(None, source, "日常"), [])
