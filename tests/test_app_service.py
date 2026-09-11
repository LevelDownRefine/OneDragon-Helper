"""任务展示服务：展开本地资源并合并当前选择。"""

import os
import tempfile
import unittest
from copy import deepcopy
from unittest.mock import call, patch

from src.service.app_service import AppService, get_daily_map, get_weekly_map
from src.utils.utils_yaml import dump_yaml_file


class TestGetWeeklyDefs(unittest.TestCase):
    """get_weekly_map：静态 options 保持，options.source 运行期从外部读取/降级。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.weekly_list_path = os.path.join(self.tmp.name, "task_list.yml")
        patcher = patch(
            "src.config.task_config.get_task_list_yml_path_under_root",
            return_value=self.weekly_list_path,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _write(self, data):
        data = {
            script: [{**task, "type": "weekly"} for task in tasks]
            for script, tasks in data.items()
        }
        dump_yaml_file(self.weekly_list_path, data)

    def test_static_dungeons_untouched(self):
        """带 options（无 options.source）的项保持原样，不触发外部读取。"""
        self._write(
            {
                "March7th-Launcher": [
                    {
                        "display_name": "历战余响",
                        "options": {
                            "values": [
                                {"display_name": "无"},
                                {"display_name": "铁骸的锈冢"},
                            ]
                        },
                    }
                ]
            }
        )
        with patch("src.service.app_service.get_task_options") as mock_ext:
            defs = get_weekly_map("March7th-Launcher")
        self.assertEqual(
            defs[0]["options"]["values"],
            [{"display_name": "无"}, {"display_name": "铁骸的锈冢"}],
        )
        mock_ext.assert_not_called()  # 无 options.source 不读外部

    def test_external_source_filled_when_reachable(self):
        """options.source=assets/config/instance_names.json 且外部可读 → 用外部副本清单填充。"""
        self._write(
            {
                "March7th-Launcher": [
                    {
                        "display_name": "历战余响",
                        "options": {
                            "source": {"path": "assets/config/instance_names.json"}
                        },
                    }
                ]
            }
        )
        names = ["无", "铁骸的锈冢", "晨昏的回眸"]
        with patch(
            "src.service.app_service.get_task_options", return_value=names
        ) as mock_ext:
            defs = get_weekly_map("March7th-Launcher")
        mock_ext.assert_called_once_with(
            "March7th-Launcher", "历战余响", "assets/config/instance_names.json"
        )
        self.assertEqual(
            defs[0]["options"]["values"],
            [{"display_name": name} for name in names],
        )
        self.assertTrue(defs[0]["options"]["values"])  # 供 GUI 推导 has_options

    def test_external_source_empty_when_unreachable(self):
        """外部读不到（返回 None）→ 降级 options=[]，该周常无需选副本。"""
        self._write(
            {
                "March7th-Launcher": [
                    {
                        "display_name": "历战余响",
                        "options": {
                            "source": {"path": "assets/config/instance_names.json"}
                        },
                    }
                ]
            }
        )
        with patch("src.service.app_service.get_task_options", return_value=None):
            defs = get_weekly_map("March7th-Launcher")
        self.assertEqual(defs[0]["options"]["values"], [])

    def test_unknown_script_returns_empty(self):
        """未知脚本 → get_weekly_map 返回空列表（不抛错、不读外部）。"""
        self._write({"March7th-Launcher": [{"display_name": "货币战争"}]})
        self.assertEqual(get_weekly_map("不存在"), [])


class TestGetDungeonMap(unittest.TestCase):
    """get_daily_map：静态 options 保持，options.source 运行期从外部读取/降级。"""

    def test_static_sequences_untouched(self):
        """带 options（无 options.source）的项保持原样，不触发外部读取。"""
        raw = {
            "ok-ef": [
                {
                    "display_name": "每日任务",
                    "options": {
                        "values": [
                            {
                                "display_name": "干员养成",
                                "options": {
                                    "values": [
                                        {
                                            "display_name": "干员经验",
                                            "physical_name": "干员经验",
                                        }
                                    ]
                                },
                            }
                        ]
                    },
                }
            ]
        }
        with (
            patch("src.service.app_service.load_daily_map", return_value=raw),
            patch("src.service.app_service.get_task_options") as mock_ext,
        ):
            result = get_daily_map()
        self.assertEqual(
            result["ok-ef"][0]["options"]["values"][0]["options"]["values"],
            raw["ok-ef"][0]["options"]["values"][0]["options"]["values"],
        )
        mock_ext.assert_not_called()  # 无 options.source 不读外部

    def test_fills_sequences_from_options_source(self):
        """带 options.source 的声明项，其二级序列由 get_task_options 运行期填充。"""
        raw = {
            "ok-ef": [
                {
                    "display_name": "每日任务",
                    "options": {
                        "values": [
                            {"display_name": "培养目标"},
                            {
                                "display_name": "能量淤积点",
                                "options": {
                                    "source": {
                                        "path": "data/apps/ok-ef/working/assets/data/world_map.json"
                                    }
                                },
                            },
                        ]
                    },
                }
            ]
        }
        with (
            patch("src.service.app_service.load_daily_map", return_value=raw),
            patch(
                "src.service.app_service.get_task_options",
                return_value=["枢纽区", "武陵城"],
            ) as mock_ext,
        ):
            result = get_daily_map()
        # 培养目标（无 options.source）保持无序列
        self.assertEqual(
            result["ok-ef"][0]["options"]["values"][0].get("options"), None
        )
        # 带 options.source 的项被填充为 {name,value} 序列
        seqs = result["ok-ef"][0]["options"]["values"][1]["options"]["values"]
        self.assertEqual(
            seqs,
            [
                {"display_name": "枢纽区"},
                {"display_name": "武陵城"},
            ],
        )
        mock_ext.assert_called_once_with(
            "ok-ef", "能量淤积点", "data/apps/ok-ef/working/assets/data/world_map.json"
        )

    def test_options_source_unreachable_degrades_to_empty(self):
        """options.source 读不到（get_task_options 返回 []）→ 降级为空序列。"""
        raw = {
            "ok-ef": [
                {
                    "display_name": "每日任务",
                    "options": {
                        "values": [
                            {
                                "display_name": "能量淤积点",
                                "options": {
                                    "source": {
                                        "path": "data/apps/ok-ef/working/assets/data/world_map.json"
                                    }
                                },
                            }
                        ]
                    },
                }
            ]
        }
        with (
            patch("src.service.app_service.load_daily_map", return_value=raw),
            patch("src.service.app_service.get_task_options", return_value=[]),
        ):
            result = get_daily_map()
        self.assertEqual(
            result["ok-ef"][0]["options"]["values"][0]["options"]["values"], []
        )


class TestTaskItems(unittest.TestCase):
    def test_weekly_rows_preserve_order_and_only_read_selectable_tasks(self):
        definitions = [
            {"display_name": "开关任务"},
            {"display_name": "周本甲", "options": {"values": [{"display_name": "A"}]}},
            {"display_name": "资源缺失", "options": {"values": []}},
            {"display_name": "周本乙", "options": {"values": [{"display_name": "B"}]}},
        ]
        original = deepcopy(definitions)
        service = AppService()
        with (
            patch.object(service, "get_weekly_map", return_value=definitions),
            patch(
                "src.service.app_service.get_weekly_task",
                side_effect=[("未维护的原生副本", None), (None, None)],
            ) as read,
        ):
            rows = service.get_weekly_items("example")
        self.assertEqual(
            [row["name"] for row in rows], [d["display_name"] for d in definitions]
        )
        self.assertEqual(
            [row["selection_label"] for row in rows],
            ["", "未维护的原生副本", "", "选择副本"],
        )
        self.assertEqual(
            [row["has_options"] for row in rows], [False, True, False, True]
        )
        self.assertEqual(
            read.call_args_list, [call("example", "周本甲"), call("example", "周本乙")]
        )
        rows[1]["name"] = "界面副本"
        self.assertEqual(definitions, original)

    def test_weekly_refresh_reads_latest_selection(self):
        service = AppService()
        with (
            patch.object(
                service,
                "get_weekly_map",
                return_value=[
                    {
                        "display_name": "周本",
                        "options": {
                            "values": [{"display_name": "A"}, {"display_name": "B"}]
                        },
                    }
                ],
            ),
            patch(
                "src.service.app_service.get_weekly_task",
                side_effect=[("A", None), ("B", None)],
            ),
        ):
            self.assertEqual(
                service.get_weekly_items("example")[0]["selection_label"], "A"
            )
            self.assertEqual(
                service.get_weekly_items("example")[0]["selection_label"], "B"
            )

    def test_daily_refresh_preserves_cached_menu_and_optional_native_value(self):
        definitions = [
            {
                "display_name": "资源",
                "options": {
                    "values": [
                        {
                            "display_name": "材料",
                            "options": {"values": [{"display_name": "高级"}]},
                        }
                    ]
                },
            }
        ]
        original = deepcopy(definitions)
        service = AppService()
        with patch(
            "src.service.app_service.get_daily_task",
            side_effect=[("材料", "高级"), ("新副本", None)],
        ):
            first = service.get_daily_items("example", definitions)
            self.assertEqual(first[0]["selection_label"], "高级")
            first[0]["options"][0]["options"].clear()
            second = service.get_daily_items("example", definitions)
        self.assertEqual(second[0]["selection_label"], "新副本")
        self.assertEqual(
            second[0]["options"][0]["options"],
            [{"name": "高级", "value": "高级"}],
        )
        self.assertEqual(definitions, original)

    def test_daily_and_weekly_sources_share_expansion_contract(self):
        daily = {"display_name": "日常", "options": {"source": {"path": "daily.json"}}}
        weekly = {
            "display_name": "周常",
            "options": {"source": {"path": "weekly.json"}},
        }
        with (
            patch(
                "src.service.app_service.load_daily_map",
                return_value={"example": [daily]},
            ),
            patch(
                "src.service.app_service.load_weekly_map",
                return_value={"example": [weekly]},
            ),
            patch(
                "src.service.app_service.get_task_options", return_value=["A", "B"]
            ) as read,
        ):
            daily_options = get_daily_map()["example"][0]["options"]["values"]
            weekly_options = get_weekly_map("example")[0]["options"]["values"]
        self.assertEqual(
            daily_options,
            [
                {"display_name": "A"},
                {"display_name": "B"},
            ],
        )
        self.assertEqual(daily_options, weekly_options)
        self.assertEqual(
            read.call_args_list,
            [
                call("example", "日常", "daily.json"),
                call("example", "周常", "weekly.json"),
            ],
        )
        self.assertNotIn("values", daily["options"])
        self.assertNotIn("values", weekly["options"])


if __name__ == "__main__":
    unittest.main()
