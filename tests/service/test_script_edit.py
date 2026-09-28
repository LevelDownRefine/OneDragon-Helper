"""完整脚本编辑的校验、跨文件保存与初始化边界。"""

import tempfile
import unittest
from dataclasses import replace
from functools import cache
from pathlib import Path
from unittest.mock import Mock, patch

from src.config import set_config
from src.service import script_edit
from src.service.app_service import AppService
from src.service.script_edit import InvalidScriptEdit, ScriptEdit, validate_edit
from src.utils import utils_config, utils_weekly
from src.utils.utils_sub_config import DEFAULT_RUN_TIMEOUT, get_script_name
from src.utils.utils_yaml import dump_yaml_file, load_yaml


class TestScriptEdit(unittest.TestCase):
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
        self.init = self.enterContext(patch.object(script_edit, "init_config"))
        self.switch = Mock()
        self.switch_factory = self.enterContext(
            patch.object(script_edit, "task_switch_of", return_value=self.switch)
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
            with self.subTest(changes=changes), self.assertRaises(InvalidScriptEdit):
                self.service.update_script(replace(edit, **changes))
            self.assertEqual(
                (self.config.read_bytes(), self.weekly.read_bytes()), original
            )
        self.init.assert_not_called()
        self.switch_factory.assert_not_called()

    def test_normalization_keeps_input_and_files_unchanged(self):
        edit = replace(
            self.edit(game_process_name=" ", script_arguments=" --中文 "),
            display_name=" 原神 ",
        )
        original = self.config.read_bytes()
        cleaned = self.service.validate_script_edit(edit)
        self.assertEqual(cleaned.display_name, "原神")
        self.assertEqual(cleaned.config_patch["script_arguments"], "--中文")
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
                with self.assertRaises(InvalidScriptEdit):
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
                events.config.side_effect = utils_config.update_script
                events.rename.side_effect = utils_weekly.rename_weekly
                events.weekly.side_effect = utils_weekly.save_weekly
                getattr(events, failed_step).side_effect = OSError(failed_step)
                with (
                    patch.object(utils_config, "update_script", events.config),
                    patch.object(utils_weekly, "rename_weekly", events.rename),
                    patch.object(utils_weekly, "save_weekly", events.weekly),
                    patch.object(script_edit, "init_config", events.init),
                    patch.object(
                        script_edit,
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
            patch.object(script_edit, "init_config", wraps=set_config.init_config),
            patch.object(script_edit, "task_switch_of", return_value=None),
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
