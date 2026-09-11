"""任务声明读取不依赖脚本安装、资源展开或界面数据。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.config import task_config
from src.utils.utils_yaml import dump_yaml


class TestTaskConfig(unittest.TestCase):
    def test_task_and_option_names_follow_the_same_fallback_rule(self):
        for validate in (
            task_config.validate_daily_definitions,
            task_config.validate_weekly_definitions,
        ):
            for physical in (None, "native_task"):
                node = {"display_name": "展示名"}
                if physical is not None:
                    node["physical_name"] = physical
                validate("example", [node])
                task_config.validate_options([node], "example")
                self.assertEqual(
                    task_config.get_physical_name(node), physical or "展示名"
                )

    def test_task_physical_names_cannot_collide_with_display_fallbacks(self):
        declarations = [
            {"display_name": "native"},
            {"display_name": "另一个展示名", "physical_name": "native"},
        ]
        for validate in (
            task_config.validate_daily_definitions,
            task_config.validate_weekly_definitions,
        ):
            with self.assertRaisesRegex(AssertionError, "任务物理名重复"):
                validate("example", declarations)

    def test_obsolete_names_and_invalid_disable_capability_are_rejected(self):
        for validate in (
            task_config.validate_daily_definitions,
            task_config.validate_weekly_definitions,
        ):
            for extra in (
                {"name": "old"},
                {"native_task": "old"},
                {"value": "old"},
                {"value_field": "old"},
                {"options_defaults": {}},
                {"physical_name": ""},
                {"physical_name": True},
                {"allow_disable": "false"},
            ):
                with self.subTest(extra=extra), self.assertRaises(AssertionError):
                    validate("example", [{"display_name": "任务", **extra}])

    def test_daily_and_weekly_share_option_values_and_source_paths(self):
        for validate in (
            task_config.validate_daily_definitions,
            task_config.validate_weekly_definitions,
        ):
            with self.subTest(validate=validate.__name__):
                validate(
                    "example",
                    [
                        {
                            "display_name": "资源",
                            "options": {
                                "values": [
                                    {"display_name": "原生名"},
                                    {"display_name": "别名", "physical_name": 2},
                                ]
                            },
                        }
                    ],
                )
                validate(
                    "example",
                    [
                        {
                            "display_name": "资源",
                            "options": {"source": {"path": "assets/stages.json"}},
                        }
                    ],
                )
                for options in (
                    ["旧格式"],
                    [{"display_name": "重复"}, {"display_name": "重复"}],
                    [{"display_name": "错误", "physical_name": True}],
                ):
                    with (
                        self.subTest(options=options),
                        self.assertRaises(AssertionError),
                    ):
                        validate(
                            "example",
                            [{"display_name": "资源", "options": {"values": options}}],
                        )
                for source in (
                    "",
                    {},
                    {"path": None},
                    "../stages.json",
                    "C:/stages.json",
                ):
                    with self.subTest(source=source), self.assertRaises(AssertionError):
                        validate(
                            "example",
                            [{"display_name": "资源", "options": {"source": source}}],
                        )

    def test_static_and_resource_options_cannot_silently_override_each_other(self):
        for validate in (
            task_config.validate_daily_definitions,
            task_config.validate_weekly_definitions,
        ):
            with (
                self.subTest(validate=validate.__name__),
                self.assertRaisesRegex(AssertionError, "不能同时声明"),
            ):
                validate(
                    "example",
                    [
                        {
                            "display_name": "资源",
                            "options": {
                                "values": [{"display_name": "A"}],
                                "source": {"path": "stages.json"},
                            },
                        }
                    ],
                )
        with self.assertRaisesRegex(AssertionError, "不能同时声明"):
            task_config.validate_daily_definitions(
                "example",
                [
                    {
                        "display_name": "资源",
                        "options": {
                            "values": [
                                {
                                    "display_name": "分类",
                                    "options": {
                                        "values": [],
                                        "source": {"path": "stages.json"},
                                    },
                                }
                            ]
                        },
                    }
                ],
            )

    def test_leaf_aliases_must_have_unique_native_values(self):
        options = [
            {"display_name": "A"},
            {"display_name": "别名", "physical_name": "A"},
        ]
        with self.assertRaisesRegex(AssertionError, "原生值重复"):
            task_config.validate_weekly_definitions(
                "example", [{"display_name": "周本", "options": {"values": options}}]
            )
        with self.assertRaisesRegex(AssertionError, "原生值重复"):
            task_config.validate_daily_definitions(
                "example",
                [
                    {
                        "display_name": "日常",
                        "options": {
                            "values": [
                                {"display_name": "分类", "options": {"values": options}}
                            ]
                        },
                    }
                ],
            )

    def test_uninstalled_script_keeps_resource_declarations_unexpanded(self):
        definition = {
            "display_name": "资源",
            "options": {"source": {"path": "missing/stages.json"}},
        }
        for kind, load in (
            ("daily", task_config.load_daily_map),
            ("weekly", task_config.load_weekly_map),
        ):
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / f"{kind}_list.yml"
                dump_yaml(
                    str(path), {"uninstalled_script": [{**definition, "type": kind}]}
                )
                with patch.object(
                    task_config,
                    "get_task_list_yml_path_under_root",
                    return_value=str(path),
                ):
                    self.assertEqual(
                        load(), {"uninstalled_script": [{**definition, "type": kind}]}
                    )
                self.assertEqual(list(Path(tmp).iterdir()), [path])

    def test_task_properties_cannot_appear_on_option_nodes(self):
        for extra in (
            {"type": "daily"},
            {"key": "native_task"},
            {"allow_disable": True},
        ):
            for depth in (1, 2, 3):
                child = {"display_name": "末项", **extra}
                for level in range(depth):
                    child = {"display_name": str(level), "options": {"values": [child]}}
                with (
                    self.subTest(extra=extra, depth=depth),
                    self.assertRaisesRegex(AssertionError, "未知选项声明"),
                ):
                    task_config.validate_daily_definitions("example", [child])

    def test_option_group_requires_one_source_of_values_at_any_depth(self):
        for group in (
            {},
            {"key": "stage"},
            {"values": [], "source": {"path": "a.json"}},
            {"values": [], "key": False},
            {"values": [], "type": "weekly"},
            {"values": [], "items": []},
            {"values": [], "field": "stage"},
        ):
            for depth in (0, 1, 2):
                task = {"display_name": "任务", "options": group}
                for level in range(depth):
                    task = {"display_name": str(level), "options": {"values": [task]}}
                with (
                    self.subTest(group=group, depth=depth),
                    self.assertRaises(AssertionError),
                ):
                    task_config.validate_weekly_definitions("example", [task])

    def test_recursive_resource_expansion_preserves_bindings_and_schema(self):
        from copy import deepcopy

        from src.service.app_service import get_daily_map

        raw = {
            "example": [
                {
                    "display_name": "任务",
                    "type": "daily",
                    "key": "task_flag",
                    "options": {
                        "key": "first",
                        "values": [
                            {
                                "display_name": "分组",
                                "options": {
                                    "key": "second",
                                    "values": [
                                        {
                                            "display_name": "子分组",
                                            "options": {
                                                "key": "third",
                                                "source": {
                                                    "path": "stages.json",
                                                    "category": "native",
                                                },
                                            },
                                        }
                                    ],
                                },
                            }
                        ],
                    },
                }
            ]
        }
        original = deepcopy(raw)
        with (
            patch("src.service.app_service.load_daily_map", return_value=raw),
            patch(
                "src.service.app_service.get_task_options", return_value=["A"]
            ) as read,
        ):
            expanded = get_daily_map()
        task_config.validate_daily_definitions("example", expanded["example"])
        read.assert_called_once_with("example", "native", "stages.json")
        node = expanded["example"][0]
        self.assertEqual(node["key"], "task_flag")
        for key in ("first", "second", "third"):
            self.assertEqual(node["options"]["key"], key)
            self.assertNotIn("source", node["options"])
            node = node["options"]["values"][0]
        self.assertEqual(node, {"display_name": "A"})
        self.assertEqual(raw, original)


if __name__ == "__main__":
    unittest.main()
