"""BGI 一条龙旧格式与用户编辑后的任务表兼容性。"""

import copy
import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from src.config.set_config import get_daily_readback
from src.config.task.daily import BgiDaily, Daily
from src.config.task.task_declarations import get_daily_configs


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
                self.assertLogs("src.config.task.daily", level="WARNING"),
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
            self.assertLogs("src.config.task.daily", level="WARNING"),
        ):
            records = get_daily_readback("BetterGI")
        self.assertEqual([r["enabled"] for r in records], [True, None, None, None])
        self.assertEqual(records[0]["task"], "铭记之谷")
        self.assertEqual(records[2]["name"], "首领讨伐")
        self.assertEqual(records[3]["name"], "幽境危战")

    def test_switch_to_bgi_updates_qml_daily_items_without_metacall_error(self):
        code = textwrap.dedent(
            r"""
            import importlib.util
            import json
            import sys
            from pathlib import Path
            from unittest.mock import patch
            import tests  # 子进程同样启用后端真实生成配置访问绊线。
            from jsonrpcserver import dispatch_to_serializable
            from PySide6.QtCore import QCoreApplication, QEvent, QUrl, qInstallMessageHandler
            from PySide6.QtQml import (
                QQmlComponent, QQmlEngine, qmlClearTypeRegistrations, qmlRegisterSingletonInstance,
            )
            from gui.cli_client import CliFailure
            from gui.main_window import QmlBridge
            from src.config.task.daily import Daily
            from src.headless import _parse_json, rpc_methods
            from src.service.app_service import AppService

            helper_path = Path(tests.__file__).resolve().parents[2] / "python-gui/tests/gui/helpers.py"
            spec = importlib.util.spec_from_file_location("_bgi_gui_rpc_helpers", helper_path)
            helpers = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = helpers
            spec.loader.exec_module(helpers)
            app = helpers.get_app()
            messages = []
            previous_handler = qInstallMessageHandler(
                lambda kind, context, message: messages.append(message)
            )
            scripts = [
                {"display_name": "其他脚本", "script_path": "other.py"},
                {"display_name": "原神", "script_path": "BetterGI.exe"},
            ]
            native = {
                "DomainName": "铭记之谷",
                "TaskDefinitions": {"domain": "自动秘境"},
                "TaskEnabledList": {"domain": True},
            }
            with (
                patch("src.utils.utils_sub_config._load_config_yml",
                      return_value={"script_list": []}),
                patch("src.utils.utils_config.load_config", return_value={"script_list": scripts}),
                patch("src.service.task_service.load_config", return_value={"script_list": scripts}),
                patch("src.service.task_service.get_weekly_map", return_value=[]),
                patch.object(AppService, "settings_view", side_effect=helpers.settings_view),
                patch.object(AppService, "wallpaper_view", side_effect=helpers.wallpaper_view),
                patch.object(AppService, "game_icon_path",
                             side_effect=lambda name: {"script_name": name, "path": None}),
                patch.object(Daily, "_load_daily_config", return_value=native),
                # 幽境危战的开关在另一份文件：判为无真相，避免读进真实安装目录。
                patch.object(Daily, "_load_routine_config", return_value=None),
            ):
                service = AppService()
                methods = rpc_methods(service)

                def dispatch(method, params):
                    response = dispatch_to_serializable(
                        json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}),
                        methods=methods, deserializer=_parse_json,
                    )
                    if "error" in response:
                        error = response["error"]
                        return CliFailure(error["code"], error["message"])
                    assert "result" in response
                    return response["result"]

                client = helpers.FakeCliClient(handler=dispatch)
                bridge = QmlBridge(cli_client=client)
                helpers.drain_events()
                qmlRegisterSingletonInstance(QmlBridge, "OneDragonHelper", 1, 0, "Bridge", bridge)
                engine = QQmlEngine()
                component = QQmlComponent(engine)
                root = None
                try:
                    component.setData(
                        b"import QtQuick\nimport OneDragonHelper 1.0\nItem { property var rows: Bridge.dailyItems }",
                        QUrl(),
                    )
                    root = component.create()
                    assert root is not None, component.errors()
                    assert root.property("rows") == []
                    bridge.selectGame(1)
                    helpers.drain_events()
                    rows = root.property("rows")
                    assert len(rows) == 4, rows
                    assert rows[0]["task_label"] == "铭记之谷", rows
                    assert rows[3]["name"] == "幽境危战", rows
                    assert [row["can_disable"] for row in rows] == [True, False, False, False], rows
                    assert ("script.view", {"script_name": "BetterGI"}) in client.requests
                finally:
                    # Singleton 必须比 QML engine 活得更久，不能依赖解释器退出顺序。
                    if root is not None:
                        root.deleteLater()
                    component.deleteLater()
                    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
                    engine.deleteLater()
                    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
                    qmlClearTypeRegistrations()
                    bridge.deleteLater()
                    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
                    client.close()
                    service.close()
                    qInstallMessageHandler(previous_handler)
                assert not any("metacall" in m or "<NULL>" in m for m in messages), messages
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            env=dict(
                os.environ,
                PYTHONPATH=str(Path(__file__).resolve().parents[2]),
                QT_QPA_PLATFORM="offscreen",
                PYTHONUTF8="1",
                PYTHONFAULTHANDLER="1",
            ),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
