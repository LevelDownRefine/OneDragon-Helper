"""正式服资料解析、ok-ww 主导的更新门槛与失败重试。"""

import json
import tempfile
import unittest
import urllib.error
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from ruamel.yaml import YAML

from tools import okww_tacet_names as source
from tools import sync_okww_tasks as sync

FIXTURE = Path(__file__).parents[1] / "fixtures/okww_tacet_3_7.json"
STRUCTURE = [4, 5, 5, 7]
EXPECTED_NAMES = [
    "沉心域无音区",
    "烬心域无音区",
    "方擎西峰无音区",
    "玄幽东岳无音区",
    "落日堤屿无音区",
    "冰原运输港无音区",
    "加拉尔冠阶无音区",
    "隐喙深腹无音区",
    "陷足流川无音区",
    "哀恸谷无音区",
    "贝奥海域无音区",
    "黎乔利群岛无音区",
    "槲生半岛无音区",
    "悲叹墓岛无音区",
    "中曲台地无音区",
    "荒石高地无音区Ⅰ",
    "虎口山脉无音区",
    "怨鸟泽无音区",
    "归墟港市无音区",
    "荒石高地无音区Ⅱ",
    "无光之森无音区",
]
EXPECTED_DISPLAY_NAMES = [
    "沉心域",
    "烬心域",
    "方擎西峰",
    "玄幽东岳",
    "落日堤屿",
    "冰原运输港",
    "加拉尔冠阶",
    "隐喙深腹",
    "陷足流川",
    "哀恸谷",
    "贝奥海域",
    "黎乔利群岛",
    "槲生半岛",
    "悲叹墓岛",
    "中曲台地",
    "荒石高地Ⅰ",
    "虎口山脉",
    "怨鸟泽",
    "归墟港市",
    "荒石高地Ⅱ",
    "无光之森",
]
EXPECTED_IDS = [
    30010030,
    30010029,
    30010028,
    30010027,
    30010026,
    30010025,
    30010024,
    30010023,
    30010022,
    30010021,
    30010020,
    30010019,
    30010017,
    30010018,
    30010001,
    30010009,
    30010010,
    30010011,
    30010012,
    30010013,
    30010016,
]


