"""脚本列表变更的写入前校验与部分失败语义。"""

import unittest
from unittest.mock import patch

from src.service import script_list
from src.service.app_service import AppService


class ScriptListTests(unittest.TestCase):
    def test_duplicate_exe_has_distinct_error_without_writing(self):
        entry = {"script_path": "a.exe", "display_name": "一"}
        with (
            patch.object(script_list, "resolve_script_path", return_value="a.exe"),
            patch.object(script_list.os.path, "isfile", return_value=True),
            patch.object(
                script_list, "load_config", return_value={"script_list": [entry]}
            ),
            patch.object(script_list, "build_script_entry", return_value=entry),
            patch.object(script_list, "add_script") as add,
            self.assertRaises(script_list.DuplicateScript),
        ):
            script_list.add("a.exe")
        add.assert_not_called()

    def test_reorder_preserves_entries_and_unknown_fields(self):
        first = {"script_path": "a.py", "display_name": "一", "custom": [1, 2]}
        second = {"script_path": "b.exe", "display_name": "二"}
        config = {"script_list": [first, second], "other": True}
        with (
            patch.object(script_list, "load_config", return_value=config),
            patch.object(script_list, "save_config") as save,
        ):
            script_list.reorder(["b", "一"])
        save.assert_called_once_with({"script_list": [second, first], "other": True})
        self.assertIs(config["script_list"][1], first)

    def test_stale_duplicate_and_invalid_orders_do_not_write(self):
        config = {"script_list": [{"script_path": "a.py", "display_name": "一"}]}
        with (
            patch.object(script_list, "load_config", return_value=config),
            patch.object(script_list, "save_config") as save,
        ):
            for order in ([], ["一", "一"], ["unknown"], "一", [False]):
                with (
                    self.subTest(order=order),
                    self.assertRaises(script_list.InvalidScriptList),
                ):
                    script_list.reorder(order)
        save.assert_not_called()

    def test_unknown_or_last_script_cannot_be_removed(self):
        config = {"script_list": [{"script_path": "a.py", "display_name": "一"}]}
        with (
            patch.object(script_list, "load_config", return_value=config),
            patch.object(script_list, "remove_script") as remove,
        ):
            for name in ("unknown", "一"):
                with (
                    self.subTest(name=name),
                    self.assertRaises(script_list.InvalidScriptList),
                ):
                    AppService().remove_script(name)
        remove.assert_not_called()

    def test_add_uses_shortcut_resolver_and_preserves_arguments(self):
        entry = {
            "script_path": "a.exe",
            "display_name": "一",
            "script_arguments": "--test",
        }
        with (
            patch.object(
                script_list, "resolve_script_path", return_value="shortcut.lnk"
            ),
            patch.object(script_list.os.path, "isfile", return_value=True),
            patch.object(script_list, "load_config", return_value={"script_list": []}),
            patch.object(
                script_list, "build_script_entry", return_value=entry
            ) as build,
            patch.object(script_list, "add_script") as add,
        ):
            self.assertEqual(
                AppService().add_script("shortcut.lnk"),
                {"script_name": "a", "display_name": "一"},
            )
        build.assert_called_once_with("shortcut.lnk", set())
        add.assert_called_once_with(entry)

    def test_failed_initialization_after_add_remains_partial_failure(self):
        entry = {"script_path": "a.py", "display_name": "一"}
        with (
            patch.object(script_list, "resolve_script_path", return_value="a.py"),
            patch.object(script_list.os.path, "isfile", return_value=True),
            patch.object(script_list, "load_config", return_value={"script_list": []}),
            patch.object(script_list, "build_script_entry", return_value=entry),
            patch.object(script_list, "add_script", side_effect=OSError("init failed")),
            self.assertRaisesRegex(OSError, "init failed"),
        ):
            script_list.add("a.py")
