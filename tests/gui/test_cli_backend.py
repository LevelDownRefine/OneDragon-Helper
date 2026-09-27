"""真实 Qt 事件循环 + CLI 子进程，验证任务卡闭环与异步故障。"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtCore import QObject, QProcess, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QTest

from src.gui.cli_client import CliClient
from src.gui.controllers.cli_task_card import CliTaskCardController
from src.gui.controllers.task_card import TaskCardController
from src.gui.main_window import QmlBridge
from src.update.runtime import FileLease, UpdateBusyError
from tests.gui.helpers import get_app
from tests.support.headless import PROJECT_ROOT, HeadlessFixture


class DeferredClient(QObject):
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self.requests = []

    def request(self, method, params, callback):
        self.requests.append((method, params, callback))


class CliGuiTests(unittest.TestCase):
    def setUp(self):
        self.app = get_app()
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.fixture = HeadlessFixture(self.root)

    def wait_for(self, predicate, timeout=15):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(10)
        self.assertTrue(predicate(), "等待 Qt/CLI 状态超时")

    def client(self, command=None, timeout_ms=10000):
        client = CliClient(
            command=command or self.fixture.command("serve", "--stdio"),
            timeout_ms=timeout_ms,
        )
        self.addCleanup(client.close)
        return client

    def test_bridge_reads_and_writes_through_real_cli(self):
        client = self.client()
        with (
            patch("src.gui.controllers.background.BackgroundController.apply_current"),
            patch(
                "src.gui.controllers.game_list.ScriptIconProvider._load_icon",
                return_value=QPixmap(1, 1),
            ),
            patch(
                "src.service.app_service.AppService.load_config",
                side_effect=AssertionError("GUI 绕过 CLI 读列表"),
            ),
            patch(
                "src.gui.controllers.task_card.get_daily_readback",
                side_effect=AssertionError("GUI 绕过 CLI 反读"),
            ),
            patch(
                "src.service.app_service.AppService.set_script_daily_task",
                side_effect=AssertionError("GUI 绕过 CLI 写日常"),
            ),
        ):
            bridge = QmlBridge(cli_backend=True, cli_client=client)
            self.addCleanup(bridge.close_cli)
            self.wait_for(lambda: bridge.taskStatus == "已同步")
            self.assertEqual(
                [game["script_name"] for game in bridge.games], ["ok-ww", "自定义脚本"]
            )
            self.assertEqual(
                bridge.task_card.daily_items[0]["task_label"], "模拟领域 · 贝币"
            )
            pid = client._process.processId()
            bridge.selectDaily("每日任务", "凝素领域", 1)
            self.assertTrue(bridge.taskBusy)
            self.wait_for(lambda: not bridge.taskBusy)
            self.assertIn("凝素领域", bridge.task_card.daily_items[0]["task_label"])
            native = json.loads(self.fixture.native.read_text(encoding="utf-8"))
            self.assertEqual(native["Which to Farm"], "Forgery Challenge")
            self.assertEqual(native["Which Forgery Challenge to Farm"], 1)
            self.assertEqual(native["untouched"], self.fixture.initial["untouched"])
            bridge.selectWeeklyStart("幻梦游园", 0)
            self.wait_for(lambda: not bridge.taskBusy)
            self.assertEqual(bridge.task_card.weekly_items[0]["start_label"], "不启用")
            bridge.selectGame(1)
            self.wait_for(lambda: not bridge.taskBusy)
            self.assertEqual(bridge.task_card.daily_items, [])
            bridge.selectGame(0)
            self.wait_for(lambda: not bridge.taskBusy)
            self.assertIn("凝素领域", bridge.task_card.daily_items[0]["task_label"])
            self.assertEqual(pid, client._process.processId())
            with patch.object(bridge.launch, "launchAll") as launch:
                bridge.launchAll()
                bridge.maybe_auto_launch()
                launch.assert_not_called()
            # 明确杀死所属测试后端，窗口保留并允许用户刷新重连。
            client._process.kill()
            self.wait_for(lambda: "连接断开" in bridge.taskStatus)
            self.assertFalse(bridge.taskBusy)
            bridge.refreshTasks()
            self.wait_for(lambda: bridge.taskStatus == "已同步")
            self.assertIn("凝素领域", bridge.task_card.daily_items[0]["task_label"])
            bridge.close_cli()
            self.assertEqual(client._process.state(), QProcess.NotRunning)
            lock_path = self.root / ".update/runtime.lock"
            with (
                FileLease(lock_path),
                self.assertRaises(UpdateBusyError),
                FileLease(lock_path, shared=True),
            ):
                self.fail("CLI 退出后取得的独占锁未阻止共享锁")

    def test_stale_responses_do_not_replace_current_card(self):
        client = DeferredClient()
        games = SimpleNamespace(current_game={"script_name": "A", "display_name": "甲"})
        controller = CliTaskCardController(games, Mock(), Mock(), client)
        controller.refresh()
        games.current_game = {"script_name": "B", "display_name": "乙"}
        controller.refresh()
        view = {"script": {"script_name": "B"}, "dailies": [], "weeklies": []}
        client.requests[1][2](view, None)
        client.requests[0][2](
            {"script": {"script_name": "A"}, "dailies": [], "weeklies": []}, None
        )
        self.assertEqual(controller._view["script"]["script_name"], "B")
        self.assertFalse(controller.busy)

    def test_local_and_cli_cards_use_the_same_display_rules(self):
        dailies = [
            {
                "name": "未配置",
                "task": None,
                "sequence": None,
                "enabled": None,
                "options": {"values": [{"display_name": "默认副本"}]},
            },
            {
                "name": "二级",
                "task": "资源",
                "sequence": True,
                "enabled": True,
                "options": {
                    "values": [
                        {
                            "display_name": "资源",
                            "options": {
                                "values": [
                                    {"display_name": "开启", "physical_name": True}
                                ]
                            },
                        }
                    ]
                },
            },
            {
                "name": "停用",
                "task": "资源",
                "sequence": None,
                "enabled": False,
                "options": {"values": []},
            },
        ]
        weeklies = [
            {"name": "无副本", "options": None, "task": None, "start_day": None},
            {"name": "空菜单", "options": {"values": []}, "task": None, "start_day": 0},
            {
                "name": "选副本",
                "options": {"values": [{"display_name": "首领"}]},
                "task": None,
                "start_day": 3,
            },
        ]
        games = SimpleNamespace(current_game={"script_name": "A", "display_name": "甲"})
        service = Mock()
        service.get_daily_map.return_value = {
            "A": {
                "dailies": [
                    {"display_name": row["name"], "options": row["options"]}
                    for row in dailies
                ]
            }
        }
        service.get_weekly_map.return_value = [
            {
                "display_name": row["name"],
                **({"options": row["options"]} if row["options"] is not None else {}),
            }
            for row in weeklies
        ]
        starts = {row["name"]: row["start_day"] for row in weeklies}
        service.get_weekly_start_for.side_effect = lambda _script, name: starts[name]
        local = TaskCardController(games, service, Mock())
        with (
            patch(
                "src.gui.controllers.task_card.get_daily_readback", return_value=dailies
            ),
            patch("src.gui.controllers.task_card.get_weekly_task", return_value=None),
        ):
            daily_items, weekly_items = local.daily_items, local.weekly_items
        self.assertEqual(
            [row["task_label"] for row in daily_items],
            ["默认副本", "资源 · 开启", "不启用"],
        )
        self.assertEqual(
            [row["can_disable"] for row in daily_items], [False, True, True]
        )
        self.assertEqual([row["disabled"] for row in daily_items], [False, False, True])
        self.assertEqual(
            [row["task_label"] for row in weekly_items], ["", "", "选择副本"]
        )
        self.assertEqual(
            [row["start_label"] for row in weekly_items],
            ["选择周几", "不启用", "周三起"],
        )
        self.assertEqual(
            [row["start_set"] for row in weekly_items], [False, True, True]
        )
        self.assertEqual(
            [row["has_task"] for row in weekly_items], [False, False, True]
        )

        client = DeferredClient()
        remote = CliTaskCardController(games, service, Mock(), client)
        remote.refresh()
        client.requests[0][2](
            {"script": {"script_name": "A"}, "dailies": dailies, "weeklies": weeklies},
            None,
        )
        with (
            patch(
                "src.gui.controllers.task_card.get_daily_readback",
                side_effect=AssertionError("CLI 属性不得读盘"),
            ),
            patch(
                "src.gui.controllers.task_card.get_weekly_task",
                side_effect=AssertionError("CLI 属性不得读盘"),
            ),
        ):
            self.assertEqual(remote.daily_items, daily_items)
            self.assertEqual(remote.weekly_items, weekly_items)
            for name in ("未配置", "二级", "停用", "不存在"):
                self.assertEqual(remote.daily_options(name), local.daily_options(name))
            for name in ("无副本", "空菜单", "选副本", "不存在"):
                self.assertEqual(
                    remote.weekly_task_options(name), local.weekly_task_options(name)
                )
        self.assertEqual(len(client.requests), 1)

    def test_write_success_queries_before_enabling_editing(self):
        cases = (
            ("daily.select", "selectDaily", ("日常", "副本", 1)),
            ("daily.enable", "setDailyEnabled", ("日常", False)),
            ("weekly.select", "selectWeekly", ("周常", "副本")),
            ("weekly.start", "selectWeeklyStart", ("周常", 0)),
        )
        for method, slot, args in cases:
            with self.subTest(method=method):
                client = DeferredClient()
                games = SimpleNamespace(current_game={"script_name": "A"})
                toast = Mock()
                controller = CliTaskCardController(games, Mock(), toast, client)
                controller._view = {"dailies": [], "weeklies": [{"name": "周常"}]}
                getattr(controller, slot)(*args)
                self.assertTrue(controller.busy)
                client.requests[0][2](None, None)
                self.assertEqual(
                    [(r[0], r[1]) for r in client.requests[1:]],
                    [("script.view", {"script_name": "A"})],
                )
                self.assertEqual(client.requests[0][0], method)
                self.assertTrue(controller.busy)
                self.assertEqual(controller.status, "已保存 · 刷新中")
                getattr(controller, slot)(*args)
                self.assertEqual(len(client.requests), 2)
                view = {"script": {"script_name": "A"}, "dailies": [], "weeklies": []}
                client.requests[1][2](view, None)
                self.assertFalse(controller.busy)
                self.assertEqual(controller.status, "已同步")
                self.assertEqual(controller._view, view)
                toast.assert_not_called()

    def test_refresh_failure_preserves_write_confirmation_without_replaying(self):
        for code in ("operation_failed", "transport_failed"):
            with self.subTest(code=code):
                client = DeferredClient()
                games = SimpleNamespace(current_game={"script_name": "A"})
                toast = Mock()
                controller = CliTaskCardController(games, Mock(), toast, client)
                controller._view = {"dailies": [], "weeklies": [{"name": "周常"}]}
                controller.selectWeeklyStart("周常", 0)
                client.requests[0][2](None, None)
                client.requests[1][2](
                    None,
                    {"code": code, "message": "读取失败", "refresh_required": False},
                )
                if code == "transport_failed":
                    client.failed.emit("读取失败")
                self.assertFalse(controller.busy)
                self.assertEqual(controller._view, {"dailies": [], "weeklies": []})
                toast.assert_called_once_with("配置已保存，刷新失败：读取失败")
                self.assertEqual(
                    [r[0] for r in client.requests], ["weekly.start", "script.view"]
                )
                controller.refresh()
                self.assertEqual(
                    [r[0] for r in client.requests],
                    ["weekly.start", "script.view", "script.view"],
                )

    def test_switching_scripts_ignores_old_write_and_refresh_responses(self):
        for switch_after_ack in (False, True):
            with self.subTest(switch_after_ack=switch_after_ack):
                client = DeferredClient()
                games = SimpleNamespace(current_game={"script_name": "A"})
                toast = Mock()
                controller = CliTaskCardController(games, Mock(), toast, client)
                controller._view = {"dailies": [], "weeklies": [{"name": "周常"}]}
                controller.selectWeeklyStart("周常", 0)
                if switch_after_ack:
                    client.requests[0][2](None, None)
                games.current_game = {"script_name": "B"}
                controller.refresh()
                view = {"script": {"script_name": "B"}, "dailies": [], "weeklies": []}
                client.requests[-1][2](view, None)
                count = len(client.requests)
                if switch_after_ack:
                    client.requests[1][2](
                        {"script": {"script_name": "A"}, "dailies": [], "weeklies": []},
                        None,
                    )
                else:
                    client.requests[0][2](None, None)
                self.assertEqual(len(client.requests), count)
                self.assertEqual(controller._view, view)
                self.assertEqual(controller.status, "已同步")
                self.assertFalse(controller.busy)
                toast.assert_not_called()

    def test_write_failure_refreshes_without_replaying(self):
        client = DeferredClient()
        games = SimpleNamespace(current_game={"script_name": "A", "display_name": "甲"})
        toast = Mock()
        controller = CliTaskCardController(games, Mock(), toast, client)
        controller._view = {"dailies": [], "weeklies": [{"name": "周常"}]}
        controller.selectWeeklyStart("周常", 0)
        self.assertTrue(controller.busy)
        client.requests[0][2](
            None,
            {
                "code": "operation_failed",
                "message": "部分写入失败",
                "refresh_required": True,
            },
        )
        self.assertEqual(
            [r[0] for r in client.requests], ["weekly.start", "script.view"]
        )
        toast.assert_called_once_with("部分写入失败")

    def test_fragmented_utf8_and_stderr_do_not_block_event_loop(self):
        code = """
