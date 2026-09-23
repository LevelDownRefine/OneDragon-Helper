"""测试 src/config/task_switch.py：声明校验、开关枚举与写入。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.config import task_switch as mod
from src.config.task_switch import TaskSwitch, load_task_switch_map, task_switch_of

_DECLARATION = {
    "config": "User/OneDragon/默认配置.json",
    "tasks_key": "TaskDefinitions",
    "enabled_key": "TaskEnabledList",
}


def _switch() -> TaskSwitch:
    return TaskSwitch("BetterGI", _DECLARATION, "原神")


def _config(tasks: dict, enabled: dict) -> dict:
    return {"TaskDefinitions": tasks, "TaskEnabledList": enabled}


class TestRead(unittest.TestCase):
    """read：行名与开关态取自配置，表缺失或项缺开关记录时按无该行处理。"""

    def test_rows_follow_config_order_and_names(self):
        config = _config(
            {"a": "领取邮件", "b": "自动秘境", "c": "周常"},
            {"a": True, "b": False, "c": False},
        )
        with patch.object(mod, "load_script_config", return_value=config):
            self.assertEqual(
                _switch().read(),
                [
                    {"name": "领取邮件", "enabled": True},
                    {"name": "自动秘境", "enabled": False},
                    {"name": "周常", "enabled": False},
                ],
            )

    def test_missing_config_reads_empty(self):
        """脚本未安装/未配置：无开关可用，也不报错。"""
        with patch.object(mod, "load_script_config", return_value=None):
            self.assertEqual(_switch().read(), [])

    def test_missing_tables_reads_empty_with_warning(self):
        with (
            patch.object(mod, "load_script_config", return_value={"other": 1}),
            self.assertLogs("src.config.task_switch", level="WARNING"),
        ):
            self.assertEqual(_switch().read(), [])

    def test_task_without_switch_record_is_skipped(self):
        """定义表有、启用表缺的项：跳过并记日志（不猜目标）。"""
        config = _config({"a": "领取邮件", "b": "周常"}, {"a": True})
        with (
            patch.object(mod, "load_script_config", return_value=config),
            self.assertLogs("src.config.task_switch", level="WARNING"),
        ):
            self.assertEqual(_switch().read(), [{"name": "领取邮件", "enabled": True}])

    def test_non_bool_switch_is_rejected(self):
        """开关值非 bool：声明与脚本实际不符，当场报错而非误判。"""
        config = _config({"a": "领取邮件"}, {"a": "true"})
        with (
            patch.object(mod, "load_script_config", return_value=config),
            self.assertRaises(AssertionError),
        ):
            _switch().read()


class TestWrite(unittest.TestCase):
    """write：按任务名反查 id 写入，取值未变则不动。"""

    def _run(self, config, states):
        saved = []
        with (
            patch.object(mod, "load_script_config", return_value=config),
            patch.object(
                mod, "save_script_config", side_effect=lambda *args: saved.append(args)
            ),
        ):
            changed = _switch().write(states)
        return changed, saved

    def test_writes_named_task_only(self):
        config = _config({"a": "领取邮件", "b": "周常"}, {"a": True, "b": False})
        changed, saved = self._run(config, {"周常": True})
        self.assertEqual(changed, 1)
        self.assertEqual(len(saved), 1)
        self.assertEqual(config["TaskEnabledList"], {"a": True, "b": True})

    def test_unchanged_value_skips_save(self):
        config = _config({"a": "领取邮件"}, {"a": True})
        self.assertEqual(self._run(config, {"领取邮件": True}), (0, []))

    def test_empty_states_does_not_touch_disk(self):
        """脚本无开关区时保存不带状态：不读不写。"""
        with patch.object(mod, "load_script_config") as mock_load:
            self.assertEqual(_switch().write({}), 0)
        mock_load.assert_not_called()

    def test_unknown_and_ambiguous_names_are_skipped(self):
        """行名找不到或同名撞车都不写，并记日志。"""
        config = _config(
            {"a": "领取邮件", "b": "同名", "c": "同名"},
            {"a": True, "b": False, "c": False},
        )
        with (
            patch.object(mod, "load_script_config", return_value=config),
            patch.object(mod, "save_script_config") as mock_save,
            self.assertLogs("src.config.task_switch", level="WARNING"),
        ):
            self.assertEqual(_switch().write({"不存在": True, "同名": True}), 0)
        mock_save.assert_not_called()

    def test_missing_config_write_is_noop(self):
        with patch.object(mod, "load_script_config", return_value=None):
            self.assertEqual(_switch().write({"领取邮件": True}), 0)

    def test_missing_tables_write_is_noop(self):
        with (
            patch.object(mod, "load_script_config", return_value={"other": 1}),
            self.assertLogs("src.config.task_switch", level="WARNING"),
        ):
            self.assertEqual(_switch().write({"领取邮件": True}), 0)


class TestDeclaration(unittest.TestCase):
    """声明文件：按内容解析一次，字段非法即报错。"""

    def setUp(self):
        mod._parse_declarations.cache_clear()
        task_switch_of.cache_clear()
        self.addCleanup(mod._parse_declarations.cache_clear)
        self.addCleanup(task_switch_of.cache_clear)

    def _with_declaration(self, text: str):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        path = Path(directory, "task_switch_list.yml")
        path.write_text(text, encoding="utf-8")
        return patch.object(
            mod, "get_task_switch_list_yml_path_under_root", return_value=str(path)
        )

    def test_declared_script_builds_switch(self):
        text = (
            "BetterGI:\n"
            "  config: User/OneDragon/默认配置.json\n"
            "  tasks_key: TaskDefinitions\n"
            "  enabled_key: TaskEnabledList\n"
        )
        with self._with_declaration(text):
            switch = task_switch_of("BetterGI")
            self.assertIsNotNone(switch)
            self.assertIsNone(task_switch_of("ZZZ"), "未声明脚本应为无此特性")

    def test_missing_file_is_rejected(self):
        with (
            patch.object(
                mod,
                "get_task_switch_list_yml_path_under_root",
                return_value="C:/不存在/task_switch_list.yml",
            ),
            self.assertRaises(AssertionError),
        ):
            load_task_switch_map()

    def test_invalid_declarations_are_rejected(self):
        cases = {
            "缺字段": "BetterGI:\n  config: a/b.json\n  tasks_key: T\n",
            "多写字段": (
                "BetterGI:\n  config: a/b.json\n  tasks_key: T\n"
                "  enabled_key: E\n  extra: 1\n"
            ),
            "空值": "BetterGI:\n  config: ''\n  tasks_key: T\n  enabled_key: E\n",
            "绝对路径": "BetterGI:\n  config: C:/a/b.json\n  tasks_key: T\n  enabled_key: E\n",
            "上溯路径": "BetterGI:\n  config: ../b.json\n  tasks_key: T\n  enabled_key: E\n",
        }
        for case, text in cases.items():
            with (
                self.subTest(case=case),
                self._with_declaration(text),
                self.assertRaises(AssertionError),
            ):
                load_task_switch_map()

    def test_repo_declaration_covers_bettergi(self):
        """仓库声明里原神已接上：键指向其一条龙配置的两张表。"""
        declaration = load_task_switch_map()["BetterGI"]
        self.assertEqual(declaration["config"], "User/OneDragon/默认配置.json")
        self.assertEqual(declaration["tasks_key"], "TaskDefinitions")
        self.assertEqual(declaration["enabled_key"], "TaskEnabledList")
