"""日常配置字段、原生资源分类与普通位置参数的公共契约。"""

import unittest
from copy import deepcopy
from unittest.mock import patch

from src.config import set_config as adapters
from src.config.set_config import (
    EndfieldConfig,
    GenshinConfig,
    WutheringWavesConfig,
    set_config,
)
from src.config.task_config import (
    validate_daily_definitions,
)
from src.service.app_service import build_task_item, get_daily_map


class TestDungeonSchema(unittest.TestCase):
    def _register(self, parent, definitions):
        validate_daily_definitions(parent._script_name, definitions)
        cls = type(
            "Example",
            (parent,),
            {
                "_script_name": parent._script_name,
                "_config_rel_path": parent._config_rel_path,
                "_backup_paths": parent._backup_paths,
                "_game_config_rel_path": parent._game_config_rel_path,
            },
        )
        with (
            patch.object(
                adapters,
                "load_daily_map",
                return_value={parent._script_name: definitions},
            ),
            patch.dict(adapters._CONFIGS),
        ):
            return adapters.register(cls)

    def test_native_source_value_is_independent_of_label_and_written_value(self):
        daily = {
            "display_name": "每日任务",
            "options": {
                "values": [
                    {
                        "display_name": "新展示分组",
                        "options": {
                            "source": {
                                "path": "custom/domains.json",
                                "category": "FutureDomain",
                            },
                            "key": "DomainName",
                        },
                    }
                ]
            },
        }
        original = deepcopy(daily)
        resources = {
            "data": [
                {
                    "points": [
                        {"type": "FutureDomain", "name": "未来秘境"},
                        {"type": "OtherDomain", "name": "其他秘境"},
                    ]
                }
            ]
        }
        with (
            patch(
                "src.service.app_service.load_daily_map",
                return_value={"BetterGI": [daily]},
            ),
            patch(
                "src.config.set_config.load_game_config", return_value=resources
            ) as read,
        ):
            expanded = get_daily_map()["BetterGI"][0]
        read.assert_called_once_with("BetterGI", "custom/domains.json")
        self.assertEqual(daily, original)
        self.assertEqual(
            expanded["options"]["values"][0]["options"]["values"],
            [{"display_name": "未来秘境"}],
        )
        config = {"DomainName": "旧副本", "other": True}
        with (
            patch.object(GenshinConfig, "_load", return_value=config),
            patch.object(GenshinConfig, "_save") as save,
            patch.object(GenshinConfig, "_daily_configs", {"每日任务": daily}),
        ):
            GenshinConfig().set_daily_task("每日任务", "新展示分组", "未来秘境")
            selection = GenshinConfig()._read_daily_task("每日任务")
        save.assert_called_once_with({"DomainName": "未来秘境", "other": True})
        self.assertEqual(selection, ("未来秘境", None))
        self.assertEqual(
            build_task_item(expanded, selection)["selection_label"], "未来秘境"
        )

    def test_named_grouped_dailies_write_independently(self):
        definitions = [
            {
                "display_name": daily,
                "options": {
                    "values": [
                        {
                            "display_name": "分类",
                            "options": {"key": field, "values": []},
                        },
                        {
                            "display_name": "别的展示名",
                            "options": {"key": field, "values": []},
                        },
                    ]
                },
            }
            for daily, field in (("资源", "resource_stage"), ("清理", "cleanup_stage"))
        ]
        for parent in (GenshinConfig, EndfieldConfig):
            with self.subTest(parent=parent.__name__):
                cls = self._register(parent, list(reversed(definitions)))
                config = {
                    "resource_stage": "旧本",
                    "cleanup_stage": "旧本",
                    "other": True,
                }
                with (
                    patch.object(cls, "_load", return_value=config),
                    patch.object(cls, "_save"),
                ):
                    cfg = cls()
                    cfg.set_daily_task("清理", "分类", "清理副本")
                    cfg.set_daily_task("资源", "新原生副本")
                    self.assertEqual(cfg._read_daily_task("清理"), ("清理副本", None))
                    self.assertEqual(cfg._read_daily_task("资源"), ("新原生副本", None))
                self.assertEqual(
                    config,
                    {
                        "resource_stage": "新原生副本",
                        "cleanup_stage": "清理副本",
                        "other": True,
                    },
                )

    def test_ambiguous_writable_values_cannot_be_read_or_saved(self):
        definitions = [
            {
                "display_name": "资源",
                "options": {
                    "key": "kind",
                    "values": [
                        {"display_name": "A", "physical_name": "same"},
                        {"display_name": "B", "physical_name": "same"},
                    ],
                },
            }
        ]
        with self.assertRaisesRegex(AssertionError, "无法唯一反读"):
            self._register(WutheringWavesConfig, definitions)

    def test_grouped_adapters_honor_explicit_bindings(self):
        for parent in (GenshinConfig, EndfieldConfig):
            definition = {
                "display_name": "资源",
                "options": {
                    "key": "kind",
                    "values": [
                        {
                            "display_name": "分类",
                            "physical_name": "native",
                            "options": {
                                "key": "stage",
                                "values": [{"display_name": "新副本"}],
                            },
                        }
                    ],
                },
            }
            cls = self._register(parent, [definition])
            config = {"kind": "old", "stage": "旧副本"}
            with self.subTest(parent=parent.__name__):
                task = cls()
                task._daily_configs = dict(task._daily_configs)
                task._update_daily_task(config, "资源", "分类", "新副本")
                self.assertEqual(config, {"kind": "native", "stage": "新副本"})
                self.assertEqual(
                    task._read_daily_config(config, "资源"), ("分类", "新副本")
                )

    def test_group_without_child_cannot_write_its_display_name(self):
        for cls, field, group in (
            (GenshinConfig, "DomainName", "圣遗物"),
            (EndfieldConfig, "体力本", "干员养成"),
        ):
            with self.subTest(cls=cls.__name__):
                config = {field: "旧副本", "other": True}
                with (
                    patch.object(cls, "_load", return_value=config),
                    patch.object(cls, "_save") as save,
                    self.assertRaisesRegex(AssertionError, "具体副本"),
                ):
                    cls().set_daily_task("每日任务", group)
                save.assert_not_called()
                self.assertEqual(config, {field: "旧副本", "other": True})

    def test_tasks_without_selection_fields_do_not_read_native_config(self):
        for parent in (GenshinConfig, EndfieldConfig):
            cls = self._register(
                parent, [{"display_name": "资源", "options": {"values": []}}]
            )
            with (
                self.subTest(parent=parent.__name__),
                patch.object(cls, "_load") as load,
            ):
                self.assertEqual(cls()._read_daily_task("资源"), (None, None))
                load.assert_not_called()
                config = {"other": True}
                with self.assertRaisesRegex(AssertionError, "options.key"):
                    cls()._update_daily_task(config, "资源", "新副本")
                self.assertEqual(config, {"other": True})

    def test_missing_source_does_not_offer_group_as_a_leaf(self):
        daily = {
            "display_name": "资源",
            "options": {
                "key": "stage",
                "values": [
                    {
                        "display_name": "分类",
                        "options": {
                            "source": {
                                "path": "missing.json",
                                "category": "NativeCategory",
                            },
                            "values": [],
                        },
                    }
                ],
            },
        }
        row = build_task_item(daily, (None, None))
        self.assertEqual(row["options"], [])
        self.assertEqual(row["selection_label"], "选择副本")
        self.assertEqual(
            build_task_item(daily, ("旧副本", None))["selection_label"], "旧副本"
        )

    def test_grouped_selection_rejects_invalid_child_before_saving(self):
        for cls, field, group in (
            (GenshinConfig, "DomainName", "圣遗物"),
            (EndfieldConfig, "体力本", "干员养成"),
        ):
            for sequence in ("", 1, True):
                config = {field: "旧副本", "other": True}
                with (
                    self.subTest(cls=cls.__name__, sequence=sequence),
                    patch.object(cls, "_load", return_value=config),
                    patch.object(cls, "_save") as save,
                    self.assertRaisesRegex(
                        AssertionError, "非空字符串|类型不一致|字符串或整数"
                    ),
                ):
                    cls().set_daily_task("每日任务", group, sequence)
                save.assert_not_called()
                self.assertEqual(config, {field: "旧副本", "other": True})

    def test_source_value_defaults_to_name_and_preserves_native_type(self):
        for extra, expected in (
            ({}, "分类"),
            ({"physical_name": "NativeCategory"}, "NativeCategory"),
            ({"physical_name": 3}, 3),
            (
                {
                    "physical_name": "written_value",
                    "options": {
                        "source": {"path": "data.json", "category": "resource_category"}
                    },
                },
                "resource_category",
            ),
        ):
            daily = {
                "display_name": "资源",
                "options": {
                    "values": [
                        {
                            "display_name": "分类",
                            "options": {"source": {"path": "data.json"}},
                            **extra,
                        }
                    ]
                },
            }
            with (
                self.subTest(extra=extra),
                patch(
                    "src.service.app_service.load_daily_map",
                    return_value={"example": [daily]},
                ),
                patch(
                    "src.service.app_service.get_task_options", return_value=[]
                ) as read,
            ):
                get_daily_map()
            read.assert_called_once_with("example", expected, "data.json")

    def test_native_dungeon_equal_to_category_value_reads_as_a_dungeon(self):
        definition = {
            "display_name": "资源",
            "options": {
                "values": [
                    {
                        "display_name": "分类别名",
                        "physical_name": "NativeCategory",
                        "options": {"key": "stage", "values": []},
                    }
                ]
            },
        }
        cls = self._register(GenshinConfig, [definition])
        with patch.object(cls, "_load", return_value={"stage": "NativeCategory"}):
            self.assertEqual(cls()._read_daily_task("资源"), ("NativeCategory", None))

    def test_expanded_resources_are_validated_before_building_menus(self):
        declarations = {
            "example": [
                {
                    "display_name": "资源",
                    "options": {
                        "values": [
                            {
                                "display_name": "分类",
                                "options": {"source": {"path": "stages.json"}},
                            }
                        ]
                    },
                }
            ]
        }
        for names in ("副本", [1], ["副本", None], [""]):
            with (
                self.subTest(names=names),
                patch(
                    "src.service.app_service.load_daily_map",
                    return_value=declarations,
                ),
                patch("src.service.app_service.get_task_options", return_value=names),
                self.assertRaisesRegex(AssertionError, "名称列表"),
            ):
                get_daily_map()
        self.assertNotIn(
            "values", declarations["example"][0]["options"]["values"][0]["options"]
        )

    def test_section_is_rejected_at_every_declaration_level(self):
        definitions = [
            {"display_name": "资源", "section": "native"},
            {
                "display_name": "资源",
                "options_defaults": {"section": "native"},
                "options": {"values": []},
            },
            {
                "display_name": "资源",
                "options": {"values": [{"display_name": "材料", "section": "native"}]},
            },
            {
                "display_name": "资源",
                "options": {
                    "values": [
                        {
                            "display_name": "材料",
                            "options": {
                                "values": [
                                    {"display_name": "目标", "section": "native"}
                                ]
                            },
                        }
                    ]
                },
            },
        ]
        for definition in definitions:
            with self.subTest(definition=definition), self.assertRaises(AssertionError):
                validate_daily_definitions("example", [definition])

    def test_public_set_config_accepts_positional_daily_name(self):
        config = {"DomainName": "旧副本"}
        with (
            patch.object(GenshinConfig, "_load", return_value=config),
            patch.object(GenshinConfig, "_save") as save,
        ):
            set_config("BetterGI", "圣遗物", "新副本", None, "每日任务")
        save.assert_called_once_with({"DomainName": "新副本"})

    def test_source_schema_rejects_missing_or_mistyped_fields(self):
        for source in (
            "",
            "../data.json",
            "C:/data.json",
            {},
            {"path": ""},
            {"path": "data.json", "key": 1},
            {"path": "data.json", "key": ""},
            {"path": "data.json", "type": "Typo"},
        ):
            with self.subTest(source=source), self.assertRaises(AssertionError):
                validate_daily_definitions(
                    "example",
                    [
                        {
                            "display_name": "资源",
                            "options": {
                                "values": [
                                    {
                                        "display_name": "分类",
                                        "options": {"source": source},
                                    }
                                ]
                            },
                        }
                    ],
                )

    def test_old_schema_fields_do_not_silently_disable_bindings(self):
        for extra in (
            {"field": "kind"},
            {"sequence_field": "target"},
            {"sub_options": []},
            {"sub_options_source": "data.json"},
            {"sub_value_field": "target"},
        ):
            with (
                self.subTest(extra=extra),
                self.assertRaisesRegex(AssertionError, "未知选项声明"),
            ):
                validate_daily_definitions(
                    "example",
                    [
                        {
                            "display_name": "资源",
                            "options": {"values": [{"display_name": "分类", **extra}]},
                        }
                    ],
                )

    def test_child_name_and_unknown_fields_are_validated(self):
        for child in (
            {"display_name": " ", "physical_name": 1},
            {"display_name": "目标", "physical_name": 1, "field": "ignored"},
        ):
            with self.subTest(child=child), self.assertRaises(AssertionError):
                validate_daily_definitions(
                    "example",
                    [
                        {
                            "display_name": "资源",
                            "options": {
                                "key": "kind",
                                "values": [
                                    {
                                        "display_name": "分类",
                                        "options": {"values": [child]},
                                    }
                                ],
                            },
                        }
                    ],
                )