import json, sys, time
request = json.loads(sys.stdin.readline())
sys.stderr.write('x' * 100000)
sys.stderr.flush()
payload = (json.dumps({'protocol_version': 1, 'id': request['id'], 'result': {'name': '中文'}}, ensure_ascii=False) + '\\n').encode('utf-8')
cut = payload.index('中'.encode('utf-8')) + 1
sys.stdout.buffer.write(payload[:cut]); sys.stdout.buffer.flush()
time.sleep(0.1)
sys.stdout.buffer.write(payload[cut:]); sys.stdout.buffer.flush()
sys.stdin.read()
"""
        client = self.client([sys.executable, "-u", "-c", code])
        received, ticks = [], []
        timer = QTimer()
        timer.timeout.connect(lambda: ticks.append(1))
        timer.start(5)
        self.addCleanup(timer.stop)
        with patch("src.gui.cli_client.logger.info"):
            client.request(
                "app.snapshot",
                {},
                lambda result, error: received.append((result, error)),
            )
            self.wait_for(lambda: bool(received))
        self.assertEqual(received, [({"name": "中文"}, None)])
        self.assertGreater(len(ticks), 2)

    def test_process_failures_report_once_and_clear_pending(self):
        cases = (
            ("exit", [sys.executable, "-c", "raise SystemExit(3)"], 1000),
            ("timeout", [sys.executable, "-c", "import time; time.sleep(60)"], 100),
            (
                "bad_json",
                [
                    sys.executable,
                    "-u",
                    "-c",
                    "import sys; sys.stdin.readline(); sys.stdout.write('bad\\n'); sys.stdout.flush(); sys.stdin.read()",
                ],
                1000,
            ),
            (
                "null_error",
                [
                    sys.executable,
                    "-u",
                    "-c",
                    "import json, sys; r = json.loads(sys.stdin.readline()); "
                    "sys.stdout.write(json.dumps({'protocol_version': 1, "
                    "'id': r['id'], 'error': None}) + '\\n'); "
                    "sys.stdout.flush(); sys.stdin.read()",
                ],
                1000,
            ),
        )
        for name, command, timeout in cases:
            with self.subTest(name=name):
                client = self.client(command, timeout)
                received = []
                client.request(
                    "daily.select",
                    {},
                    lambda result, error, received=received: received.append(
                        (result, error)
                    ),
                )
                self.wait_for(lambda received=received: bool(received))
                self.wait_for(
                    lambda client=client: client._process.state() == QProcess.NotRunning
                )
                self.assertEqual(len(received), 1)
                self.assertEqual(received[0][1]["code"], "transport_failed")
                self.assertTrue(received[0][1]["refresh_required"])
                self.assertEqual(client._pending, {})
                self.assertEqual(client._outgoing, [])

    def test_qml_menus_send_integer_and_boolean_values(self):
        result = subprocess.run(
            [sys.executable, "-m", "tests.support.cli_gui_scene"],
            cwd=PROJECT_ROOT,
            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=40,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("ReferenceError", result.stderr)
        self.assertNotIn("TypeError", result.stderr)
