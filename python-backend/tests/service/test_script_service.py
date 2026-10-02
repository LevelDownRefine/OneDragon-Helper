"""脚本管理的输入校验、跨配置保存与失败边界。"""

import json
import os
import tempfile
import unittest
from dataclasses import replace
from functools import cache
from pathlib import Path
from unittest.mock import Mock, patch

from src.config import set_config
from src.service import script_service
from src.service.app_service import AppService
from src.service.script_service import InvalidScript, ScriptEdit, validate_edit
from src.utils import utils_config, utils_weekly
from src.utils.utils_sub_config import DEFAULT_RUN_TIMEOUT, get_script_name
from src.utils.utils_yaml import dump_yaml_file, load_yaml


class ScriptServiceTestBase(unittest.TestCase):
    def setUp(self):
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.config = directory / "config.yml"
        self.weekly = directory / "weekly.yml"
        for module, name, path in (
            (utils_config, "require_config_yml_path", self.config),
            (utils_config, "get_config_yml_path_under_root", self.config),
            (utils_weekly, "get_weekly_yml_path_under_root", self.weekly),
        ):
            self.enterContext(patch.object(module, name, return_value=str(path)))
        self.init = self.enterContext(patch.object(script_service, "init_config"))
        self.switch = Mock()
        self.switch_factory = self.enterContext(
            patch.object(script_service, "task_switch_of", return_value=self.switch)
        )
        self.service = AppService()
        self._seed(self.edit())

    @staticmethod
    def edit(**patch_fields):
        return ScriptEdit(
            script_name="BetterGI",
            display_name="原神",
            config_patch={
                "script_path": "C:/old/BetterGI.exe",
                "script_type": "external",
                "script_arguments": "",
                "check_done": "script_closed",
                "game_process_name": "YuanShen.exe",
                "game_path": "",
                "game_arguments": "",
                "kill_script_after_done": True,
                "kill_game_after_done": True,
                "block": True,
                **patch_fields,
            },
            weekly_timeouts=[60] * 7,
            switches={"任务": False},
        )

    def _seed(self, edit):
        dump_yaml_file(
            str(self.config),
            {
                "script_list": [
                    {
                        "display_name": edit.display_name,
                        **edit.config_patch,
                        "other_field": "保留",
                    }
                ]
            },
        )
        dump_yaml_file(
            str(self.weekly),
            {
                "weekly_start": {edit.script_name: {"周常": 3}},
                "weekly_timeouts": {edit.script_name: [60] * 7},
            },
        )