class TestTacetSource(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_released_snapshot_joins_all_names_and_ignores_record_order(self):
        records = list(reversed(self.fixture["records"]))
        records.append({"Secondary": 21})  # 强敌讨伐不是无音清剿。
        ids, names = source.parse_tacet_data(records, self.fixture["texts"], STRUCTURE)
        self.assertEqual(ids, EXPECTED_IDS)
        self.assertEqual(names, EXPECTED_NAMES)

    def test_count_ahead_behind_or_wrong_groups_are_not_truncated_to_fit(self):
        for structure in ([2, 5, 5, 7], [5, 5, 5, 7], [5, 4, 5, 7]):
            with self.subTest(structure=structure), self.assertRaises(ValueError):
                source.parse_tacet_data(
                    self.fixture["records"], self.fixture["texts"], structure
                )

    def test_invalid_or_ambiguous_source_does_not_produce_names(self):
        for fault in (
            "missing_field",
            "duplicate_id",
            "new_sort_tie",
            "interleaved_group",
            "missing_text",
            "empty_name",
            "duplicate_name",
            "duplicate_text",
            "bad_type",
        ):
            with self.subTest(fault=fault):
                records, texts = (
                    deepcopy(self.fixture["records"]),
                    deepcopy(self.fixture["texts"]),
                )
                if fault == "missing_field":
                    del records[0]["SortId"]
                elif fault == "duplicate_id":
                    records[-1]["Id"] = records[-2]["Id"]
                elif fault == "new_sort_tie":
                    records[-1]["SortId"] = records[-2]["SortId"]
                elif fault == "interleaved_group":
                    records[-2]["DetectionTabType"] = 5
                elif fault == "missing_text":
                    texts.pop()
                elif fault == "empty_name":
                    texts[-1]["Content"] = ""
                elif fault == "duplicate_name":
                    texts[-1]["Content"] = texts[-2]["Content"]
                elif fault == "duplicate_text":
                    texts.append(texts[-1])
                else:
                    records[0]["SortId"] = "3"
                with self.assertRaises(ValueError):
                    source.parse_tacet_data(records, texts, STRUCTURE)

    def test_downloads_are_pinned_to_one_release_commit(self):
        with patch.object(
            source,
            "fetch_text",
            side_effect=[
                json.dumps({"default_branch": "3.7"}),
                json.dumps({"sha": "a" * 40}),
                "Status: Release</br>\nGame Version: 3.7.0</br>",
                json.dumps(self.fixture["records"]),
                json.dumps(self.fixture["texts"]),
            ],
        ) as fetch:
            snapshot = source.fetch_tacet_snapshot(STRUCTURE)
        self.assertEqual(snapshot.names, EXPECTED_NAMES)
        self.assertEqual(snapshot.revision, "a" * 40)
        for call in fetch.call_args_list[2:]:
            self.assertIn("/" + "a" * 40 + "/", call.args[0])

    def test_beta_default_branch_is_not_imported(self):
        with (
            patch.object(
                source, "fetch_text", return_value='{"default_branch":"3.8-beta"}'
            ) as fetch,
            self.assertRaisesRegex(ValueError, "正式版本"),
        ):
            source.fetch_tacet_snapshot(STRUCTURE)
        fetch.assert_called_once()


class TestOkwwGate(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.config = self.root / "tasks.yml"
        self.state = self.root / "state.json"
        self.report = self.root / "report.md"
        self.output = self.root / "output"
        self.yaml = YAML()
        for name, value in (
            ("_DUNGEON_PATH", str(self.config)),
            ("_STATE_PATH", str(self.state)),
        ):
            patcher = patch.object(sync, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.structures = {"凝素领域": [2], "无音区": STRUCTURE}
        patcher = patch.object(
            sync, "_fetch_structures", side_effect=lambda: self.structures
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.snapshot = source.TacetSnapshot(
            "a" * 40, "3.7.0", STRUCTURE, EXPECTED_IDS, EXPECTED_NAMES
        )
        self.write_config([str(i) for i in range(1, 22)])

    def write_config(self, names, forgery_count=2):
        categories = []
        for category, labels in (
            ("凝素领域", [f"凝素-{i}" for i in range(forgery_count)]),
            ("无音区", names),
        ):
            categories.append(
                {
                    "display_name": category,
                    "options": {
                        "values": [
                            {"display_name": name, "physical_name": index}
                            for index, name in enumerate(labels, 1)
                        ]
                    },
                }
            )
        categories.append(
            {
                "display_name": "模拟领域",
                "options": {
                    "values": [
                        {"display_name": "贝币", "physical_name": "Shell Credit"}
                    ]
                },
            }
        )
        with self.config.open("w", encoding="utf-8") as stream:
            self.yaml.dump(
                {
                    "ok-ww": [
                        {"display_name": "每日任务", "options": {"values": categories}}
                    ]
                },
                stream,
            )

    def write_state(self, structure=STRUCTURE, ids=EXPECTED_IDS):
        self.state.write_text(
            json.dumps(
                {
                    "okww_structure": structure,
                    "ids": ids,
                    "data_commit": "b" * 40,
                    "game_version": "3.7.0",
                }
            ),
            encoding="utf-8",
        )

    def values(self, category):
        data = self.yaml.load(self.config.read_text(encoding="utf-8"))
        return next(
            row["options"]["values"]
            for row in data["ok-ww"][0]["options"]["values"]
            if row["display_name"] == category
        )

    def test_first_import_fills_existing_placeholders_without_count_growth(self):
        before = self.config.read_bytes()
        with patch.object(
            sync, "fetch_tacet_snapshot", return_value=self.snapshot
        ) as fetch:
            self.assertEqual(sync.main([]), 1)
            self.assertEqual(self.config.read_bytes(), before)
            self.assertFalse(self.state.exists())
            fetch.reset_mock()
            result = sync.main(
                [
                    "--apply",
                    "--report",
                    str(self.report),
                    "--github-output",
                    str(self.output),
                ]
            )
            fetch.assert_called_once_with(STRUCTURE)
        self.assertEqual(result, 0)
        self.assertEqual(
            [row["display_name"] for row in self.values("无音区")],
            EXPECTED_DISPLAY_NAMES,
        )
        self.assertEqual(
            [row["physical_name"] for row in self.values("无音区")], list(range(1, 22))
        )
        self.assertEqual(self.output.read_text(), "changed=true\n")
        self.assertIn("沉心域无音区", self.report.read_text(encoding="utf-8"))
        self.assertEqual(
            self.values("模拟领域"),
            [{"display_name": "贝币", "physical_name": "Shell Credit"}],
        )

    def test_data_updates_alone_never_trigger_a_fetch_or_config_change(self):
        self.write_config(EXPECTED_DISPLAY_NAMES[2:])
        self.write_state([2, 5, 5, 7], EXPECTED_IDS[2:])
        self.structures["无音区"] = [2, 5, 5, 7]
        before = (self.config.read_bytes(), self.state.read_bytes())
        with patch.object(sync, "fetch_tacet_snapshot") as fetch:
            self.assertEqual(sync.main(["--apply"]), 0)
            fetch.assert_not_called()
        self.assertEqual((self.config.read_bytes(), self.state.read_bytes()), before)

    def test_okww_growth_imports_names_then_becomes_idempotent(self):
        self.write_config(EXPECTED_DISPLAY_NAMES[2:])
        self.write_state([2, 5, 5, 7], EXPECTED_IDS[2:])
        with patch.object(
            sync, "fetch_tacet_snapshot", return_value=self.snapshot
        ) as fetch:
            self.assertEqual(sync.main(["--apply"]), 0)
            fetch.assert_called_once_with(STRUCTURE)
            before = (self.config.read_bytes(), self.state.read_bytes())
            fetch.reset_mock()
            self.assertEqual(sync.main(["--apply"]), 0)
            fetch.assert_not_called()
        self.assertEqual((self.config.read_bytes(), self.state.read_bytes()), before)
        self.assertEqual(
            [row["display_name"] for row in self.values("无音区")],
            EXPECTED_DISPLAY_NAMES,
        )

    def test_unready_data_preserves_files_and_retries_next_run(self):
        self.write_config(EXPECTED_DISPLAY_NAMES[2:])
        self.write_state([2, 5, 5, 7], EXPECTED_IDS[2:])
        before = (self.config.read_bytes(), self.state.read_bytes())
        for error in (ValueError("数量不一致"), urllib.error.URLError("offline")):
            with (
                self.subTest(error=type(error).__name__),
                patch.object(sync, "fetch_tacet_snapshot", side_effect=error),
            ):
                with self.assertLogs(sync.logger, level="WARNING") as logs:
                    result = sync.main(
                        [
                            "--apply",
                            "--report",
                            str(self.report),
                            "--github-output",
                            str(self.output),
                        ]
                    )
                self.assertEqual(result, 2)
                self.assertIn(type(error).__name__, logs.output[0])
                self.assertEqual(
                    (self.config.read_bytes(), self.state.read_bytes()), before
                )
        self.assertNotIn("changed=true", self.output.read_text())
        with patch.object(sync, "fetch_tacet_snapshot", return_value=self.snapshot):
            self.assertEqual(sync.main(["--apply"]), 0)
        self.assertEqual(len(self.values("无音区")), 21)

    def test_primary_rollback_does_not_delete_or_advance_state(self):
        self.write_config(EXPECTED_DISPLAY_NAMES)
        self.write_state()
        self.structures = {"凝素领域": [1], "无音区": [2, 5, 5, 7]}
        before = (self.config.read_bytes(), self.state.read_bytes())
        with patch.object(sync, "fetch_tacet_snapshot") as fetch:
            changed, report = sync._sync(True)
            fetch.assert_not_called()
        self.assertFalse(changed)
        self.assertIn("不删除", report)
        self.assertEqual((self.config.read_bytes(), self.state.read_bytes()), before)

    def test_forgery_growth_does_not_query_unchanged_tacet_data(self):
        self.write_config(EXPECTED_DISPLAY_NAMES)
        self.write_state()
        self.structures["凝素领域"] = [3]
        with patch.object(sync, "fetch_tacet_snapshot") as fetch:
            self.assertEqual(sync.main(["--apply"]), 0)
            fetch.assert_not_called()
        self.assertEqual(
            self.values("凝素领域"),
            [
                {"display_name": "1", "physical_name": 1},
                {"display_name": "凝素-0", "physical_name": 2},
                {"display_name": "凝素-1", "physical_name": 3},
            ],
        )
        self.assertEqual(
            [row["display_name"] for row in self.values("无音区")],
            EXPECTED_DISPLAY_NAMES,
        )

    def test_same_count_group_change_still_requires_source_validation(self):
        self.write_state([3, 6, 5, 7])
        with patch.object(
            sync, "fetch_tacet_snapshot", return_value=self.snapshot
        ) as fetch:
            self.assertEqual(sync.main(["--apply"]), 0)
            fetch.assert_called_once_with(STRUCTURE)

    def test_reordered_existing_ids_require_review_without_writing(self):
        self.write_state([2, 5, 5, 7], list(reversed(EXPECTED_IDS[2:])))
        self.write_config(EXPECTED_DISPLAY_NAMES[2:])
        before = (self.config.read_bytes(), self.state.read_bytes())
        with (
            patch.object(sync, "fetch_tacet_snapshot", return_value=self.snapshot),
            self.assertLogs(sync.logger, level="WARNING"),
        ):
            self.assertEqual(sync.main(["--apply"]), 2)
        self.assertEqual((self.config.read_bytes(), self.state.read_bytes()), before)


if __name__ == "__main__":
    unittest.main()
