"""测试 src/config/task_switch.py：声明校验、开关枚举与写入。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.config import task_switch as mod
from src.config.task_switch import (
    AppListTaskSwitch,
    KeyPairTaskSwitch,
    PatternTaskSwitch,
    load_task_switch_map,
    task_switch_of,
)

_DECLARATION = {
    "config": "User/OneDragon/默认配置.json",
    "tasks_key": "TaskDefinitions",
    "enabled_key": "TaskEnabledList",
}

_PATTERN_DECLARATION = {
    "config": "data/apps/ok-ef/working/configs/DailyTask.json",
    "task_pattern": "⭐(.+)",
}

_APP_LIST_DECLARATION = {
    "config": "config/01/one_dragon/_group.yml",
    "list_key": "app_list",
    "id_key": "app_id",
    "enabled_key": "enabled",
    "names": {"redemption_code": "兑换码"},
}

_NO_NAMES_APP_LIST_DECLARATION = {
    "config": "config/01/one_dragon/_group.yml",
    "list_key": "app_list",
    "id_key": "app_id",
    "enabled_key": "enabled",
}


def _switch() -> KeyPairTaskSwitch:
    return KeyPairTaskSwitch.from_declaration("BetterGI", _DECLARATION)


def _pattern_switch() -> PatternTaskSwitch:
    return PatternTaskSwitch.from_declaration("ok-ef", _PATTERN_DECLARATION)


def _app_list_switch() -> AppListTaskSwitch:
    return AppListTaskSwitch.from_declaration(
        "OneDragon-Launcher", _APP_LIST_DECLARATION
    )


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

    def test_pattern_rows_take_name_from_capture_group_and_skip_non_bool(self):
        """正则白名单形态：行名取捕获组，值非 bool 的项（带子选项）不作开关、也不报错。"""
        config = {
            "⭐收邮件": False,
            "⭐刷体力": True,
            "⭐帝江号收菜": [],
            "⭐帝江号整理": None,
            "普通字段": True,
        }
        with patch.object(mod, "load_script_config", return_value=config):
            self.assertEqual(
                _pattern_switch().read(),
                [
                    {"name": "收邮件", "enabled": False},
                    {"name": "刷体力", "enabled": True},
                ],
            )

    def test_app_list_names_act_as_whitelist(self):
        """应用列表形态：给了 names 即白名单 —— 未列出的项不出现，行名取映射值。"""
        config = {
            "app_list": [
                {"app_id": "redemption_code", "enabled": True},
                {"app_id": "lost_void", "enabled": False},
            ]
        }
        with patch.object(mod, "load_script_config", return_value=config):
            self.assertEqual(
                _app_list_switch().read(), [{"name": "兑换码", "enabled": True}]
            )

    def test_app_list_without_names_keeps_all_rows(self):
        """未给 names 时全量照原样（行标识即行名）。"""
        config = {
            "app_list": [
                {"app_id": "redemption_code", "enabled": True},
                {"app_id": "lost_void", "enabled": False},
            ]
        }
        switch = AppListTaskSwitch.from_declaration(
            "ZZZ", _NO_NAMES_APP_LIST_DECLARATION
        )
        with patch.object(mod, "load_script_config", return_value=config):
            self.assertEqual(
                switch.read(),
                [
                    {"name": "redemption_code", "enabled": True},
                    {"name": "lost_void", "enabled": False},
                ],
            )

    def test_app_list_missing_list_reads_empty_with_warning(self):
        with (
            patch.object(mod, "load_script_config", return_value={"other": 1}),
            self.assertLogs("src.config.task_switch", level="WARNING"),
        ):
            self.assertEqual(_app_list_switch().read(), [])


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

    def test_pattern_write_only_touches_switch_items(self):
        """正则白名单形态：按行名回填同一个键，带子选项的项既不写也不报错。"""
        config = {"⭐收邮件": False, "⭐帝江号收菜": [], "普通字段": 1}
        saved = []
        with (
            patch.object(mod, "load_script_config", return_value=config),
            patch.object(
                mod, "save_script_config", side_effect=lambda *args: saved.append(args)
            ),
            self.assertLogs("src.config.task_switch", level="WARNING"),
        ):
            changed = _pattern_switch().write({"收邮件": True, "帝江号收菜": True})
        self.assertEqual(changed, 1)
        self.assertEqual(config["⭐收邮件"], True)
        self.assertEqual(config["⭐帝江号收菜"], [])
        self.assertEqual(len(saved), 1)

    def test_app_list_write_touches_only_listed_item(self):
        """应用列表形态：按行名写回列表项；白名单外的标识既不出行、也写不动。"""
        config = {
            "app_list": [
                {"app_id": "redemption_code", "enabled": True},
                {"app_id": "lost_void", "enabled": False},
            ]
        }
        saved = []
        with (
            patch.object(mod, "load_script_config", return_value=config),
            patch.object(
                mod, "save_script_config", side_effect=lambda *args: saved.append(args)
            ),
        ):
            self.assertEqual(
                _app_list_switch().write({"兑换码": False, "lost_void": True}), 1
            )
        self.assertEqual(
            config["app_list"],
            [
                {"app_id": "redemption_code", "enabled": False},
                {"app_id": "lost_void", "enabled": False},
            ],
        )
        self.assertEqual(len(saved), 1)

    def test_pattern_names_whitelist_and_rename(self):
        """正则白名单形态也能用 names：只留列出的键，行名取映射值。"""
        config = {
            "power_enable": True,
            "daily_enable": False,
            "debug_mode_enable": True,
        }
        declaration = {
            "config": "config.yaml",
            "task_pattern": "(.+_enable)",
            "names": {"power_enable": "清体力", "daily_enable": "每日实训"},
        }
        switch = PatternTaskSwitch.from_declaration("M7A", declaration)
        with (
            patch.object(mod, "load_script_config", return_value=config),
            patch.object(mod, "save_script_config") as mock_save,
        ):
            self.assertEqual(
                switch.read(),
                [
                    {"name": "清体力", "enabled": True},
                    {"name": "每日实训", "enabled": False},
                ],
            )
            self.assertEqual(
                switch.write({"清体力": False, "debug_mode_enable": True}), 1
            )
        mock_save.assert_called_once()
        self.assertFalse(config["power_enable"])
        self.assertTrue(config["debug_mode_enable"])


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
            self.assertIsInstance(switch, KeyPairTaskSwitch)
            self.assertIsNone(task_switch_of("ZZZ"), "未声明脚本应为无此特性")

    def test_pattern_declaration_builds_switch(self):
        text = "ok-ef:\n  config: a/b.json\n  task_pattern: '@(.+)'\n"
        with self._with_declaration(text):
            switch = task_switch_of("ok-ef")
            self.assertIsInstance(switch, PatternTaskSwitch)

    def test_app_list_declaration_builds_switch(self):
        text = (
            "ZZZ:\n"
            "  config: a/_group.yml\n"
            "  list_key: app_list\n"
            "  id_key: app_id\n"
            "  enabled_key: enabled\n"
            "  names:\n"
            "    a: 甲\n"
        )
        with self._with_declaration(text):
            self.assertIsInstance(task_switch_of("ZZZ"), AppListTaskSwitch)

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
            "形态混用": (
                "BetterGI:\n  config: a/b.json\n  tasks_key: T\n"
                "  enabled_key: E\n  task_pattern: '@(.+)'\n"
            ),
            "正则形态缺 config": "BetterGI:\n  task_pattern: '@(.+)'\n",
            "正则无捕获组": "BetterGI:\n  config: a/b.json\n  task_pattern: '@.+'\n",
            "正则非法": "BetterGI:\n  config: a/b.json\n  task_pattern: '([a-z'\n",
            "列表形态缺 list_key": (
                "ZZZ:\n  config: a/_group.yml\n  id_key: app_id\n  enabled_key: enabled\n"
            ),
            "names 非字典": (
                "ZZZ:\n  config: a/_group.yml\n  list_key: app_list\n  id_key: app_id\n"
                "  enabled_key: enabled\n  names: 甲\n"
            ),
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

    def test_repo_declaration_covers_m7a(self):
        """仓库声明里星铁已接上：正则白名单形态，names 只列任务项（设置/通知不列）。"""
        declaration = load_task_switch_map()["March7th-Launcher"]
        self.assertEqual(declaration["config"], "config.yaml")
        self.assertEqual(declaration["task_pattern"], "(.+_enable)")
        self.assertEqual(declaration["names"]["power_enable"], "清体力")
        self.assertNotIn("debug_mode_enable", declaration["names"])
        self.assertNotIn("notify_telegram_enable", declaration["names"])

    def test_repo_declaration_covers_endfield(self):
        """仓库声明里终末地已接上：正则白名单形态指向其一条龙任务表。"""
        declaration = load_task_switch_map()["ok-ef"]
        self.assertEqual(
            declaration["config"], "data/apps/ok-ef/working/configs/DailyTask.json"
        )
        self.assertEqual(declaration["task_pattern"], "⭐(.+)")

    def test_repo_declaration_covers_zzz(self):
        """仓库声明里绝区零已接上：应用列表形态指向其一条龙应用组配置。"""
        declaration = load_task_switch_map()["OneDragon-Launcher"]
        self.assertEqual(declaration["config"], "config/01/one_dragon/_group.yml")
        self.assertEqual(declaration["list_key"], "app_list")
        self.assertEqual(declaration["names"]["redemption_code"], "兑换码")

    def test_repo_declaration_covers_oknte(self):
        """仓库声明里异环已接上：应用列表形态指向其计划任务表。"""
        declaration = load_task_switch_map()["ok-nte"]
        self.assertEqual(
            declaration["config"], "data/apps/ok-nte/working/configs/DailyPlanTask.json"
        )
        self.assertEqual(declaration["list_key"], "计划任务")
        self.assertEqual(declaration["names"]["daily_claim"], "日常领取")

    def test_repo_declaration_covers_okww(self):
        """仓库声明里鸣潮已接上：一条龙配置无统一前缀，靠正则 + names 挑出任务开关。"""
        declaration = load_task_switch_map()["ok-ww"]
        self.assertEqual(
            declaration["config"], "data/apps/ok-ww/working/configs/DailyTask.json"
        )
        self.assertEqual(declaration["task_pattern"], "(.+)")
        self.assertEqual(
            declaration["names"]["Farm Nightmare Nest for Daily Echo"],
            "使用梦魇巢穴获取日常声骸",
        )