class TestScriptEdit(ScriptServiceTestBase):
    def test_options_and_switches_save_together_in_same_native_file(self):
        from src.config.task_options import TaskOptions
        from src.config.task_switch import TaskSwitch

        native = self.config.parent / "native.json"
        native.write_text(
            json.dumps(
                {
                    "TaskDefinitions": {"id": "任务"},
                    "TaskEnabledList": {"id": True},
                    "country": "蒙德",
                    "other": 7,
                }
            ),
            encoding="utf-8",
        )
        options = TaskOptions(
            "BetterGI",
            [
                {
                    "display_name": "领奖",
                    "config": "native.json",
                    "fields": [
                        {
                            "id": "country",
                            "display_name": "地区",
                            "keys": ["country"],
                            "type": "choice",
                            "values": ["蒙德", "枫丹"],
                        }
                    ],
                }
            ],
        )
        switch = TaskSwitch(
            "BetterGI",
            [
                {
                    "config": "native.json",
                    "tasks_key": "TaskDefinitions",
                    "enabled_key": "TaskEnabledList",
                }
            ],
        )
        with (
            patch(
                "src.config.task_options.get_script_root_dir",
                return_value=str(native.parent),
            ),
            patch(
                "src.utils.utils_sub_config.get_script_root_dir",
                return_value=str(native.parent),
            ),
            patch.object(script_service, "task_options_of", return_value=options),
            patch.object(script_service, "task_switch_of", return_value=switch),
        ):
            self.service.update_script(
                replace(self.edit(), task_options={"country": "枫丹"})
            )
        actual = json.loads(native.read_text(encoding="utf-8"))
        self.assertEqual(actual["country"], "枫丹")
        self.assertFalse(actual["TaskEnabledList"]["id"])
        self.assertEqual(actual["other"], 7)

    def test_invalid_options_never_modify_main_or_native_files(self):
        options = Mock()
        options.prepare.side_effect = ValueError("未知选择")
        original = (self.config.read_bytes(), self.weekly.read_bytes())
        with (
            patch.object(script_service, "task_options_of", return_value=options),
            self.assertRaisesRegex(InvalidScript, "未知选择"),
        ):
            self.service.update_script(
                replace(self.edit(), task_options={"country": "unknown"})
            )
        self.assertEqual((self.config.read_bytes(), self.weekly.read_bytes()), original)
        options.write_prepared.assert_not_called()
        self.switch.write.assert_not_called()

    def test_options_reject_changed_script_path_before_writes(self):
        options = Mock()
        options.prepare.return_value = []
        original = (self.config.read_bytes(), self.weekly.read_bytes())
        with (
            patch.object(script_service, "task_options_of", return_value=options),
            self.assertRaisesRegex(InvalidScript, "修改脚本路径"),
        ):
            self.service.update_script(
                replace(
                    self.edit(script_path="D:/new/BetterGI.exe"),
                    task_options={"country": "枫丹"},
                )
            )
        self.assertEqual((self.config.read_bytes(), self.weekly.read_bytes()), original)
        options.write_prepared.assert_not_called()

    def test_second_options_validation_failure_is_reported_without_writes(self):
        options = Mock()
        error = ValueError("任务配置已变化，请刷新")
        options.prepare.side_effect = [[], error]
        original = (self.config.read_bytes(), self.weekly.read_bytes())
        with (
            patch.object(script_service, "task_options_of", return_value=options),
            self.assertRaisesRegex(InvalidScript, "任务配置已变化，请刷新") as raised,
        ):
            self.service.update_script(
                replace(self.edit(), task_options={"country": "枫丹"})
            )
        self.assertEqual(options.prepare.call_count, 2)
        self.assertIs(raised.exception.__cause__, error)
        self.assertEqual((self.config.read_bytes(), self.weekly.read_bytes()), original)
        options.write_prepared.assert_not_called()
        self.switch.write.assert_not_called()
        self.init.assert_not_called()

    def test_invalid_edit_never_writes(self):
        edit = self.edit()
        original = (self.config.read_bytes(), self.weekly.read_bytes())
        for changes in (
            {"script_name": ""},
            {"display_name": " "},
            {"config_patch": {**edit.config_patch, "unknown": True}},
            {"config_patch": self.edit(script_path=" ").config_patch},
            {"config_patch": self.edit(block=1).config_patch},
            {"config_patch": self.edit(script_type="shell").config_patch},
            {"config_patch": self.edit(check_done="unknown").config_patch},
            {
                "config_patch": self.edit(
                    game_path=str(self.config.parent / "missing.exe")
                ).config_patch
            },
            {"weekly_timeouts": [None] * 6},
            {"weekly_timeouts": [True] * 7},
            {"weekly_timeouts": [86401] * 7},
            {"switches": {"任务": 1}},
        ):
            with self.subTest(changes=changes), self.assertRaises(InvalidScript):
                self.service.update_script(replace(edit, **changes))
            self.assertEqual(
                (self.config.read_bytes(), self.weekly.read_bytes()), original
            )
        self.init.assert_not_called()
        self.switch_factory.assert_not_called()

    def test_game_arguments_save_independently(self):
        arguments = '--profile "中文 空格" --literal "a&b"'
        self.service.update_script(
            self.edit(game_arguments=arguments, script_arguments="--script")
        )
        saved = load_yaml(str(self.config))["script_list"][0]
        self.assertEqual(saved["game_arguments"], arguments)
        self.assertEqual(saved["script_arguments"], "--script")

    def test_normalization_keeps_input_and_files_unchanged(self):
        edit = replace(
            self.edit(
                game_process_name=" ",
                script_arguments=" --中文 ",
                game_arguments=' --profile "中文 空格" ',
            ),
            display_name=" 原神 ",
        )
        original = self.config.read_bytes()
        cleaned = self.service.validate_script_edit(edit)
        self.assertEqual(cleaned.display_name, "原神")
        self.assertEqual(cleaned.config_patch["script_arguments"], "--中文")
        self.assertEqual(
            cleaned.config_patch["game_arguments"], '--profile "中文 空格"'
        )
        self.assertFalse(cleaned.config_patch["kill_game_after_done"])
        self.assertEqual(edit.display_name, " 原神 ")
        self.assertEqual(edit.config_patch["script_arguments"], " --中文 ")
        self.assertTrue(edit.config_patch["kill_game_after_done"])
        self.assertEqual(self.config.read_bytes(), original)

    def test_save_rechecks_missing_script_and_identity_conflict(self):
        for label, entries in (
            ("missing", []),
            (
                "conflict",
                [
                    {"display_name": "原神", **self.edit().config_patch},
                    {"display_name": "重复", "script_path": "C:/new.exe"},
                ],
            ),
        ):
            with self.subTest(label=label):
                edit = validate_edit(self.edit(script_path="C:/new.exe"))
                dump_yaml_file(str(self.config), {"script_list": entries})
                original = (self.config.read_bytes(), self.weekly.read_bytes())
                with self.assertRaises(InvalidScript):
                    self.service.update_script(edit)
                self.assertEqual(
                    (self.config.read_bytes(), self.weekly.read_bytes()), original
                )
        self.init.assert_not_called()
        self.switch_factory.assert_not_called()

    def test_save_normalizes_timeouts_and_preserves_unedited_fields(self):
        edit = replace(
            self.edit(game_process_name=""),
            weekly_timeouts=[None, 0, 5, 60, 90, 120, 86400],
        )
        self.assertEqual(self.service.update_script(edit), "BetterGI")
        entry = load_yaml(str(self.config))["script_list"][0]
        self.assertEqual(entry["other_field"], "保留")
        self.assertFalse(entry["kill_game_after_done"])
        self.assertEqual(
            load_yaml(str(self.weekly)),
            {
                "weekly_start": {"BetterGI": {"周常": 3}},
                "weekly_timeouts": {
                    "BetterGI": [DEFAULT_RUN_TIMEOUT, 0, 5, 60, 90, 120, 86400]
                },
            },
        )
        self.init.assert_not_called()
        self.switch_factory.assert_called_once_with("BetterGI")
        self.switch.write.assert_called_once_with({"任务": False})

    def test_rename_moves_both_weekly_sections_and_uses_new_switch_target(self):
        for original, edited, expected in (
            (self.edit(), self.edit(script_path="C:/new.exe"), "new"),
            (
                replace(
                    self.edit(script_path="script.py", script_type="python"),
                    script_name="原神",
                ),
                replace(
                    self.edit(script_path="script.py", script_type="python"),
                    script_name="原神",
                    display_name="新脚本",
                ),
                "新脚本",
            ),
        ):
            with self.subTest(expected=expected):
                self._seed(original)
                self.init.reset_mock()
                self.switch_factory.reset_mock()
                self.switch.reset_mock()
                self.assertEqual(self.service.update_script(edited), expected)
                self.assertEqual(
                    get_script_name(load_yaml(str(self.config))["script_list"][0]),
                    expected,
                )
                self.assertEqual(
                    load_yaml(str(self.weekly)),
                    {
                        "weekly_start": {expected: {"周常": 3}},
                        "weekly_timeouts": {expected: [60] * 7},
                    },
                )
                self.init.assert_called_once_with(expected)
                self.switch_factory.assert_called_once_with(expected)
                self.switch.write.assert_called_once_with(edited.switches)

    def test_failure_stops_remaining_steps_without_retry(self):
        steps = ["config", "rename", "weekly", "init", "switches"]
        for index, failed_step in enumerate(steps):
            with self.subTest(step=failed_step):
                self._seed(self.edit())
                events = Mock()
                events.config.side_effect = utils_config.save_config
                events.rename.side_effect = utils_weekly.rename_weekly
                events.weekly.side_effect = utils_weekly.save_weekly
                getattr(events, failed_step).side_effect = OSError(failed_step)
                with (
                    patch.object(utils_config, "save_config", events.config),
                    patch.object(utils_weekly, "rename_weekly", events.rename),
                    patch.object(utils_weekly, "save_weekly", events.weekly),
                    patch.object(script_service, "init_config", events.init),
                    patch.object(
                        script_service,
                        "task_switch_of",
                        return_value=Mock(write=events.switches),
                    ),
                    self.assertRaisesRegex(OSError, failed_step),
                ):
                    self.service.update_script(self.edit(script_path="C:/new.exe"))
                self.assertEqual(
                    [call[0] for call in events.mock_calls], steps[: index + 1]
                )
                expected = "BetterGI" if index == 0 else "new"
                self.assertEqual(
                    get_script_name(load_yaml(str(self.config))["script_list"][0]),
                    expected,
                )

    def test_native_config_is_only_realigned_after_target_change(self):
        template = {"task": {"enabled": True}}
        factory = cache(set_config.GenshinConfig)
        with (
            patch.dict(set_config._CONFIGS, {"BetterGI": factory}, clear=True),
            patch.object(script_service, "init_config", wraps=set_config.init_config),
            patch.object(script_service, "task_switch_of", return_value=None),
            patch.object(
                set_config, "load_config", return_value=template
            ) as native_read,
            patch.object(set_config, "load_template", return_value=template),
            patch.object(set_config, "save_config") as native_write,
        ):
            set_config.ensure_config("BetterGI")
            native_read.reset_mock()
            for edit in (
                self.edit(),
                replace(self.edit(), display_name="原神日常"),
                self.edit(script_arguments="--test"),
                self.edit(game_path=str(self.config)),
                replace(self.edit(), weekly_timeouts=[90] * 7),
            ):
                with self.subTest(edit=edit), self.assertNoLogs(set_config.logger):
                    self.service.update_script(edit)
                    native_read.assert_not_called()
                    native_write.assert_not_called()
            with self.assertLogs(set_config.logger, level="INFO") as logs:
                self.service.update_script(self.edit(script_path="D:/new/BetterGI.exe"))
            self.assertEqual(len(logs.records), 1)
            native_read.assert_called_once_with(
                "BetterGI", "User/OneDragon/默认配置.json"
            )
            native_write.assert_not_called()


