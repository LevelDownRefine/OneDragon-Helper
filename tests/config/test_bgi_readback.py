"""BGI 一条龙旧格式与用户编辑后的任务表兼容性。"""

import copy
import os
import subprocess
import sys
import textwrap
import unittest
from unittest.mock import patch

from src.config.daily import BgiDaily, Daily
from src.config.set_config import get_daily_readback
from src.config.task_config import get_daily_configs


class TestBgiReadback(unittest.TestCase):
    def setUp(self):
        self.enterContext(
            patch(
                "src.utils.utils_sub_config._load_config_yml",
                return_value={"script_list": []},
            )
        )
        self.daily = BgiDaily("BetterGI", get_daily_configs("BetterGI")[0], "原神")

    def test_legacy_task_names_are_read_and_written_without_migration(self):
        for fields in ({}, {"TaskDefinitions": {}}, {"TaskDefinitions": None}):
            config = fields | {"TaskEnabledList": {"自动秘境": False, "领取邮件": True}}
            expected = copy.deepcopy(config)
            expected["TaskEnabledList"]["自动秘境"] = True
            with (
                self.subTest(definitions=fields),
                patch.object(self.daily, "_load_daily_config", return_value=config),
                patch.object(self.daily, "_save_daily_config") as save,
            ):
                self.assertIs(self.daily.read_enabled(), False)
                self.assertTrue(self.daily.set_enabled(True))
                save.assert_called_once_with(expected)
                self.assertEqual(config, expected)

    def test_unavailable_switch_is_logged_and_never_guessed_or_written(self):
        cases = (
            {},
            {"TaskEnabledList": None},
            {"TaskEnabledList": []},
            {"TaskEnabledList": {"自动秘境": "true"}},
            {"TaskEnabledList": {"自动秘境": 1}},
            {"TaskDefinitions": [], "TaskEnabledList": {"自动秘境": True}},
            {
                "TaskDefinitions": {"mail": "领取邮件"},
                "TaskEnabledList": {"mail": True},
            },
            {"TaskDefinitions": {"domain": "自动秘境"}, "TaskEnabledList": {}},
            {
                "TaskDefinitions": {"first": "自动秘境", "copy": "自动秘境"},
                "TaskEnabledList": {"first": True, "copy": False},
            },
        )
        for config in cases:
            original = copy.deepcopy(config)
            with (
                self.subTest(config=config),
                patch.object(self.daily, "_load_daily_config", return_value=config),
                patch.object(self.daily, "_save_daily_config") as save,
                self.assertLogs("src.config.daily", level="WARNING"),
            ):
                self.assertIsNone(self.daily.read_enabled())
                self.assertFalse(self.daily.set_enabled(False))
                save.assert_not_called()
                self.assertEqual(config, original)

    def test_missing_native_task_does_not_hide_other_daily_rows(self):
        config = {
            "DomainName": "铭记之谷",
            "TaskDefinitions": {
                "mail": "领取邮件",
                "pot": "领取尘歌壶奖励",
                "stygian": "自动幽境危战",
                "domain": "自动秘境",
                "reward": "领取每日奖励",
                "miliastra": "千星",
                "weekly": "周常",
                "fodder": "狗粮",
            },
            "TaskEnabledList": {
                "mail": True,
                "pot": True,
                "stygian": False,
                "domain": True,
                "reward": True,
                "miliastra": True,
                "weekly": False,
                "fodder": True,
            },
        }
        with (
            patch.object(Daily, "_load_daily_config", return_value=config),
            # 幽境危战的开关在另一份文件（一条龙配置即本用例的 config 之外的 routine），
            # 此处显式判为无真相，避免读进真实安装目录。
            patch.object(Daily, "_load_routine_config", return_value=None),
            self.assertLogs("src.config.daily", level="WARNING"),
        ):
            records = get_daily_readback("BetterGI")
        # 缺原生任务的行原地留空（None），不隐藏其它行。
        self.assertEqual(
            [r["enabled"] for r in records],
            [True, None, None, None, True, True, True, True, False],
        )
        self.assertEqual(records[0]["task"], "铭记之谷")
        self.assertEqual(records[2]["name"], "首领讨伐")
        self.assertEqual(records[3]["name"], "幽境危战")
        self.assertEqual(records[8]["name"], "周常")

    def test_switch_to_bgi_updates_qml_daily_items_without_metacall_error(self):
        code = textwrap.dedent(
            """
            from unittest.mock import patch
            from PySide6.QtCore import QUrl, qInstallMessageHandler
            from PySide6.QtQml import QQmlComponent, QQmlEngine, qmlRegisterSingletonInstance
            from PySide6.QtWidgets import QApplication
            from src.config.daily import Daily
            from src.gui.controllers.background import BackgroundController
            from src.gui.main_window import QmlBridge
            from src.service.app_service import AppService

            app = QApplication([])
            messages = []
            qInstallMessageHandler(lambda kind, context, message: messages.append(message))
            scripts = [
                {"display_name": "其他脚本", "script_path": "other.py"},
                {"display_name": "原神", "script_path": "BetterGI.exe"},
            ]
            native = {
                "DomainName": "铭记之谷",
                "TaskDefinitions": {"domain": "自动秘境", "mail": "领取邮件"},
                "TaskEnabledList": {"domain": True, "mail": True},
            }
            with (
                patch("src.utils.utils_sub_config._load_config_yml",
                      return_value={"script_list": []}),
                patch.object(AppService, "load_config", return_value={"script_list": scripts}),
                patch.object(AppService, "get_daily_map", return_value={}),
                patch("src.service.daily_plan.load_schedule", return_value={}),
                patch.object(BackgroundController, "resolve_bg", return_value=None),
                patch.object(Daily, "_load_daily_config", return_value=native),
                # 幽境危战的开关在另一份文件：判为无真相，避免读进真实安装目录。
                patch.object(Daily, "_load_routine_config", return_value=None),
            ):
                bridge = QmlBridge()
                qmlRegisterSingletonInstance(QmlBridge, "OneDragonHelper", 1, 0, "Bridge", bridge)
                engine = QQmlEngine()
                component = QQmlComponent(engine)
                component.setData(b'''import QtQuick
            import OneDragonHelper 1.0
            Item { property var rows: Bridge.dailyItems }
            ''', QUrl())
                root = component.create()
                assert root is not None, component.errors()
                assert root.property("rows") == []
                bridge.selectGame(1)
                app.processEvents()
                rows = root.property("rows")
                assert len(rows) == 9, rows
                assert rows[0]["task_label"] == "铭记之谷", rows
                assert rows[3]["name"] == "幽境危战", rows
                assert rows[8]["name"] == "周常", rows
                assert [row["can_disable"] for row in rows] == (
                    [True, False, False, False, True] + [False] * 4), rows
                # 纯开关日常（无副本选项、有开关落点）chip 只表达开关态
                assert rows[4]["switch_only"] and rows[4]["task_label"] == "启用", rows
                assert not any("metacall" in m or "<NULL>" in m for m in messages), messages
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