class TestScriptList(ScriptServiceTestBase):
    def _file(self, name):
        path = self.config.parent / name
        path.touch()
        return str(path)

    def test_add_infers_type_and_keeps_default_fields(self):
        for filename, script_type in (
            ("new.py", "python"),
            ("new.EXE", "external"),
            ("new.bat", "external"),
        ):
            with self.subTest(filename=filename):
                self._seed(self.edit())
                path = self._file(filename)
                result = self.service.add_script(path)
                self.assertEqual(result, {"script_name": "new", "display_name": "new"})
                entry = utils_config.get_script("new")
                self.assertEqual(entry["script_path"], path)
                self.assertEqual(entry["script_type"], script_type)
                self.assertEqual(entry["script_arguments"], "")
                self.assertEqual(entry["check_done"], "script_closed")
                self.assertTrue(entry["block"])

    def test_repeated_script_files_get_distinct_names(self):
        for filename in ("重复.py", "重复.bat"):
            with self.subTest(filename=filename):
                self._seed(self.edit())
                path = self._file(filename)
                results = [self.service.add_script(path) for _ in range(3)]
                self.assertEqual(
                    [result["script_name"] for result in results],
                    ["重复", "重复_1", "重复_2"],
                )
                self.assertEqual(
                    [
                        entry["display_name"]
                        for entry in load_yaml(str(self.config))["script_list"][1:]
                    ],
                    ["重复", "重复_1", "重复_2"],
                )

    def test_mutations_preserve_other_config_with_one_read(self):
        path = self._file("新增.py")
        for operation in ("add", "remove", "update", "reorder"):
            with self.subTest(operation=operation):
                self._seed(self.edit())
                config = load_yaml(str(self.config))
                original = config["script_list"][0]
                extra = {
                    "display_name": "其他",
                    "script_path": "other.py",
                    "custom": [1],
                }
                config["script_list"].append(extra)
                config["other_config"] = {"preserved": True}
                dump_yaml_file(str(self.config), config)
                with patch.object(
                    utils_config, "load_config", wraps=utils_config.load_config
                ) as read:
                    if operation == "add":
                        self.service.add_script(path)
                    elif operation == "remove":
                        self.service.remove_script("BetterGI")
                    elif operation == "update":
                        self.service.update_script(self.edit(script_path="C:/new.exe"))
                    else:
                        self.service.reorder_scripts(["其他", "BetterGI"])
                    read.assert_called_once_with()
                saved = load_yaml(str(self.config))
                self.assertEqual(saved["other_config"], {"preserved": True})
                self.assertIn(extra, saved["script_list"])
                if operation == "update":
                    self.assertEqual(
                        saved["script_list"][0],
                        {**original, "script_path": "C:/new.exe"},
                    )
                elif operation != "remove":
                    self.assertIn(original, saved["script_list"])

    def test_duplicate_exe_has_distinct_error_without_writing(self):
        path = self._file("BetterGI.exe")
        before = (self.config.read_bytes(), self.weekly.read_bytes())
        with self.assertRaises(script_service.DuplicateScript):
            self.service.add_script(path)
        self.assertEqual((self.config.read_bytes(), self.weekly.read_bytes()), before)
        self.init.assert_not_called()

    def test_invalid_file_and_shortcut_do_not_write(self):
        before = (self.config.read_bytes(), self.weekly.read_bytes())
        for path in (
            "",
            str(self.config.parent / "missing.py"),
            self._file("notes.txt"),
        ):
            with self.subTest(path=path), self.assertRaises(InvalidScript):
                self.service.add_script(path)
        with (
            patch.object(
                script_service, "read_shortcut", side_effect=OSError("broken link")
            ),
            self.assertRaisesRegex(InvalidScript, "broken link"),
        ):
            self.service.add_script(self._file("broken.lnk"))
        self.assertEqual((self.config.read_bytes(), self.weekly.read_bytes()), before)
        self.init.assert_not_called()

    def test_add_and_remove_coordinate_config_and_weekly(self):
        path = self._file("新增.py")
        self.assertEqual(
            self.service.add_script(path),
            {"script_name": "新增", "display_name": "新增"},
        )
        self.assertEqual(utils_config.get_script("新增")["script_path"], path)
        weekly = load_yaml(str(self.weekly))
        self.assertEqual(weekly["weekly_timeouts"]["新增"], [DEFAULT_RUN_TIMEOUT] * 7)
        self.assertEqual(weekly["weekly_start"], {"BetterGI": {"周常": 3}})
        self.init.assert_called_once_with("新增")
        self.init.reset_mock()

        self.service.remove_script("新增")
        self.assertIsNone(utils_config.get_script("新增"))
        self.assertEqual(
            load_yaml(str(self.weekly)),
            {
                "weekly_timeouts": {"BetterGI": [60] * 7},
                "weekly_start": {"BetterGI": {"周常": 3}},
            },
        )
        self.assertTrue(Path(path).is_file())
        self.init.assert_not_called()

    def test_add_shortcut_preserves_target_and_arguments(self):
        target = self._file("new.exe")
        shortcut = self._file("shortcut.lnk")
        arguments = '--profile "中文 100% #1" --daily'
        with patch.object(
            script_service, "read_shortcut", return_value=(target, arguments, "")
        ) as read:
            result = self.service.add_script(shortcut)
        read.assert_called_once_with(shortcut)
        self.assertEqual(result, {"script_name": "new", "display_name": "new"})
        entry = utils_config.get_script("new")
        self.assertEqual(entry["script_path"], target)
        self.assertEqual(entry["script_arguments"], arguments)
        self.init.assert_called_once_with("new")

    def test_shortcut_with_different_working_directory_does_not_write(self):
        before = (self.config.read_bytes(), self.weekly.read_bytes())
        target = self._file("new.exe")
        with (
            patch.object(
                script_service,
                "read_shortcut",
                return_value=(target, "--daily", str(self.config.parent / "other")),
            ),
            self.assertRaisesRegex(InvalidScript, "不同的工作目录"),
        ):
            self.service.add_script(self._file("shortcut.lnk"))
        self.assertEqual((self.config.read_bytes(), self.weekly.read_bytes()), before)
        self.init.assert_not_called()

    def test_shortcut_accepts_equivalent_working_directory_and_environment(self):
        target = self._file("new.exe")
        # 仅设置单个测试变量，避免重建整份进程环境。
        os.environ["SHORTCUT_TEST_ROOT"] = str(self.config.parent)
        try:
            with patch.object(
                script_service,
                "read_shortcut",
                return_value=(
                    "${SHORTCUT_TEST_ROOT}/new.exe",
                    "--daily",
                    "${SHORTCUT_TEST_ROOT}/.",
                ),
            ):
                self.service.add_script(self._file("shortcut.lnk"))
        finally:
            os.environ.pop("SHORTCUT_TEST_ROOT", None)
        entry = utils_config.get_script("new")
        self.assertEqual(entry["script_path"], target)
        self.assertEqual(entry["script_arguments"], "--daily")

    def test_reorder_preserves_entries_and_unknown_fields(self):
        first = {"script_path": "a.py", "display_name": "一", "custom": [1, 2]}
        second = {"script_path": "b.exe", "display_name": "二"}
        dump_yaml_file(
            str(self.config), {"script_list": [first, second], "other": True}
        )
        weekly_before = self.weekly.read_bytes()
        self.service.reorder_scripts(["b", "一"])
        self.assertEqual(
            load_yaml(str(self.config)), {"script_list": [second, first], "other": True}
        )
        self.assertEqual(self.weekly.read_bytes(), weekly_before)
        self.init.assert_not_called()

    def test_stale_duplicate_and_invalid_orders_do_not_write(self):
        before = self.config.read_bytes()
        for order in ([], ["BetterGI", "BetterGI"], ["unknown"], "BetterGI", [False]):
            with self.subTest(order=order), self.assertRaises(InvalidScript):
                self.service.reorder_scripts(order)
        self.assertEqual(self.config.read_bytes(), before)

    def test_unknown_or_last_script_cannot_be_removed(self):
        before = (self.config.read_bytes(), self.weekly.read_bytes())
        for name in ("unknown", "BetterGI"):
            with self.subTest(name=name), self.assertRaises(InvalidScript):
                self.service.remove_script(name)
        self.assertEqual((self.config.read_bytes(), self.weekly.read_bytes()), before)

    def test_add_failure_stops_remaining_steps_without_retry(self):
        path = self._file("新增.py")
        steps = ["config", "weekly", "init"]
        for index, failed_step in enumerate(steps):
            with self.subTest(step=failed_step):
                self._seed(self.edit())
                events = Mock()
                events.config.side_effect = utils_config.save_config
                events.weekly.side_effect = utils_weekly.ensure_weekly_entry
                getattr(events, failed_step).side_effect = OSError(failed_step)
                with (
                    patch.object(utils_config, "save_config", events.config),
                    patch.object(utils_weekly, "ensure_weekly_entry", events.weekly),
                    patch.object(script_service, "init_config", events.init),
                    self.assertRaisesRegex(OSError, failed_step),
                ):
                    self.service.add_script(path)
                self.assertEqual(
                    [call[0] for call in events.mock_calls], steps[: index + 1]
                )
                self.assertEqual(utils_config.get_script("新增") is not None, index > 0)
                self.assertEqual(
                    "新增" in load_yaml(str(self.weekly))["weekly_timeouts"], index > 1
                )

    def test_remove_failure_stops_remaining_steps_without_retry(self):
        path = self._file("新增.py")
        steps = ["config", "weekly"]
        for index, failed_step in enumerate(steps):
            with self.subTest(step=failed_step):
                self._seed(self.edit())
                self.service.add_script(path)
                self.init.reset_mock()
                events = Mock()
                events.config.side_effect = utils_config.save_config
                events.weekly.side_effect = utils_weekly.delete_weekly
                getattr(events, failed_step).side_effect = OSError(failed_step)
                with (
                    patch.object(utils_config, "save_config", events.config),
                    patch.object(utils_weekly, "delete_weekly", events.weekly),
                    self.assertRaisesRegex(OSError, failed_step),
                ):
                    self.service.remove_script("新增")
                self.assertEqual(
                    [call[0] for call in events.mock_calls], steps[: index + 1]
                )
                self.assertEqual(
                    utils_config.get_script("新增") is not None, index == 0
                )
                self.assertIn("新增", load_yaml(str(self.weekly))["weekly_timeouts"])
                self.init.assert_not_called()
